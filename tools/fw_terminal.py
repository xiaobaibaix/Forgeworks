#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内嵌终端会话层：PTY、输出广播、会话回收。

前端通过 Bridge 的 terminal 路由使用；本模块只依赖标准库。
"""

import hmac
import json
import os
import queue
import secrets
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time

try:
    import fcntl
    import pty
    import termios
except ImportError:  # Windows 没有 pty，Bridge 仍要能导入本模块
    fcntl = pty = termios = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, 'tools', 'fw_pty_exec.py')
MCP_SERVER = os.path.join(ROOT, 'tools', 'mcp_forgeworks.py')

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


def shell_path():
    for candidate in (os.environ.get('SHELL'), '/bin/zsh', '/bin/bash', '/bin/sh'):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which('sh')


def terminal_availability(platform=None):
    platform = sys.platform if platform is None else platform
    if platform.startswith('win'):
        return {'available': False, 'platform': platform, 'shell': None,
                'reason': 'Windows 暂不支持内嵌终端（需要 ConPTY 适配）'}
    if pty is None:
        return {'available': False, 'platform': platform, 'shell': None,
                'reason': '当前 Python 缺少 pty 支持'}
    shell = shell_path()
    return {'available': bool(shell), 'platform': platform, 'shell': shell,
            'reason': '' if shell else '未找到可用的 shell'}


def claude_command(port):
    binary = shutil.which('claude')
    if not binary:
        return {'available': False, 'command': None,
                'reason': '未找到 claude 命令，请先安装 Claude Code CLI'}
    config = {'mcpServers': {'forgeworks': {
        'command': sys.executable or 'python3',
        'args': [MCP_SERVER],
        'env': {'FORGEWORKS_BRIDGE': 'http://127.0.0.1:%d' % port},
    }}}
    command = '%s --mcp-config %s' % (
        shlex.quote(binary), shlex.quote(json.dumps(config, ensure_ascii=False)))
    return {'available': True, 'command': command, 'reason': ''}


def set_winsize(fd, cols, rows):
    cols = max(2, min(int(cols or 100), 500))
    rows = max(2, min(int(rows or 30), 300))
    if fcntl is not None and termios is not None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    return cols, rows


def _signal_group(proc, sig):
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return
    except OSError:
        pass
    try:
        proc.send_signal(sig)
    except OSError:
        pass


class TerminalSession:
    def __init__(self, cwd, shell=None, cols=100, rows=30):
        if pty is None:
            raise TerminalUnavailable('当前平台不支持 PTY')
        self.id = secrets.token_hex(8)
        self.token = secrets.token_urlsafe(32)
        self.cwd = cwd
        self.shell = shell or shell_path()
        if not self.shell:
            raise TerminalUnavailable('未找到可用的 shell')
        self.cols, self.rows = cols, rows
        self.created_at = time.time()
        self.exited_at = None
        self.exit_code = None
        self.idle_since = None
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._clients = set()
        self._history = bytearray()
        self._stopped = False
        self._master = None
        self._proc = None
        self._reader = None
        self.pid = None
        self._start()

    def _start(self):
        master, slave = pty.openpty()
        env = os.environ.copy()
        env.update({'TERM': 'xterm-256color', 'COLORTERM': 'truecolor', 'LANG': env.get('LANG') or 'en_US.UTF-8'})
        env.pop('CLAUDECODE', None)
        env.pop('CLAUDE_CODE_ENTRYPOINT', None)
        try:
            self._proc = subprocess.Popen(
                [sys.executable, SHIM, self.shell],
                stdin=slave, stdout=slave, stderr=slave,
                cwd=self.cwd, env=env, start_new_session=True, close_fds=True)
        except Exception:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self._master = master
        self.pid = self._proc.pid
        self.cols, self.rows = set_winsize(master, self.cols, self.rows)
        self._reader = threading.Thread(target=self._read_loop, name='fw-term-%s' % self.id, daemon=True)
        self._reader.start()

    def _read_loop(self):
        try:
            while True:
                try:
                    data = os.read(self._master, READ_CHUNK)
                except OSError:
                    break
                if not data:
                    break
                self._broadcast(data)
        finally:
            # master 必须由读线程关闭：macOS 上跨线程 close 会与阻塞中的 read 互锁
            try:
                os.close(self._master)
            except OSError:
                pass
            self._mark_exit()

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

    def write(self, data):
        if not data:
            return
        with self._io_lock:
            view = memoryview(data)
            while view:
                try:
                    written = os.write(self._master, view)
                except OSError:
                    return
                view = view[written:]

    def resize(self, cols, rows):
        self.cols, self.rows = set_winsize(self._master, cols, rows)

    def _mark_exit(self):
        with self._lock:
            if self.exited_at is not None:
                return
            self.exited_at = time.time()
            self.exit_code = self._proc.poll() if self._proc is not None else None
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.put_nowait(None)
            except queue.Full:
                pass

    def stop(self):
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            # 交互式 zsh 忽略 SIGTERM，SIGHUP 才是终端挂断的正确信号
            _signal_group(proc, signal.SIGHUP)
            try:
                proc.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                _signal_group(proc, signal.SIGKILL)
                try:
                    proc.wait(timeout=STOP_GRACE)
                except subprocess.TimeoutExpired:
                    pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=STOP_GRACE)
        self._mark_exit()

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


class TerminalManager:
    def __init__(self, port, max_sessions=MAX_SESSIONS):
        self.port = port
        self.max_sessions = max_sessions
        self._sessions = {}
        self._lock = threading.Lock()
        self._janitor = None

    def start(self, cwd, cols=100, rows=30):
        status = terminal_availability()
        if not status['available']:
            raise TerminalUnavailable(status['reason'] or '终端不可用')
        if not cwd or not os.path.isdir(cwd):
            raise TerminalError('项目目录不存在，请先在「同步」页绑定项目')
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise TerminalLimit('终端会话已达上限（%d）' % self.max_sessions)
        session = TerminalSession(cwd, shell=status['shell'], cols=cols, rows=rows)
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                session.stop()
                raise TerminalLimit('终端会话已达上限（%d）' % self.max_sessions)
            self._sessions[session.id] = session
        self._ensure_janitor()
        return session

    def get(self, session_id, token=None):
        if not session_id or not token:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None or not hmac.compare_digest(session.token, str(token)):
            return None
        return session

    def stop(self, session_id):
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.stop()

    def shutdown_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()

    def status(self):
        with self._lock:
            sessions = list(self._sessions.values())
        return [{'id': s.id, 'cwd': s.cwd, 'alive': s.exited_at is None,
                 'clients': s.client_count(), 'createdAt': s.created_at} for s in sessions]

    def _ensure_janitor(self):
        if self._janitor is not None and self._janitor.is_alive():
            return
        self._janitor = threading.Thread(target=self._janitor_loop, name='fw-terminal-janitor', daemon=True)
        self._janitor.start()

    def _janitor_loop(self):
        while True:
            time.sleep(JANITOR_INTERVAL)
            now = time.time()
            with self._lock:
                sessions = list(self._sessions.items())
            for session_id, session in sessions:
                if session.should_reap(now):
                    self.stop(session_id)
            with self._lock:
                if not self._sessions:
                    self._janitor = None
                    return
