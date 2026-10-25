import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
_argv = sys.argv
sys.argv = [_argv[0]]          # bridge 在导入时读 argv[1] 当端口
import bridge
sys.argv = _argv


@unittest.skipUnless(sys.platform.startswith('win'), 'Windows 目录选择器')
class PickFolderWindowsTest(unittest.TestCase):
    """Windows 上目录框必须置顶，否则会被前台窗口盖住，用户以为按钮没反应。"""

    def _run(self, returncode=0, stdout='', stderr=''):
        completed = subprocess.CompletedProcess([], returncode, stdout, stderr)
        with mock.patch.object(bridge.subprocess, 'run', return_value=completed) as run:
            return bridge.pick_folder(), run

    def test_dialog_uses_topmost_owner(self):
        result, run = self._run(stdout='C:\\work')
        self.assertEqual(result, {'ok': True, 'path': 'C:\\work'})
        script = run.call_args[0][0][-1]
        self.assertIn('TopMost = $true', script)
        self.assertIn('ShowDialog($owner)', script)

    def test_user_cancel_is_cancelled(self):
        result, _ = self._run(returncode=0, stdout='')
        self.assertEqual(result, {'ok': False, 'cancelled': True})

    def test_powershell_failure_is_reported(self):
        result, _ = self._run(returncode=1, stderr='Add-Type failed')
        self.assertFalse(result['ok'])
        self.assertNotIn('cancelled', result)
        self.assertIn('Add-Type failed', result['error'])


if __name__ == '__main__':
    unittest.main()
