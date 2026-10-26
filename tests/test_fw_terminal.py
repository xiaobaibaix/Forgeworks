import base64
import http.client
import json
import os
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
_bridge_args = sys.argv
sys.argv = [sys.argv[0]]
import bridge        # noqa: E402
import fw_terminal   # noqa: E402
sys.argv = _bridge_args

POSIX = os.name != 'nt'


def read_until(session, client, marker, timeout=10):
    buffer = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = client.get(timeout=0.2)
        except Exception:
            if not session.has_client(client):
                break
            continue
        if chunk is None:
            break
        buffer += chunk
        if marker in buffer:
            return buffer
    return buffer


def decode_output(raw):
    out = b''
    for match in re.findall(rb'event: output\ndata: (.*)\n', raw):
        out += base64.b64decode(json.loads(match)['b64'])
    return out


class AvailabilityTests(unittest.TestCase):
    def test_windows_is_reported_unavailable(self):
        status = fw_terminal.terminal_availability('win32')
        self.assertFalse(status['available'])
        self.assertIn('Windows', status['reason'])

    @unittest.skipUnless(POSIX, 'PTY 终端仅支持 macOS/Linux')
    def test_posix_reports_shell(self):
        status = fw_terminal.terminal_availability()
        self.assertTrue(status['available'], status['reason'])
        self.assertTrue(os.path.isfile(status['shell']))


@unittest.skipUnless(POSIX, 'PTY 终端仅支持 macOS/Linux')
class TerminalSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_resize_and_stop(self):
        session = fw_terminal.TerminalSession(self.temp.name)
        client = session.add_client()
        try:
            session.write(b"printf 'FW_TERM_OK\\n'\r")
            output = read_until(session, client, b'FW_TERM_OK\r\n')
            self.assertIn(b'FW_TERM_OK\r\n', output)

            session.resize(123, 45)
            self.assertEqual((session.cols, session.rows), (123, 45))
            winsize = fcntl_ioctl_winsize(session._master)
            self.assertEqual(winsize, (45, 123))

            proc = session._proc
            session.stop()
            self.assertIsNotNone(proc.poll())
            self.assertFalse(session._reader.is_alive())
            with self.assertRaises(ProcessLookupError):
                os.kill(session.pid, 0)
        finally:
            session.stop()

    def test_history_replays_to_late_client(self):
        session = fw_terminal.TerminalSession(self.temp.name)
        try:
            first = session.add_client()
            session.write(b"printf 'FW_HISTORY\\n'\r")
            self.assertIn(b'FW_HISTORY\r\n', read_until(session, first, b'FW_HISTORY\r\n'))
            session.drop_client(first)
            second = session.add_client()
            self.assertIn(b'FW_HISTORY', read_until(session, second, b'FW_HISTORY'))
        finally:
            session.stop()


def fcntl_ioctl_winsize(fd):
    import fcntl
    import termios
    rows, cols, _, _ = struct.unpack('HHHH', fcntl.ioctl(fd, termios.TIOCGWINSZ, b'\0' * 8))
    return rows, cols


@unittest.skipUnless(POSIX, 'PTY 终端仅支持 macOS/Linux')
class TerminalManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = fw_terminal.TerminalManager(8787, max_sessions=1)

    def tearDown(self):
        self.manager.shutdown_all()
        self.temp.cleanup()

    def test_token_and_limit(self):
        session = self.manager.start(self.temp.name)
        self.assertIs(self.manager.get(session.id, session.token), session)
        self.assertIsNone(self.manager.get(session.id, 'wrong'))
        self.assertIsNone(self.manager.get(session.id))
        with self.assertRaises(fw_terminal.TerminalLimit):
            self.manager.start(self.temp.name)
        self.manager.shutdown_all()
        self.assertEqual(self.manager.status(), [])
        with self.assertRaises(ProcessLookupError):
            os.kill(session.pid, 0)

    def test_claude_command_points_at_mcp_server(self):
        info = fw_terminal.claude_command(9123)
        if not info['available']:
            self.assertIn('claude', info['reason'])
            return
        self.assertIn('--mcp-config', info['command'])
        self.assertIn(fw_terminal.MCP_SERVER, info['command'])
        self.assertIn('http://127.0.0.1:9123', info['command'])


