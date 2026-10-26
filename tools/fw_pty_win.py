#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 内嵌终端后端：ConPTY 由 pywinpty 提供。

仅 Windows 使用；pywinpty 缺失时以 TerminalUnavailable 明确报错，不影响 Bridge 其它功能。
"""

import os
import shutil
import subprocess
import threading
import time

from fw_terminal_core import (READ_CHUNK, STOP_GRACE, SessionCore,
                              TerminalUnavailable, clamp_size)

INSTALL_HINT = '未安装 pywinpty，请先在 Windows 上执行 pip install pywinpty'


def _load_pty_process():
    try:
        from winpty import PtyProcess
    except ImportError:
        raise TerminalUnavailable(INSTALL_HINT)
    return PtyProcess


def shell_path():
    for name in ('pwsh', 'powershell'):
        found = shutil.which(name)
        if found:
            return found
    return os.environ.get('COMSPEC') or shutil.which('cmd')


def terminal_status(platform='win32'):
    try:
        _load_pty_process()
    except TerminalUnavailable:
        return {'available': False, 'platform': platform, 'shell': None,
                'reason': INSTALL_HINT}
    shell = shell_path()
    return {'available': bool(shell), 'platform': platform, 'shell': shell,
            'reason': '' if shell else '未找到可用的 shell'}


def kill_tree(pid):
    # ConPTY 只负责把控制台输出接到伪终端，子进程不会随 shell 一起退出
    if not pid:
        return
    try:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                       capture_output=True, timeout=STOP_GRACE)
    except (OSError, subprocess.SubprocessError):
        pass


class WindowsSession(SessionCore):
    def __init__(self, cwd, shell=None, cols=100, rows=30):
        self._proc = None
        super().__init__(cwd, shell or shell_path(), cols, rows)

    def _start(self):
        if not self.shell:
            raise TerminalUnavailable('未找到可用的 shell')
        PtyProcess = _load_pty_process()
        env = os.environ.copy()
        env.pop('CLAUDECODE', None)
        env.pop('CLAUDE_CODE_ENTRYPOINT', None)
        try:
            self._proc = PtyProcess.spawn([self.shell], cwd=self.cwd, env=env,
                                          dimensions=(self.rows, self.cols))
        except FileNotFoundError:
            raise TerminalUnavailable('未找到可用的 shell：%s' % self.shell)
        self.pid = getattr(self._proc, 'pid', None)
        self._reader = threading.Thread(target=self._read_loop,
                                        name='fw-term-win-%s' % self.id, daemon=True)
        self._reader.start()

    def _read_loop(self):
        try:
            while True:
                try:
                    chunk = self._proc.read(READ_CHUNK)
                except (EOFError, OSError, ValueError):
                    break
                if chunk:
                    self._broadcast(chunk.encode('utf-8', 'replace'))
        finally:
            self._mark_exit()

    def _exit_code(self):
        if self._proc is None:
            return None
        try:
            return self._proc.exitstatus
        except (OSError, ValueError):
            return None

    def write(self, data):
        if not data:
            return
        text = data.decode('utf-8', 'replace') if isinstance(data, (bytes, bytearray)) else str(data)
        with self._io_lock:
            try:
                self._proc.write(text)
            except (EOFError, OSError, ValueError):
                return

    def resize(self, cols, rows):
        self.cols, self.rows = clamp_size(cols, rows)
        try:
            self._proc.setwinsize(self.rows, self.cols)
        except (EOFError, OSError, ValueError):
            pass

    def _alive(self):
        try:
            return bool(self._proc and self._proc.isalive())
        except (OSError, ValueError):
            return False

    def stop(self):
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        if self._alive():
            kill_tree(self.pid)
            try:
                self._proc.terminate(force=True)
            except (EOFError, OSError, ValueError):
                pass
            deadline = time.time() + STOP_GRACE
            while time.time() < deadline and self._alive():
                time.sleep(0.05)
        if self._proc is not None:
            try:
                self._proc.close()
            except (EOFError, OSError, ValueError):
                pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=STOP_GRACE)
        self._mark_exit()
