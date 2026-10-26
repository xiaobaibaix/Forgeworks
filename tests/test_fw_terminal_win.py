import json
import os
import queue
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import fw_pty_win      # noqa: E402
import fw_terminal     # noqa: E402


class FakePtyProcess:
    def __init__(self, argv, cwd, env, dimensions):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.dimensions = dimensions
        self.pid = 4242
        self.writes = []
        self.sizes = []
        self.terminated = False
        self.closed = False
        self.exit_code = 0
        self._dead = False
        self._pending = queue.Queue()

    @classmethod
    def spawn(cls, argv, cwd=None, env=None, dimensions=(24, 80)):
        cls.last = cls(argv, cwd, env, dimensions)
        return cls.last

    def feed(self, text):
        self._pending.put(text)

    def end(self, exit_code=0):
        self.exit_code = exit_code
        self._dead = True
        self._pending.put(None)

    def read(self, size=1024):
        item = self._pending.get()
        if item is None:
            raise EOFError('Pty is closed')
        return item

    def write(self, text):
        if self.closed:
            raise EOFError('Pty is closed')
        self.writes.append(text)

    def setwinsize(self, rows, cols):
        self.sizes.append((rows, cols))

    def isalive(self):
        return not (self._dead or self.terminated or self.closed)

    def terminate(self, force=False):
        self.terminated = True

    def close(self, force=False):
        self.closed = True
        self._pending.put(None)

    @property
    def exitstatus(self):
        return None if self.isalive() else self.exit_code


def install_fake_winpty():
    module = types.ModuleType('winpty')
    module.PtyProcess = FakePtyProcess
    sys.modules['winpty'] = module


class WinptyTestCase(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get('winpty')
        install_fake_winpty()

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('winpty', None)
        else:
            sys.modules['winpty'] = self._saved


class AvailabilityTests(WinptyTestCase):
    def setUp(self):
        super().setUp()
        sys.modules.pop('winpty', None)

    def test_missing_dependency_explains_install(self):
        status = fw_pty_win.terminal_status('win32')
        self.assertFalse(status['available'])
        self.assertIn('pip install pywinpty', status['reason'])

    def test_prefers_pwsh(self):
        install_fake_winpty()

        def fake_which(name):
            return {'pwsh': 'C:/pwsh.exe', 'powershell': 'C:/powershell.exe'}.get(name)

        with mock.patch.object(fw_pty_win.shutil, 'which', side_effect=fake_which):
            status = fw_pty_win.terminal_status('win32')
        self.assertTrue(status['available'], status['reason'])
        self.assertEqual(status['shell'], 'C:/pwsh.exe')

    def test_falls_back_to_comspec(self):
        install_fake_winpty()
        with mock.patch.object(fw_pty_win.shutil, 'which', return_value=None), \
                mock.patch.dict(os.environ, {'COMSPEC': 'C:/Windows/system32/cmd.exe'}):
            status = fw_pty_win.terminal_status('win32')
        self.assertEqual(status['shell'], 'C:/Windows/system32/cmd.exe')


class WindowsSessionTests(WinptyTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self._saved_shell = os.environ.get('COMSPEC')
        os.environ['COMSPEC'] = 'C:/pwsh.exe'
        self.killed = []
        for patcher in (
            mock.patch.object(fw_pty_win, 'kill_tree', side_effect=self.killed.append),
            mock.patch.object(fw_pty_win.shutil, 'which', return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.session = fw_pty_win.WindowsSession(self.temp.name)

    def tearDown(self):
        self.session.stop()
        if self._saved_shell is None:
            os.environ.pop('COMSPEC', None)
        else:
            os.environ['COMSPEC'] = self._saved_shell
        self.temp.cleanup()
        super().tearDown()

    def test_spawn_dimensions_and_env(self):
        proc = FakePtyProcess.last
        self.assertEqual(proc.argv, ['C:/pwsh.exe'])
        self.assertEqual(proc.cwd, self.temp.name)
        self.assertEqual(proc.dimensions, (30, 100))
        self.assertNotIn('CLAUDECODE', proc.env)

    def test_round_trip_write_resize_and_stop(self):
        proc = FakePtyProcess.last
        client = self.session.add_client()
        proc.feed('hello 中文\r\n')
        self.assertEqual(client.get(timeout=2), 'hello 中文\r\n'.encode('utf-8'))

        self.session.write('echo 你好\r'.encode('utf-8'))
        self.assertEqual(proc.writes, ['echo 你好\r'])

        self.session.resize(123, 45)
        self.assertEqual((self.session.cols, self.session.rows), (123, 45))
        self.assertEqual(proc.sizes, [(45, 123)])

        self.session.stop()
        self.assertEqual(self.killed, [4242])
        self.assertTrue(proc.terminated)
        self.assertFalse(self.session._reader.is_alive())
        self.assertIsNotNone(self.session.exited_at)

    def test_resize_clamps_to_supported_range(self):
        self.session.resize(1, 9999)
        self.assertEqual((self.session.cols, self.session.rows), (2, 300))
        self.assertEqual(FakePtyProcess.last.sizes, [(300, 2)])

    def test_reader_eof_marks_exit_and_wakes_clients(self):
        proc = FakePtyProcess.last
        client = self.session.add_client()
        proc.feed('bye\r\n')
        self.assertEqual(client.get(timeout=2), b'bye\r\n')
        proc.end(exit_code=3)
        self.assertIsNone(client.get(timeout=2))
        for _ in range(40):
            if self.session.exited_at is not None:
                break
            time.sleep(0.025)
        self.assertIsNotNone(self.session.exited_at)
        self.assertEqual(self.session.exit_code, 3)

    def test_write_after_close_is_ignored(self):
        self.session.stop()
        self.session.write(b'ignored')
        self.assertEqual(FakePtyProcess.last.writes, [])


class ClaudeCommandWindowsTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.gettempdir(), 'forgeworks-mcp-9123.json')
        if os.path.exists(self.path):
            os.remove(self.path)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def test_writes_mcp_config_file(self):
        with mock.patch.object(fw_terminal.shutil, 'which', return_value='C:/npm/claude.cmd'):
            info = fw_terminal.claude_command(9123, platform='win32')
        self.assertTrue(info['available'], info.get('reason'))
        self.assertEqual(info['command'], 'claude --mcp-config "%s"' % self.path)
        with open(self.path, encoding='utf-8') as handle:
            config = json.load(handle)
        server = config['mcpServers']['forgeworks']
        self.assertEqual(server['args'], [fw_terminal.MCP_SERVER])
        self.assertEqual(server['env']['FORGEWORKS_BRIDGE'], 'http://127.0.0.1:9123')

    def test_missing_claude_is_reported(self):
        with mock.patch.object(fw_terminal.shutil, 'which', return_value=None):
            info = fw_terminal.claude_command(9123, platform='win32')
        self.assertFalse(info['available'])
        self.assertIn('claude', info['reason'])
        self.assertFalse(os.path.exists(self.path))


if __name__ == '__main__':
    unittest.main()
