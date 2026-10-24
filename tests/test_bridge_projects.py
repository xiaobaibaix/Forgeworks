import base64
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
    meta = {'name': '钻机', 'sizeCm': [100, 100, 200], 'contentHash': 'abc'}
    manifest['assets'][asset_id] = {
        'kind': 'machine',
        'state': 'exported',
        'files': {'mesh': [{'path': asset_id + '.glb', 'sha1': 'sha1', 'size': 4}]},
        'meta': meta,
    }
    source_dir = fw_project.asset_source_dir(fw_root, 'machine', asset_id, meta, manifest)
    manifest['assets'][asset_id]['sourceDir'] = source_dir
    base = fw_root / source_dir
    base.mkdir(parents=True, exist_ok=True)
    (base / (asset_id + '.glb')).write_bytes(b'glTF')
    pipeline = base / 'pipeline'
    pipeline.mkdir()
    (pipeline / 'prompt.txt').write_text('钻机描述词', encoding='utf-8')
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')


def _write_content(fw_root, content=None):
    payload = content or {'items': [], 'recipes': [], 'elements': [], 'machines': [], 'techs': []}
    (fw_root / 'project.json').write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return payload


class BridgeContentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []
        created = bridge.create_project(str(self.workspace), '内容工程')
        self.root = Path(created['fwDir'])
        self.events = []
        self.old_push = bridge.push_event
        bridge.push_event = lambda kind, data=None: self.events.append((kind, data))

    def tearDown(self):
        bridge.push_event = self.old_push
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.temp.cleanup()

    def test_revision_blocks_stale_full_write(self):
        first = _write_content(self.root)
        revision = fw_project.content_revision(self.root)
        self.assertTrue(revision)

        changed = dict(first, meta={'name': '新'})
        saved = bridge.save_content_checked(self.root, changed, revision, 'ui', 'tab-1')
        self.assertTrue(saved['ok'], saved)
        self.assertNotEqual(saved['revision'], revision)
        self.assertEqual(self.events[-1][0], 'content.changed')
        self.assertEqual(self.events[-1][1]['source'], 'ui')
        self.assertEqual(self.events[-1][1]['clientId'], 'tab-1')

        stale = bridge.save_content_checked(self.root, first, revision)
        self.assertTrue(stale['conflict'], stale)
        self.assertEqual(fw_project.load_content(self.root)['meta']['name'], '新')

    def test_upsert_and_delete_entity(self):
        _write_content(self.root)
        created = bridge.upsert_entity(self.root, 'elements',
                                       {'id': 'Fe', 'name': '铁'}, source='mcp')
        self.assertTrue(created['ok'], created)
        self.assertTrue(created['created'])

        updated = bridge.upsert_entity(self.root, 'elements',
                                       {'id': 'Fe', 'name': '纯铁'}, source='mcp')
        self.assertTrue(updated['ok'], updated)
        self.assertFalse(updated['created'])
        content = fw_project.load_content(self.root)
        self.assertEqual(content['elements'], [{'id': 'Fe', 'name': '纯铁'}])

        deleted = bridge.delete_entity(self.root, 'elements', 'Fe')
        self.assertTrue(deleted['ok'], deleted)
        self.assertEqual(fw_project.load_content(self.root)['elements'], [])

        missing = bridge.delete_entity(self.root, 'elements', 'Fe')
        self.assertTrue(missing['notFound'], missing)
        self.assertEqual(self.events[-1][1]['entity']['op'], 'delete')

    def test_upsert_honors_base_revision(self):
        _write_content(self.root)
        revision = fw_project.content_revision(self.root)
        self.assertTrue(bridge.upsert_entity(self.root, 'items', {'id': 'I1'},
                                             revision)['ok'])
        conflict = bridge.upsert_entity(self.root, 'items', {'id': 'I2'}, revision)
        self.assertTrue(conflict['conflict'], conflict)
        ids = [row['id'] for row in fw_project.load_content(self.root)['items']]
        self.assertEqual(ids, ['I1'])

    def test_upsert_validates_input(self):
        _write_content(self.root)
        with self.assertRaises(ValueError):
            bridge.upsert_entity(self.root, 'unknown', {'id': 'X'})
        with self.assertRaises(ValueError):
            bridge.upsert_entity(self.root, 'items', {'name': '无 ID'})
        with self.assertRaises(ValueError):
            bridge.upsert_entity(self.root, 'items', ['not-a-dict'])


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

        exported = ue_root / 'Forgeworks' / '_Source' / '机器' / '钻机'
        self.assertTrue((exported / 'M1.glb').is_file())
        self.assertFalse((exported / 'pipeline').exists())
        self.assertFalse((exported / 'prompt.txt').exists())

    def test_export_and_publish_item_icon(self):
        created = bridge.create_project(str(self.workspace), '图标工程')
        fw_root = Path(created['fwDir'])
        exported = bridge.export_asset('item', 'I1', {
            'icon': {'path': 'I1.png', 'b64': base64.b64encode(b'fake-png').decode()},
        }, {'name': '铁矿石', 'type': 'raw', 'iconHash': 'h1'})
        self.assertTrue(exported['ok'], exported)
        self.assertTrue((fw_root / '_Source' / '物品' / '图标' / '铁矿石' / 'I1.png').is_file())

        ue_root = self.workspace / 'Game'
        ue_root.mkdir()
        (ue_root / 'Game.uproject').write_text('{}', encoding='utf-8')
        self.assertTrue(bridge.set_ue_target(str(ue_root))['ok'])

        result = bridge.publish_to_ue()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['published'], ['I1'])
        published = ue_root / 'Forgeworks' / '_Source' / '物品' / '图标' / '铁矿石' / 'I1.png'
        self.assertTrue(published.is_file())
        self.assertEqual(published.read_bytes(), b'fake-png')

    def test_export_and_publish_element_icon(self):
        created = bridge.create_project(str(self.workspace), '元素工程')
        fw_root = Path(created['fwDir'])
        exported = bridge.export_asset('element', 'Fe', {
            'icon': {'path': 'Fe.png', 'b64': base64.b64encode(b'fake-element-png').decode()},
        }, {'name': '铁', 'symbol': 'Fe', 'tier': 1, 'iconHash': 'eh1'})
        self.assertTrue(exported['ok'], exported)

        icon_path = fw_root / '_Source' / '元素' / '铁' / 'Fe.png'
        self.assertTrue(icon_path.is_file())
        manifest = json.loads((fw_root / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
        record = manifest['assets']['Fe']
        self.assertEqual(record['kind'], 'element')
        self.assertEqual(record['files']['icon'][0]['path'], 'Fe.png')
        self.assertEqual(record['meta']['iconHash'], 'eh1')
        self.assertEqual(record['sourceDir'], '_Source/元素/铁')

        ue_root = self.workspace / 'Game'
        ue_root.mkdir()
        (ue_root / 'Game.uproject').write_text('{}', encoding='utf-8')
        self.assertTrue(bridge.set_ue_target(str(ue_root))['ok'])

        result = bridge.publish_to_ue()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['published'], ['Fe'])
        published = ue_root / 'Forgeworks' / '_Source' / '元素' / '铁' / 'Fe.png'
        self.assertTrue(published.is_file())
        self.assertEqual(published.read_bytes(), b'fake-element-png')
        self.assertFalse((published.parent / 'pipeline').exists())

    def test_export_rejects_cross_kind_id_collision(self):
        created = bridge.create_project(str(self.workspace), '冲突工程')
        fw_root = Path(created['fwDir'])
        first = bridge.export_asset('item', 'X1', {
            'icon': {'path': 'X1.png', 'b64': base64.b64encode(b'item').decode()},
        }, {'name': '方块', 'iconHash': 'i1'})
        self.assertTrue(first['ok'], first)

        second = bridge.export_asset('element', 'X1', {
            'icon': {'path': 'X1.png', 'b64': base64.b64encode(b'element').decode()},
        }, {'name': '氙', 'symbol': 'Xe', 'iconHash': 'e1'})
        self.assertFalse(second['ok'], second)
        self.assertIn('已被其他类型占用', second['error'])
        self.assertTrue((fw_root / '_Source' / '物品' / '图标' / '方块' / 'X1.png').is_file())
        self.assertFalse((fw_root / '_Source' / '元素' / '氙').exists())


class BridgeExportMergeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []
        created = bridge.create_project(str(self.workspace), '导出合并')
        self.root = Path(created['fwDir'])
        self.old_find_blender = bridge.find_blender
        self.old_queue = bridge._queue_blender_check
        self.old_push = bridge.push_event
        self.queued = []
        bridge.find_blender = lambda: '/fake/blender'
        bridge._queue_blender_check = lambda *args: self.queued.append(args)
        bridge.push_event = lambda kind, data=None: None

    def tearDown(self):
        bridge.find_blender = self.old_find_blender
        bridge._queue_blender_check = self.old_queue
        bridge.push_event = self.old_push
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.temp.cleanup()

    @staticmethod
    def _file(path, payload=b'x'):
        return {'path': path, 'b64': base64.b64encode(payload).decode('ascii')}

    def test_icon_then_mesh_keeps_both_roles_and_meta(self):
        first = bridge.export_asset(
            'machine', 'M1',
            {'icon': self._file('M1_icon.png', b'\x89PNG\r\n\x1a\n')},
            {'name': '钻机', 'iconHash': 'i1', 'iconSource': 'generated'})
        self.assertTrue(first['ok'], first)
        second = bridge.export_asset(
            'machine', 'M1',
            {'mesh': self._file('M1.glb', b'glTF')},
            {'name': '钻机', 'modelHash': 'm1'})
        self.assertTrue(second['ok'], second)
        record = bridge.load_manifest()['assets']['M1']
        self.assertEqual(sorted(record['files']), ['icon', 'mesh'])
        self.assertEqual(record['meta']['iconHash'], 'i1')
        self.assertEqual(record['meta']['iconSource'], 'generated')
        self.assertEqual(record['meta']['modelHash'], 'm1')
        self.assertEqual(len(self.queued), 1)

    def test_mesh_then_icon_preserves_mesh(self):
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'mesh': self._file('M1.glb', b'glTF')}, {'name': '钻机'})['ok'])
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'\x89PNG\r\n\x1a\n')},
            {'name': '钻机', 'iconHash': 'i2'})['ok'])
        record = bridge.load_manifest()['assets']['M1']
        self.assertEqual(sorted(record['files']), ['icon', 'mesh'])
        self.assertEqual(record['files']['mesh'][0]['path'], 'M1.glb')

    def test_same_role_replaces_old_entry(self):
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'old')}, {'name': '钻机'})['ok'])
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'new')}, {'name': '钻机'})['ok'])
        record = bridge.load_manifest()['assets']['M1']
        self.assertEqual(len(record['files']['icon']), 1)
        with open(self.root / record['sourceDir'] / 'M1_icon.png', 'rb') as stream:
            self.assertEqual(stream.read(), b'new')

    def test_icon_only_machine_does_not_queue_blender(self):
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'\x89PNG\r\n\x1a\n')},
            {'name': '钻机'})['ok'])
        self.assertEqual(self.queued, [])


if __name__ == '__main__':
    unittest.main()
