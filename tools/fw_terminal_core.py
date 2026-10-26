#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端会话的跨平台部分：输出历史、客户端广播、退出与回收判定。

POSIX（pty）与 Windows（ConPTY）后端都继承 SessionCore，只实现进程与 PTY 的差异。
"""

import queue
import secrets
import threading
import time

MAX_SESSIONS = 4
HISTORY_BYTES = 256 * 1024
CLIENT_QUEUE = 512
READ_CHUNK = 65536
MAX_INPUT_BYTES = 64 * 1024
STOP_GRACE = 2.0
ORPHAN_GRACE = 300
FINISHED_GRACE = 60
JANITOR_INTERVAL = 5


class TerminalError(Exception):
    pass


class TerminalUnavailable(TerminalError):
    pass


class TerminalLimit(TerminalError):
    pass


def clamp_size(cols, rows):
    return (max(2, min(int(cols or 100), 500)),
            max(2, min(int(rows or 30), 300)))


class SessionCore:
    def __init__(self, cwd, shell, cols=100, rows=30):
        self.id = secrets.token_hex(8)
        self.token = secrets.token_urlsafe(32)
        self.cwd = cwd
        self.shell = shell
        self.cols, self.rows = clamp_size(cols, rows)
        self.created_at = time.time()
        self.exited_at = None
        self.exit_code = None
        self.idle_since = None
        self.pid = None
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._clients = set()
        self._history = bytearray()
        self._stopped = False
        self._reader = None
        self._start()

    def _start(self):
        raise NotImplementedError

    def _exit_code(self):
        return None

    def write(self, data):
        raise NotImplementedError

    def resize(self, cols, rows):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def _broadcast(self, data):
        with self._lock:
            self._history.extend(data)
            if len(self._history) > HISTORY_BYTES:
                del self._history[:-HISTORY_BYTES]
            for client in list(self._clients):
                try:
                    client.put_nowait(data)
                except queue.Full:
                    self._clients.discard(client)

    def add_client(self):
        client = queue.Queue(maxsize=CLIENT_QUEUE)
        with self._lock:
            if self._history:
                client.put_nowait(bytes(self._history))
            if self.exited_at is not None:
                client.put_nowait(None)
            else:
                self._clients.add(client)
                self.idle_since = None
        return client

    def has_client(self, client):
        with self._lock:
            return client in self._clients

    def drop_client(self, client):
        with self._lock:
            self._clients.discard(client)

    def client_count(self):
        with self._lock:
            return len(self._clients)

    def _mark_exit(self):
        with self._lock:
            if self.exited_at is not None:
                return
            self.exited_at = time.time()
            self.exit_code = self._exit_code()
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.put_nowait(None)
            except queue.Full:
                pass

    def should_reap(self, now):
        if self.exited_at is not None:
            return now - self.exited_at > FINISHED_GRACE
        with self._lock:
            if self._clients:
                self.idle_since = None
                return False
            if self.idle_since is None:
                self.idle_since = now
                return False
            return now - self.idle_since > ORPHAN_GRACE
