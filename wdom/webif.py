#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
from asyncio import coroutine, Future, ensure_future
from typing import Optional
from xml.dom import Node

from wdom.interface import Event

logger = logging.getLogger(__name__)


class WebIF:
    @property
    def ownerDocument(self) -> Optional[Node]:
        return None

    def __init__(self, *args, **kwargs):
        self._reqid = 0
        self._tasks = {}
        super().__init__(*args, **kwargs)

    @property
    def connected(self) -> bool:
        '''When this instance has any connection, return True.'''
        return bool(self.ownerDocument and self.ownerDocument.connections)

    def on_message(self, msg: dict):
        '''called when webscoket get message.'''
        logger.debug('{tag}: {msg}'.format(tag=self.tag, msg=msg))

        msg_type = msg.get('type')
        if msg_type == 'event':
            self._handle_event(msg)
        elif msg_type == 'response':
            self._handle_response(msg)

    def _handle_event(self, msg):
        _e = msg.get('event', {})
        event = Event(**_e)
        self.dispatchEvent(event=event)

    def _handle_response(self, msg):
        response = msg.get('data', False)
        if response:
            task = self._tasks.pop(msg.get('reqid'), False)
            if task and not task.cancelled() and not task.done():
                task.set_result(msg.get('data'))

    def js_exec(self, method:str, *args) -> Optional[Future]:
        '''Execute ``method`` in the related node on browser, via web socket
        connection. Other keyword arguments are passed to ``params`` attribute.
        If this node is not in any document tree (namely, this node does not
        have parent node), the ``method`` is not executed.
        '''
        if self.connected:
            return ensure_future(
                self.ws_send(dict(method=method, params=args))
            )

    def js_query(self, query) -> Future:
        if self.connected:
            self.js_exec(query, self._reqid)
            fut = Future()
            self._tasks[self._reqid] = fut
            self._reqid += 1
            return fut
        else:
            fut = Future()
            fut.set_result(None)
            return fut

    @coroutine
    def ws_send(self, obj):
        '''Send message to the related nodes on browser, with ``tagname`` and
        ``id`` which specifies relation between python's object and element
        on browser. The message is serialized by JSON object and send via
        WebSocket connection.
        '''
        obj['target'] = 'node'
        obj['id'] = self.id
        obj['tag'] = self.tag
        msg = json.dumps(obj)
        if self.ownerDocument:
            for conn in self.ownerDocument.connections:
                conn.write_message(msg)