@unittest.skipUnless(POSIX, 'PTY 终端仅支持 macOS/Linux')
class TerminalHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        project = Path(self.temp.name) / 'ue'
        project.mkdir()
        (project / 'Fixture.uproject').write_text('{}')
        self._old_state = dict(bridge._state)
        self._old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(Path(self.temp.name) / 'state.json')
        bridge._state.clear()
        self.assertTrue(bridge.open_project(str(project))['ok'])
        self.server = bridge.Bridge(('127.0.0.1', 0), bridge.BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.base = 'http://127.0.0.1:%d' % self.port

    def tearDown(self):
        bridge._TERMINAL.shutdown_all()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        bridge.STATE_FILE = self._old_state_file
        bridge._state.clear()
        bridge._state.update(self._old_state)
        self.temp.cleanup()

    def post(self, route, body, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(
            '%s/api/%s' % (self.base, route), data=json.dumps(body).encode(),
            headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), json.loads(error.read())

    def start_session(self):
        status, headers, payload = self.post('terminal/start', {'cols': 90, 'rows': 24}, origin=self.base)
        self.assertEqual(status, 200, payload)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        return payload

    def test_start_requires_loopback_origin(self):
        status, _, _ = self.post('terminal/start', {'cols': 80, 'rows': 24})
        self.assertEqual(status, 403)
        status, _, _ = self.post('terminal/start', {'cols': 80, 'rows': 24}, origin='http://evil.example')
        self.assertEqual(status, 403)

    def test_stream_and_input_require_token(self):
        session = self.start_session()
        status, _, _ = self.post('terminal/input', {'sessionId': session['id'], 'token': 'bad',
                                                   'data': base64.b64encode(b'x').decode()}, origin=self.base)
        self.assertEqual(status, 403)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('GET', '/api/terminal/stream/%s?token=bad' % session['id'])
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()

    def test_end_to_end_round_trip(self):
        session = self.start_session()
        payload = base64.b64encode(b"printf 'FW_HTTP_OK\\n'\r").decode()
        status, _, result = self.post('terminal/input', {'sessionId': session['id'], 'token': session['token'],
                                                        'data': payload}, origin=self.base)
        self.assertEqual(status, 200, result)
        time.sleep(0.8)

        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('GET', '/api/terminal/stream/%s?token=%s' % (session['id'], session['token']))
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
        raw = b''
        deadline = time.time() + 2.5
        while time.time() < deadline:
            try:
                chunk = response.fp.read1(65536)
            except (socket.timeout, TimeoutError):
                break
            if not chunk:
                break
            raw += chunk
        connection.close()

        self.assertIn(b'event: ready', raw)
        self.assertIn(b'FW_HTTP_OK', decode_output(raw))

        status, _, result = self.post('terminal/stop', {'sessionId': session['id'], 'token': session['token']},
                                      origin=self.base)
        self.assertEqual(status, 200, result)
        self.assertFalse(any(row['id'] == session['id'] for row in bridge._TERMINAL.status()))
        with self.assertRaises(ProcessLookupError):
            os.kill(session['pid'], 0)

    def test_loopback_host_guard_and_cors(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.putrequest('GET', '/api/terminal/status', skip_host=True, skip_accept_encoding=True)
        connection.putheader('Host', 'evil.example')
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()

        status, headers, payload = self.post('terminal/start', {'cols': 80, 'rows': 24}, origin=self.base)
        self.assertEqual(status, 200, payload)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('GET', '/api/status')
        response = connection.getresponse()
        self.assertEqual(response.getheader('Access-Control-Allow-Origin'), '*')
        connection.close()


if __name__ == '__main__':
    unittest.main()
