import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_project


def _write_machine(root, asset_id='M1', mesh=True, icon=True):
    manifest_file = root / '_Sync' / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.is_file() else {
        'schemaVersion': 1,
        'project': {'name': root.name, 'kind': 'forgeworks', 'root': str(root)},
        'assets': {},
    }
    files = {
        'mesh': [{'path': asset_id + '.glb', 'sha1': 'mesh-sha1', 'size': 4}],
        'preview': [{'path': asset_id + '_preview.svg', 'sha1': 'svg-sha1', 'size': 4}],
    }
    if icon:
        files['icon'] = [{'path': asset_id + '_icon.png', 'sha1': 'icon-sha1', 'size': 8}]
    meta = {'name': '钻机', 'sizeCm': [100, 100, 200], 'contentHash': 'abc'}
    manifest['assets'][asset_id] = {
        'kind': 'machine',
        'state': 'exported',
        'files': files,
        'meta': meta,
    }
    source_dir = fw_project.asset_source_dir(root, 'machine', asset_id, meta, manifest)
    manifest['assets'][asset_id]['sourceDir'] = source_dir
    base = root / source_dir
    base.mkdir(parents=True, exist_ok=True)
    if mesh:
        (base / (asset_id + '.glb')).write_bytes(b'glTF')
    (base / (asset_id + '_preview.svg')).write_text('<svg/>', encoding='utf-8')
    if icon:
        (base / (asset_id + '_icon.png')).write_bytes(b'\x89PNG\r\n\x1a\n')
    pipeline = base / 'pipeline'
    pipeline.mkdir()
    (pipeline / 'graph.json').write_text('{}', encoding='utf-8')
    (pipeline / 'prompt.txt').write_text('钻机描述词', encoding='utf-8')
    (root / '_Sync').mkdir(exist_ok=True)
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def _write_item(root, asset_id='I1', icon=True):
    manifest_file = root / '_Sync' / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    meta = {'name': '铁矿石', 'type': 'raw', 'iconHash': 'h1'}
    manifest['assets'][asset_id] = {
        'kind': 'item',
        'state': 'exported',
        'files': {'icon': [{'path': asset_id + '.png', 'sha1': 'icon-sha1', 'size': 8}]},
        'meta': meta,
    }
    source_dir = fw_project.asset_source_dir(root, 'item', asset_id, meta, manifest)
    manifest['assets'][asset_id]['sourceDir'] = source_dir
    base = root / source_dir
    base.mkdir(parents=True, exist_ok=True)
    if icon:
        (base / (asset_id + '.png')).write_bytes(b'\x89PNG\r\n\x1a\n')
    (base / 'prompt.txt').write_text('铁矿石描述词', encoding='utf-8')
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def _write_element(root, asset_id='Fe', name='铁', icon=True):
    manifest_file = root / '_Sync' / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    meta = {'name': name, 'symbol': 'Fe', 'iconHash': 'eh1'}
    files = {'icon': [{'path': asset_id + '.png', 'sha1': 'icon-sha1', 'size': 8}]} if icon else {}
    manifest['assets'][asset_id] = {
        'kind': 'element',
        'state': 'exported',
        'files': files,
        'meta': meta,
    }
    source_dir = fw_project.asset_source_dir(root, 'element', asset_id, meta, manifest)
    manifest['assets'][asset_id]['sourceDir'] = source_dir
    base = root / source_dir
    base.mkdir(parents=True, exist_ok=True)
    if icon:
        (base / (asset_id + '.png')).write_bytes(b'\x89PNG\r\n\x1a\n')
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


