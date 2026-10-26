#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内嵌终端会话层：POSIX 用 pty，Windows 交给 pywinpty（ConPTY）。

前端通过 Bridge 的 terminal 路由使用；本模块只依赖标准库。
"""

import hmac
import json
import os
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time

from fw_terminal_core import (CLIENT_QUEUE, FINISHED_GRACE, HISTORY_BYTES,
                              JANITOR_INTERVAL, MAX_INPUT_BYTES, MAX_SESSIONS,
                              ORPHAN_GRACE, READ_CHUNK, STOP_GRACE,
                              SessionCore, TerminalError, TerminalLimit,
                              TerminalUnavailable, clamp_size)

try:
    import fcntl
    import pty
    import termios
except ImportError:  # Windows 没有 pty，Bridge 仍要能导入本模块
    fcntl = pty = termios = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, 'tools', 'fw_pty_exec.py')
MCP_SERVER = os.path.join(ROOT, 'tools', 'mcp_forgeworks.py')


def shell_path():
    for candidate in (os.environ.get('SHELL'), '/bin/zsh', '/bin/bash', '/bin/sh'):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which('sh')


def _windows_status(platform):
    try:
        import fw_pty_win
    except ImportError as error:
        return {'available': False, 'platform': platform, 'shell': None,
                'reason': 'Windows 终端组件不可用：%s' % error}
    return fw_pty_win.terminal_status(platform)


def terminal_availability(platform=None):
    platform = sys.platform if platform is None else platform
    if platform.startswith('win'):
        return _windows_status(platform)
    if pty is None:
        return {'available': False, 'platform': platform, 'shell': None,
                'reason': '当前 Python 缺少 pty 支持'}
    shell = shell_path()
    return {'available': bool(shell), 'platform': platform, 'shell': shell,
            'reason': '' if shell else '未找到可用的 shell'}


def claude_command(port, platform=None):
    platform = sys.platform if platform is None else platform
    binary = shutil.which('claude')
    if not binary:
        return {'available': False, 'command': None,
                'reason': '未找到 claude 命令，请先安装 Claude Code CLI'}
    config = {'mcpServers': {'forgeworks': {
        'command': sys.executable or 'python3',
        'args': [MCP_SERVER],
        'env': {'FORGEWORKS_BRIDGE': 'http://127.0.0.1:%d' % port},
    }}}
    if platform.startswith('win'):
        # cmd 与 PowerShell 的内联 JSON 引号规则不同，落成文件两边都能直接用
        path = os.path.join(tempfile.gettempdir(), 'forgeworks-mcp-%d.json' % port)
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(config, handle, ensure_ascii=False)
        except OSError as error:
            return {'available': False, 'command': None,
                    'reason': '无法写入 MCP 配置：%s' % error}
        return {'available': True, 'command': 'claude --mcp-config "%s"' % path,
                'reason': '', 'configPath': path}
    command = '%s --mcp-config %s' % (
        shlex.quote(binary), shlex.quote(json.dumps(config, ensure_ascii=False)))
    return {'available': True, 'command': command, 'reason': ''}


def set_winsize(fd, cols, rows):
    cols, rows = clamp_size(cols, rows)
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


class TerminalSession(SessionCore):
    def __init__(self, cwd, shell=None, cols=100, rows=30):
        if pty is None:
            raise TerminalUnavailable('当前平台不支持 PTY')
        self._master = None
        self._proc = None
        super().__init__(cwd, shell or shell_path(), cols, rows)

    def _start(self):
        if not self.shell:
            raise TerminalUnavailable('未找到可用的 shell')
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

    def _exit_code(self):
        return self._proc.poll() if self._proc is not None else None

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


def create_session(cwd, shell=None, cols=100, rows=30):
    if os.name == 'nt':
        import fw_pty_win
        return fw_pty_win.WindowsSession(cwd, shell=shell, cols=cols, rows=rows)
    return TerminalSession(cwd, shell=shell, cols=cols, rows=rows)


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
        session = create_session(cwd, shell=status['shell'], cols=cols, rows=rows)
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
