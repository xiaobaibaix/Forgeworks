import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
_argv = sys.argv
sys.argv = [_argv[0]]          # bridge 在导入时读 argv[1] 当端口
import bridge
sys.argv = _argv
import fw_project


def _write_legacy_store(ue_root):
    store = ue_root / 'Forgeworks'
    (store / '_Sync').mkdir(parents=True)
    (store / '_Sync' / 'manifest.json').write_text(
        json.dumps({'schemaVersion': 1, 'project': {'name': '旧项目'}, 'assets': {}}),
        encoding='utf-8')
    return store


def _write_machine(fw_root, asset_id='M1'):
    manifest_file = fw_root / '_Sync' / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    manifest['assets'][asset_id] = {
        'kind': 'machine',
        'state': 'exported',
        'sourceDir': '_Source/Machines/%s' % asset_id,
        'files': {'mesh': [{'path': asset_id + '.glb', 'sha1': 'sha1', 'size': 4}]},
        'meta': {'name': '钻机', 'sizeCm': [100, 100, 200], 'contentHash': 'abc'},
    }
    base = fw_root / '_Source' / 'Machines' / asset_id
    base.mkdir(parents=True)
    (base / (asset_id + '.glb')).write_bytes(b'glTF')
    pipeline = base / 'pipeline'
    pipeline.mkdir()
    (pipeline / 'prompt.txt').write_text('钻机描述词', encoding='utf-8')
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')


class BridgeProjectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []

    def tearDown(self):
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.temp.cleanup()

    def test_create_and_open_independent_project(self):
        result = bridge.create_project(str(self.workspace), '独立工程')
        self.assertTrue(result['ok'], result)
        root = Path(result['fwDir'])
        self.assertTrue((root / 'forgeworks.project.json').is_file())
        self.assertEqual(bridge.project_root(), str(root))
        self.assertIsNone(result['ueTarget'])

    def test_legacy_workspace_migrates_without_ue_target(self):
        ue_root = self.workspace / 'ResWs'
        store = _write_legacy_store(ue_root)
        bridge._state['projectRoot'] = str(ue_root)
        bridge._state['ueProjectRoot'] = str(ue_root)

        bridge.normalize_bound_project()

        self.assertEqual(bridge.project_root(), str(store))
        self.assertTrue((store / 'forgeworks.project.json').is_file())
        self.assertIsNone(bridge.ue_project_root())

    def test_legacy_ue_project_cannot_target_itself(self):
        ue_root = self.workspace / 'MyGame'
        ue_root.mkdir()
        (ue_root / 'MyGame.uproject').write_text('{}', encoding='utf-8')
        _write_legacy_store(ue_root)

        opened = bridge.open_project(str(ue_root))
        self.assertTrue(opened['ok'], opened)
        self.assertIsNone(opened['ueTarget'])
        self.assertEqual(bridge.project_root(), str(ue_root / 'Forgeworks'))

        rejected = bridge.set_ue_target(str(ue_root))
        self.assertFalse(rejected['ok'])
        self.assertIn('Forgeworks 项目', rejected['error'])

    def test_publish_only_ships_mesh(self):
        created = bridge.create_project(str(self.workspace), '导出工程')
        fw_root = Path(created['fwDir'])
        _write_machine(fw_root)

        ue_root = self.workspace / 'Game'
        ue_root.mkdir()
        (ue_root / 'Game.uproject').write_text('{}', encoding='utf-8')
        self.assertTrue(bridge.set_ue_target(str(ue_root))['ok'])

        result = bridge.publish_to_ue()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['published'], ['M1'])

        exported = ue_root / 'Forgeworks' / '_Source' / 'Machines' / 'M1'
        self.assertTrue((exported / 'M1.glb').is_file())
        self.assertFalse((exported / 'pipeline').exists())
        self.assertFalse((exported / 'prompt.txt').exists())


if __name__ == '__main__':
    unittest.main()