class ProjectLifecycleTest(unittest.TestCase):
    def test_create_project_writes_marker_and_store(self):
        with tempfile.TemporaryDirectory() as directory:
            result = fw_project.create_project(directory, '重装工程')
            root = Path(result['root'])
            self.assertTrue((root / 'forgeworks.project.json').is_file())
            self.assertTrue((root / '_Source' / '机器').is_dir())
            self.assertTrue((root / '_Source' / '物品' / '图标').is_dir())
            self.assertTrue((root / '_Source' / '材质').is_dir())
            self.assertTrue((root / '_Sync').is_dir())
            marker = json.loads((root / 'forgeworks.project.json').read_text(encoding='utf-8'))
            self.assertEqual(marker['name'], '重装工程')
            self.assertIn('forgeworks', (root / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))

    def test_create_project_rejects_unsafe_name(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('', '..', '../x', 'a/b', '.hidden'):
                with self.assertRaises(ValueError):
                    fw_project.create_project(directory, name)

    def test_detect_accepts_project_and_legacy_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = Path(fw_project.create_project(directory, 'FW')['root'])
            self.assertEqual(fw_project.detect_project(str(root))['kind'], 'project')

            legacy = parent / 'UEProject'
            (legacy / 'Forgeworks' / '_Sync').mkdir(parents=True)
            (legacy / 'Forgeworks' / '_Sync' / 'manifest.json').write_text('{}', encoding='utf-8')
            found = fw_project.detect_project(str(legacy))
            self.assertEqual(found['root'], str(legacy / 'Forgeworks'))
            self.assertEqual(found['ueRoot'], str(legacy))
            self.assertEqual(found['kind'], 'legacy')

    def test_project_content_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fw_project.create_project(directory, 'FW')['root']
            self.assertIsNone(fw_project.load_content(root))
            fw_project.save_content(root, {'items': [], 'recipes': []})
            self.assertEqual(fw_project.load_content(root), {'items': [], 'recipes': []})
            with self.assertRaises(ValueError):
                fw_project.save_content(root, ['not', 'an', 'object'])


class NamingAndMigrationTest(unittest.TestCase):
    def test_sanitize_keeps_chinese_and_replaces_illegal_chars(self):
        self.assertEqual(fw_project.sanitize_asset_folder('  重型   钻机  ', 'M1'), '重型 钻机')
        self.assertEqual(fw_project.sanitize_asset_folder('钻机/原型:1', 'M1'), '钻机-原型-1')

    def test_empty_reserved_or_too_long_name_falls_back_to_id(self):
        for name in ('', '   ', 'CON', '..', '/', 'x' * 100):
            folder = fw_project.sanitize_asset_folder(name, 'M1')
            self.assertTrue(folder)
            self.assertLessEqual(len(folder), fw_project.MAX_FOLDER_LENGTH)
        self.assertEqual(fw_project.sanitize_asset_folder('', 'M1'), 'M1')
        self.assertEqual(fw_project.sanitize_asset_folder('CON', 'M1'), 'M1')

    def test_duplicate_names_append_id_and_stay_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(fw_project.create_project(directory, 'FW')['root'])
            manifest = _write_machine(root, 'M1')
            manifest = _write_machine(root, 'M2')
            self.assertEqual(manifest['assets']['M1']['sourceDir'], '_Source/机器/钻机')
            self.assertEqual(manifest['assets']['M2']['sourceDir'], '_Source/机器/钻机-M2')

            again = fw_project.asset_source_dir(root, 'machine', 'M2', manifest['assets']['M2']['meta'], manifest)
            self.assertEqual(again, '_Source/机器/钻机-M2')

    def test_renaming_moves_directory_with_pipeline_and_blend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(fw_project.create_project(directory, 'FW')['root'])
            manifest = _write_machine(root, 'M1')
            old_dir = root / manifest['assets']['M1']['sourceDir']
            (old_dir / 'M1.blend').write_bytes(b'blend')

            meta = dict(manifest['assets']['M1']['meta'], name='地质钻机')
            new_rel = fw_project.asset_source_dir(root, 'machine', 'M1', meta, manifest)

            self.assertEqual(new_rel, '_Source/机器/地质钻机')
            self.assertFalse(old_dir.exists())
            new_dir = root / new_rel
            self.assertTrue((new_dir / 'M1.glb').is_file())
            self.assertTrue((new_dir / 'M1.blend').is_file())
            self.assertTrue((new_dir / 'pipeline' / 'graph.json').is_file())

    def test_migrate_legacy_layout_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(fw_project.create_project(directory, 'FW')['root'])
            legacy_machine = root / '_Source' / 'Machines' / 'M1'
            legacy_item = root / '_Source' / 'Items' / 'Icons' / 'I1'
            legacy_machine.mkdir(parents=True)
            legacy_item.mkdir(parents=True)
            (legacy_machine / 'M1.glb').write_bytes(b'glTF')
            (legacy_machine / 'pipeline').mkdir()
            (legacy_machine / 'pipeline' / 'graph.json').write_text('{}', encoding='utf-8')
            (legacy_item / 'I1.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            manifest_file = root / '_Sync' / 'manifest.json'
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
            manifest.pop('layoutVersion', None)
            manifest['assets'] = {
                'M1': {'kind': 'machine', 'sourceDir': '_Source/Machines/M1',
                       'files': {'mesh': [{'path': 'M1.glb', 'sha1': 'x'}]}, 'meta': {'name': '地质钻机'}},
                'I1': {'kind': 'item', 'sourceDir': '_Source/Items/Icons/I1',
                       'files': {'icon': [{'path': 'I1.png', 'sha1': 'y'}]}, 'meta': {'name': '铁矿石'}},
            }
            manifest_file.write_text(json.dumps(manifest), encoding='utf-8')

            fw_project.migrate_layout(root)
            migrated = json.loads(manifest_file.read_text(encoding='utf-8'))
            self.assertEqual(migrated['layoutVersion'], 2)
            self.assertEqual(migrated['assets']['M1']['sourceDir'], '_Source/机器/地质钻机')
            self.assertEqual(migrated['assets']['I1']['sourceDir'], '_Source/物品/图标/铁矿石')
            self.assertTrue((root / '_Source' / '机器' / '地质钻机' / 'M1.glb').is_file())
            self.assertTrue((root / '_Source' / '机器' / '地质钻机' / 'pipeline' / 'graph.json').is_file())
            self.assertTrue((root / '_Source' / '物品' / '图标' / '铁矿石' / 'I1.png').is_file())
            self.assertFalse((root / '_Source' / 'Machines').exists())
            self.assertFalse((root / '_Source' / 'Items').exists())

            fw_project.migrate_layout(root)
            self.assertEqual(json.loads(manifest_file.read_text(encoding='utf-8')), migrated)

    def test_prune_ignores_ds_store_and_cleans_legacy_dirs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(fw_project.create_project(directory, 'FW')['root'])
            legacy = root / '_Source' / 'Machines'
            legacy.mkdir(parents=True, exist_ok=True)
            (legacy / '.DS_Store').write_bytes(b'\x00')

            fw_project.migrate_layout(root)
            self.assertFalse(legacy.exists())

    def test_migrate_ue_export_moves_old_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            manifest = _write_machine(fw)
            ue = workspace / 'UE'
            export = ue / 'Forgeworks'
            legacy = export / '_Source' / 'Machines' / 'M1'
            legacy.mkdir(parents=True)
            (legacy / 'M1.glb').write_bytes(b'glTF')
            (export / '_Source' / 'Machines' / '.DS_Store').write_bytes(b'\x00')
            (export / '_Source' / 'Items' / 'Icons').mkdir(parents=True)
            (export / '_Source' / 'Items' / 'Icons' / '.DS_Store').write_bytes(b'\x00')
            (export / '_Sync').mkdir()
            (export / '_Sync' / 'manifest.json').write_text(json.dumps({
                'assets': {'M1': dict(manifest['assets']['M1'], sourceDir='_Source/Machines/M1')},
            }), encoding='utf-8')

            fw_project.migrate_ue_export(fw, ue)
            self.assertTrue((export / '_Source' / '机器' / '钻机' / 'M1.glb').is_file())
            self.assertFalse((export / '_Source' / 'Machines').exists())
            self.assertFalse((export / '_Source' / 'Items').exists())
            exported_manifest = json.loads((export / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(exported_manifest['assets']['M1']['sourceDir'], '_Source/机器/钻机')

            fw_project.migrate_ue_export(fw, ue)
            self.assertTrue((export / '_Source' / '机器' / '钻机' / 'M1.glb').is_file())


class PublishToUETest(unittest.TestCase):
    def test_publish_copies_mesh_icon_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_machine(fw)
            ue = workspace / 'MyGame'
            ue.mkdir()
            (ue / 'MyGame.uproject').write_text('{}', encoding='utf-8')

            result = fw_project.publish_to_ue(fw, ue)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['published'], ['M1'])

            exported = ue / 'Forgeworks' / '_Source' / '机器' / '钻机'
            self.assertTrue((exported / 'M1.glb').is_file())
            self.assertTrue((exported / 'M1_icon.png').is_file())
            self.assertFalse((exported / 'M1_preview.svg').exists())
            self.assertFalse((exported / 'pipeline').exists())

            manifest = json.loads((ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['project']['root'], str(ue))
            self.assertEqual(manifest['project']['forgeworksRoot'], str(ue / 'Forgeworks'))
            record = manifest['assets']['M1']
            self.assertEqual(list(record['files']), ['mesh', 'icon'])
            self.assertEqual(record['meta']['sizeCm'], [100, 100, 200])

    def test_publish_element_icon_to_chinese_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_element(fw, 'Fe', '铁')
            ue = workspace / 'MyGame'
            ue.mkdir()
            (ue / 'MyGame.uproject').write_text('{}', encoding='utf-8')

            result = fw_project.publish_to_ue(fw, ue)
            self.assertTrue(result['ok'], result)
            self.assertIn('Fe', result['published'])

            exported = ue / 'Forgeworks' / '_Source' / '元素' / '铁'
            self.assertTrue((exported / 'Fe.png').is_file())
            self.assertFalse((exported / 'pipeline').exists())

            manifest = json.loads((ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            record = manifest['assets']['Fe']
            self.assertEqual(record['kind'], 'element')
            self.assertEqual(list(record['files']), ['icon'])

    def test_element_duplicate_names_fall_back_to_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(fw_project.create_project(directory, 'FW')['root'])
            manifest = _write_element(root, 'Fe', '铁')
            self.assertEqual(manifest['assets']['Fe']['sourceDir'], '_Source/元素/铁')
            manifest = _write_element(root, 'Cu', '铁')
            self.assertEqual(manifest['assets']['Cu']['sourceDir'], '_Source/元素/铁-Cu')

    def test_publish_machine_without_icon_keeps_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_machine(fw, icon=False)
            ue = workspace / 'MyGame'
            ue.mkdir()

            result = fw_project.publish_to_ue(fw, ue)
            self.assertTrue(result['ok'], result)
            exported = ue / 'Forgeworks' / '_Source' / '机器' / '钻机'
            self.assertTrue((exported / 'M1.glb').is_file())
            self.assertFalse((exported / 'M1_icon.png').exists())

            manifest = json.loads((ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(list(manifest['assets']['M1']['files']), ['mesh'])

    def test_publish_respects_selection_and_reports_missing_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_machine(fw, 'M1')
            _write_machine(fw, 'M2', mesh=False)
            ue = workspace / 'UE'
            ue.mkdir()

            result = fw_project.publish_to_ue(fw, ue, ['M1'])
            self.assertEqual(result['published'], ['M1'])
            self.assertEqual(result['skipped'], [])

            result = fw_project.publish_to_ue(fw, ue, ['M2'])
            self.assertFalse(result['ok'])
            self.assertEqual(result['errors'][0]['id'], 'M2')

    def test_publish_includes_item_icons_without_internal_files(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_machine(fw)
            _write_item(fw)
            ue = workspace / 'UE'
            ue.mkdir()

            result = fw_project.publish_to_ue(fw, ue)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['published'], ['M1', 'I1'])

            exported = ue / 'Forgeworks' / '_Source' / '物品' / '图标' / '铁矿石'
            self.assertTrue((exported / 'I1.png').is_file())
            self.assertFalse((exported / 'prompt.txt').exists())

            manifest = json.loads((ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            record = manifest['assets']['I1']
            self.assertEqual(record['kind'], 'item')
            self.assertEqual(list(record['files']), ['icon'])
            self.assertEqual(record['meta']['iconHash'], 'h1')

    def test_partial_publish_keeps_previous_manifest_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_machine(fw)
            _write_item(fw)
            ue = workspace / 'UE'
            ue.mkdir()

            self.assertTrue(fw_project.publish_to_ue(fw, ue, ['M1'])['ok'])
            self.assertTrue(fw_project.publish_to_ue(fw, ue, ['I1'])['ok'])

            manifest = json.loads((ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(manifest['assets']), ['I1', 'M1'])
            self.assertTrue((ue / 'Forgeworks' / '_Source' / '机器' / '钻机' / 'M1.glb').is_file())

    def test_publish_reports_item_without_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_item(fw, 'I2', icon=False)
            ue = workspace / 'UE'
            ue.mkdir()

            result = fw_project.publish_to_ue(fw, ue, ['I2'])
            self.assertFalse(result['ok'])
            self.assertEqual(result['errors'][0]['id'], 'I2')


if __name__ == '__main__':
    unittest.main()
