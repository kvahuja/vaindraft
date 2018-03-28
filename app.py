#!/usr/bin/env python
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Simplified chat demo for websockets.

Authentication, error handling, etc are left as an exercise for the reader :)
"""

import logging
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import os.path
import uuid
import json

from tornado.options import define, options
from tornado import gen
from datetime import datetime

define("port", default=8888, help="run on the given port", type=int)
define("debug", default=False, help="enable or disable debug mode", type=bool)

heroes = [
    'adagio',
    'alpha',
    'ardan',
    'baptiste',
    'baron',
    'blackfeather',
    'catherine',
    'celeste',
    'churnwalker',
    'flicker',
    'fortress',
    'glaive',
    'grace',
    'grumpjaw',
    'gwen',
    'idris',
    'joule',
    'kestrel',
    'koshka',
    'krul',
    'lance',
    'lorelai',
    'lyra',
    'ozo',
    'petal',
    'phinn',
    'reim',
    'reza',
    'ringo',
    'rona',
    'samuel',
    'saw',
    'skaarf',
    'skye',
    'taka',
    'tony',
    'varya',
    'vox',
]

draft_styles = {
    '1': [
            {'index': 1, 'side': '1', 'type': 'ban'},
            {'index': 2, 'side': '2', 'type': 'ban'},
            {'index': 3, 'side': '2', 'type': 'ban'},
            {'index': 4, 'side': '1', 'type': 'ban'},
            {'index': 5, 'side': '1', 'type': 'pick'},
            {'index': 6, 'side': '2', 'type': 'pick'},
        ],
}

class DraftState():
    def __init__(self, style):
        self.style = style
        self.turn = 0
        self.history = []

    def get_id(self):
        return self.style

    def get_style(self):
        return draft_styles[self.style]

    def get_history(self):
        return self.history

    def get_turn(self):
        return self.turn

    def next_turn(self):
        self.turn += 1

    def update_draft(self, event):
        self.next_turn()
        self.history.append(event)

    def is_turn(self, team):
        return draft_styles[self.style][self.turn]['side'] == team

    def is_ended(self):
        return self.turn > len(draft_styles[self.style])

    def to_dict(self):
        return self.__dict__

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__,
            sort_keys=True, indent=4)


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", MainHandler),
            (r"/draft/([a-zA-Z0-9]*)/([a-zA-Z0-9]*)/([a-zA-Z0-9]*)$", MainHandler),
            (r"/chatsocket", ChatSocketHandler),
            (r"/chatsocket/([a-zA-Z0-9]*)/([a-zA-Z0-9]*)/([a-zA-Z0-9]*)$", ChatSocketHandler),
        ]
        settings = dict(
            cookie_secret="__TODO:_GENERATE_YOUR_OWN_RANDOM_VALUE_HERE__",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            xsrf_cookies=True,
            debug=options.debug,
        )
        super(Application, self).__init__(handlers, **settings)


class MainHandler(tornado.web.RequestHandler):
    """
    Main request handler for the root path and for chat rooms.
    """

    @tornado.web.asynchronous
    def get(self, room=None, role=None, draft_style=None):
        if not room:
            self.redirect("/draft/1")
            return

        # Set chat room as instance var (should be validated).
        self.room = str(room)
        self.role = str(role)
        self.draft_state = DraftState(str(draft_style))

        self.render("index.html", messages=[], room=self.room, role=self.role, draft_style_id=self.draft_state.get_id() , draft_style=self.draft_state.get_style(), heroes=heroes)

class ChatSocketHandler(tornado.websocket.WebSocketHandler):
    """
    Handler for dealing with websockets. It receives, stores and distributes new messages.
    """
    waiters = {}
    draft_states = {}

    @gen.engine
    def open(self, room=None, role=None, draft_style=None):
        """
        Called when socket is opened.
        """
        # Check if room is set.
        if not room:
            self.write_message({'error': 1, 'textStatus': 'Error: No room specified'})
            self.close()
            return

        self.room = str(room)
        self.role = str(role)

        if room in self.waiters:
            if role in [client['role'] for client in self.waiters[room]]:
                logging.info('Error: Role already specified')
                self.write_message({'error': 1, 'textStatus': 'Error: Role already specified'})
                self.room = None
                self.close()
            else:
                self.waiters[room].append({'waiter': self, 'role': self.role})
                draft_state = self.draft_states[room]
                message = draft_state.get_history()
                self.send_update(self, message)
        else:
            self.waiters[room] = [{'waiter': self, 'role': self.role}]

        if room not in self.draft_states:
            self.draft_states[room] = DraftState(draft_style)


    @classmethod
    def send_updates(cls, room, message):
        logging.info("sending message to %d waiters in room %s", len(cls.waiters[room]), room)
        for client in cls.waiters[room]:
            try:
                client['waiter'].write_message(message)
            except:
                logging.error("Error sending message", exc_info=True)

    @classmethod
    def send_update(cls, waiter, message):
        logging.info("sending message to waiter %s", waiter)
        try:
            waiter.write_message(message)
        except:
            logging.error("Error sending message", exc_info=True)


    def on_message(self, message):
        """
        Callback when new message received via the socket.
        """
        logging.info('Received new message %r', message)

        draft_state = self.draft_states[self.room]
        logging.info('Draft state: %s', draft_state.to_json())

        if draft_state.is_ended():
            logging.info('Draft has ended')
            event = {
                'time': str(datetime.now()),
                'type': 'message',
                'message': 'Draft has ended',
            }
            self.send_updates(self.room, event)
            self.close()
            return

        if not draft_state.is_turn(self.role):
            logging.info('Not your turn')
            message = {
                'time': str(datetime.now()),
                'type': 'message',
                'message': 'Not your turn',
            }
            self.send_update(self, message)
            return

        event = {
            'time': str(datetime.now()),
            'type': 'update',
            'hero': message,
        }

        draft_state.update_draft(event)

        event['index'] = draft_state.get_turn()
        self.send_updates(self.room, event)

        self.draft_states[self.room] = draft_state

    def on_close(self):
        """
        Callback when the socket is closed. Frees up resource related to this socket.
        """
        if not self.room:
            return

        remove_clients = [client for client in self.waiters[self.room] if client['role'] == self.role]
        for client in remove_clients:
            self.waiters[self.room].remove(client)

        if not self.waiters[self.room]:
            del self.waiters[self.room]



def main():
    tornado.options.parse_command_line()
    app = Application()
    app.listen(options.port)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
