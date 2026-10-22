import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_project


def _write_machine(root, asset_id='M1', mesh=True):
    manifest_file = root / '_Sync' / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.is_file() else {
        'schemaVersion': 1,
        'project': {'name': root.name, 'kind': 'forgeworks', 'root': str(root)},
        'assets': {},
    }
    manifest['assets'][asset_id] = {
        'kind': 'machine',
        'state': 'exported',
        'sourceDir': '_Source/Machines/%s' % asset_id,
        'files': {
            'mesh': [{'path': asset_id + '.glb', 'sha1': 'mesh-sha1', 'size': 4}],
            'preview': [{'path': asset_id + '_preview.svg', 'sha1': 'svg-sha1', 'size': 4}],
        },
        'meta': {'name': '钻机', 'sizeCm': [100, 100, 200], 'contentHash': 'abc'},
    }
    base = root / '_Source' / 'Machines' / asset_id
    base.mkdir(parents=True)
    if mesh:
        (base / (asset_id + '.glb')).write_bytes(b'glTF')
    (base / (asset_id + '_preview.svg')).write_text('<svg/>', encoding='utf-8')
    pipeline = base / 'pipeline'
    pipeline.mkdir()
    (pipeline / 'graph.json').write_text('{}', encoding='utf-8')
    (pipeline / 'prompt.txt').write_text('钻机描述词', encoding='utf-8')
    (root / '_Sync').mkdir(exist_ok=True)
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


class ProjectLifecycleTest(unittest.TestCase):
    def test_create_project_writes_marker_and_store(self):
        with tempfile.TemporaryDirectory() as directory:
            result = fw_project.create_project(directory, '重装工程')
            root = Path(result['root'])
            self.assertTrue((root / 'forgeworks.project.json').is_file())
            self.assertTrue((root / '_Source' / 'Machines').is_dir())
            self.assertTrue((root / '_Source' / 'Items' / 'Icons').is_dir())
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


class PublishToUETest(unittest.TestCase):
    def test_publish_copies_only_mesh_and_manifest(self):
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

            exported = ue / 'Forgeworks' / '_Source' / 'Machines' / 'M1'
            self.assertTrue((exported / 'M1.glb').is_file())
            self.assertFalse((exported / 'M1_preview.svg').exists())
            self.assertFalse((exported / 'pipeline').exists())

            manifest = json.loads((ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['project']['root'], str(ue))
            self.assertEqual(manifest['project']['forgeworksRoot'], str(ue / 'Forgeworks'))
            record = manifest['assets']['M1']
            self.assertEqual(list(record['files']), ['mesh'])
            self.assertEqual(record['meta']['sizeCm'], [100, 100, 200])

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


if __name__ == '__main__':
    unittest.main()
