import importlib.util
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fw_sync = load_module('fw_sync', 'ue/fw_sync.py')
fw_registry = load_module('fw_registry', 'ue/fw_registry.py')
bridge_args = sys.argv
sys.argv = [sys.argv[0]]
bridge = load_module('bridge', 'tools/bridge.py')
sys.argv = bridge_args


class UEPipelineTest(unittest.TestCase):
    def test_import_plan_uses_project_content_path_and_meter_scale(self):
        manifest = {'assets': {'MC_DRILL': {
            'kind': 'machine',
            'files': {'mesh': [{'path': 'MC_DRILL.glb', 'sha1': 'abc'}]},
            'meta': {'sizeM': [2.0, 2.0, 2.79]},
        }}}

        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            mesh = base / '_Source' / 'Machines' / 'MC_DRILL' / 'MC_DRILL.glb'
            mesh.parent.mkdir(parents=True)
            mesh.write_bytes(b'glb')
            plan = fw_sync.build_import_plan(manifest, base, ['MC_DRILL'])

        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]['contentPath'], '/Game/Forgeworks/Machines/MC_DRILL')
        self.assertTrue(plan[0]['sourcePath'].endswith('/_Source/Machines/MC_DRILL/MC_DRILL.glb'))
        self.assertEqual(plan[0]['importOptions']['uniformScale'], 100.0)

    def test_import_plan_rejects_traversal_mesh_path(self):
        manifest = {'assets': {'MC_DRILL': {
            'kind': 'machine',
            'files': {'mesh': [{'path': '../../outside.glb'}]},
        }}}

        with self.assertRaises(ValueError):
            fw_sync.build_import_plan(manifest, ROOT, ['MC_DRILL'])

    def test_import_plan_converts_expected_meter_dimensions_to_centimeters(self):
        self.assertEqual(fw_sync.build_import_plan.__name__, 'build_import_plan')
        fw_sync.validate_measured_size([200, 200, 279], {'x': 200, 'y': 195, 'z': 279})
        with self.assertRaises(RuntimeError):
            fw_sync.validate_measured_size([200, 200, 279], {'x': 2, 'y': 2, 'z': 2.79})

    def test_registry_snapshot_keeps_safe_static_mesh_rows(self):
        rows = fw_registry.normalize_assets([
            {'objectPath': '/Game/Forgeworks/Machines/MC_DRILL/SM_MC_DRILL.SM_MC_DRILL',
             'class': 'StaticMesh', 'bounds': {'x': 200, 'y': 195, 'z': 279},
             'triangles': 2580, 'materialSlots': ['M_body'], 'dependencies': []},
            {'objectPath': '/Game/Engine/Default.Default', 'class': 'StaticMesh'},
            {'objectPath': '/Game/Forgeworks/Machines/../Other/Bad.Bad', 'class': 'StaticMesh'},
        ])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['triangles'], 2580)
        self.assertEqual(rows[0]['bounds'], {'x': 200.0, 'y': 195.0, 'z': 279.0})

    def test_ue_report_requires_known_machine_and_matching_content_path(self):
        manifest = {'assets': {'MC_DRILL': {'kind': 'machine', 'files': {'mesh': [{'sha1': 'abc'}]}}}}
        report = {'contentPath': '/Game/Forgeworks/Machines/MC_DRILL',
                  'assets': {'mesh': '/Game/Forgeworks/Machines/MC_DRILL/SM_MC_DRILL.SM_MC_DRILL'},
                  'bounds': {'x': 200, 'y': 195, 'z': 279}, 'triangles': 2580,
                  'materialSlots': ['M_body'], 'sourceSha1': 'abc'}

        normalized = bridge.normalize_ue_report('MC_DRILL', report, manifest)
        self.assertEqual(normalized['bounds']['x'], 200.0)
        with self.assertRaises(ValueError):
            bridge.normalize_ue_report('UNKNOWN', report, manifest)
        with self.assertRaises(ValueError):
            bridge.normalize_ue_report('MC_DRILL', dict(report, contentPath='/Game/Other'), manifest)

    def test_ue_registry_snapshot_reader_handles_missing_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(bridge.normalize_ue_snapshot_path(directory), {'schemaVersion': 1, 'generatedAt': None, 'assets': []})
            sync = pathlib.Path(directory) / '_Sync'
            sync.mkdir()
            (sync / 'ue_assets.json').write_text('{bad', encoding='utf-8')
            self.assertEqual(bridge.normalize_ue_snapshot_path(directory), {'schemaVersion': 1, 'generatedAt': None, 'assets': []})

    def test_external_mesh_change_archives_both_versions_and_keep_tool_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / '_Source' / 'Machines' / 'MC_DRILL' / 'MC_DRILL.glb'
            baseline = root / '_Sync' / 'tool_versions' / 'MC_DRILL' / 'MC_DRILL.glb'
            source.parent.mkdir(parents=True)
            baseline.parent.mkdir(parents=True)
            baseline.write_bytes(b'tool-version')
            source.write_bytes(b'disk-version')
            manifest = {'assets': {'MC_DRILL': {'kind': 'machine', 'sourceDir': '_Source/Machines/MC_DRILL',
                'files': {'mesh': [{'path': 'MC_DRILL.glb', 'sha1': bridge.sha1_bytes(b'tool-version')}]}}}}
            old_save, old_events = bridge.save_manifest, bridge.push_event
            bridge.save_manifest = lambda _: None
            bridge.push_event = lambda *_: None
            try:
                changes = bridge.watch_source_once(str(root), manifest)
                conflict = manifest['assets']['MC_DRILL']['conflicts'][0]
                self.assertEqual(changes[0]['state'], 'conflict')
                self.assertEqual((root / '_Sync' / 'conflicts' / 'MC_DRILL' / conflict['conflictId'] / 'tool/MC_DRILL.glb').read_bytes(), b'tool-version')
                bridge._state['projectRoot'] = str(root.parent)
                old_fw, old_sync, old_load = bridge.fw_dir, bridge.sync_dir, bridge.load_manifest
                bridge.fw_dir = lambda: str(root)
                bridge.sync_dir = lambda: str(root / '_Sync')
                bridge.load_manifest = lambda: manifest
                try:
                    result = bridge.resolve_file_conflict('MC_DRILL', conflict['conflictId'], 'keep-tool')
                finally:
                    bridge.fw_dir, bridge.sync_dir, bridge.load_manifest = old_fw, old_sync, old_load
                self.assertTrue(result['ok'])
                self.assertEqual(source.read_bytes(), b'tool-version')
            finally:
                bridge.save_manifest, bridge.push_event = old_save, old_events


if __name__ == '__main__':
    unittest.main()
