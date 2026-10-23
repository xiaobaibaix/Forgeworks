import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_pipeline


class PipelineGraphTest(unittest.TestCase):
    def test_starter_graph_includes_asset_stages_in_order(self):
        graph = fw_pipeline.starter_graph('M1')
        by_id, order = fw_pipeline.validate_graph(graph)
        types = {node['type'] for node in graph['nodes']}
        for stage in fw_pipeline.LOCAL_STAGE_TYPES:
            self.assertIn(stage, types)
        self.assertLess(order.index('metadata'), order.index('validate'))
        self.assertLess(order.index('uv'), order.index('lod'))

    def test_browser_derived_stage_survives_save_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = fw_pipeline.starter_graph('M1')
            for node in graph['nodes']:
                if node['type'] == 'lod':
                    node['result'] = {
                        'state': 'done',
                        'source': 'forgeworks-ui',
                        'output': {'levels': [{'level': 0, 'parts': 3}]},
                    }
            saved = fw_pipeline.save_graph(directory, 'M1', graph)
            lod = next(node for node in saved['nodes'] if node['type'] == 'lod')
            self.assertEqual(lod['result']['state'], 'done')

            result = fw_pipeline.execute_local(directory, 'M1')
            lod = next(node for node in result['graph']['nodes'] if node['type'] == 'lod')
            self.assertEqual(lod['result']['state'], 'done')
            self.assertEqual(lod['result']['output']['levels'][0]['parts'], 3)
            uv = next(node for node in result['graph']['nodes'] if node['type'] == 'uv')
            self.assertEqual(uv['result']['state'], 'blocked')

    def test_output_port_may_fan_out_but_input_port_cannot_merge(self):
        graph = fw_pipeline.starter_graph('M1')
        graph['edges'] = [edge for edge in graph['edges'] if edge['from'] != 'metadata']
        graph['edges'].append({'from': 'metadata', 'out': 'mesh', 'to': 'validate', 'in': 'mesh'})
        graph['edges'].append({'from': 'metadata', 'out': 'mesh', 'to': 'export', 'in': 'mesh'})
        fw_pipeline.validate_graph(graph)

        graph['edges'].append({'from': 'uv', 'out': 'mesh', 'to': 'export', 'in': 'mesh'})
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_unknown_node_type_rejected(self):
        graph = fw_pipeline.starter_graph('M1')
        graph['nodes'].append({'id': 'bogus', 'type': 'bogus', 'params': {}})
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_archive_lives_in_asset_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = fw_pipeline.starter_graph('M1')
            graph['nodes'][0]['params']['text'] = '重型钻机'
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            archive = Path(directory) / '_Source' / '机器' / 'M1' / 'pipeline'
            self.assertTrue((archive / 'graph.json').is_file())
            self.assertEqual((archive / 'prompt.txt').read_text(encoding='utf-8'), '重型钻机')
            info = fw_pipeline.archive_info(directory, 'M1', 'machine')
            self.assertTrue(info['exists'])
            self.assertEqual(info['path'], '_Source/机器/M1/pipeline')

    def test_item_archive_uses_items_icons_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            fw_pipeline.save_graph(directory, 'I1', fw_pipeline.starter_graph('I1'), kind='item')
            self.assertTrue((Path(directory) / '_Source' / '物品' / '图标' / 'I1' / 'pipeline' / 'graph.json').is_file())

    def test_element_archive_uses_elements_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(fw_pipeline.pipeline_root(directory, 'Fe', 'element'),
                             str(Path(directory) / '_Source' / '元素' / 'Fe' / 'pipeline'))
            fw_pipeline.save_graph(directory, 'Fe', fw_pipeline.starter_graph('Fe'), kind='element')
            self.assertTrue((Path(directory) / '_Source' / '元素' / 'Fe' / 'pipeline' / 'graph.json').is_file())

    def test_legacy_graph_is_still_read(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / '_Source' / 'pipeline' / 'M1'
            legacy.mkdir(parents=True)
            graph = fw_pipeline.starter_graph('M1')
            graph['revision'] = 7
            (legacy / 'graph.json').write_text(json.dumps(graph), encoding='utf-8')
            loaded = fw_pipeline.load_graph(directory, 'M1', kind='machine')
            self.assertEqual(loaded['revision'], 7)
            self.assertTrue(fw_pipeline.archive_info(directory, 'M1', 'machine')['legacy'])

    def test_output_resolves_from_asset_folder_then_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            name = 'model_task_1234.glb'
            legacy = Path(directory) / '_Source' / 'pipeline' / 'M1' / 'outputs'
            legacy.mkdir(parents=True)
            (legacy / name).write_bytes(b'legacy')
            self.assertEqual(fw_pipeline.resolve_output(directory, 'M1', 'machine', name), str(legacy / name))
            archive = Path(directory) / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs'
            archive.mkdir(parents=True)
            (archive / name).write_bytes(b'archive')
            self.assertEqual(fw_pipeline.resolve_output(directory, 'M1', 'machine', name), str(archive / name))

    def test_manifest_source_dir_wins_over_kind_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            asset_dir = Path(directory) / '_Source' / '机器' / '地质钻机'
            asset_dir.mkdir(parents=True)
            (Path(directory) / '_Sync').mkdir()
            (Path(directory) / '_Sync' / 'manifest.json').write_text(json.dumps({'assets': {
                'M1': {'kind': 'machine', 'sourceDir': '_Source/机器/地质钻机'},
            }}), encoding='utf-8')

            self.assertEqual(fw_pipeline.pipeline_root(directory, 'M1', 'machine'),
                             str(asset_dir / 'pipeline'))

    def test_kind_dirs_match_project_module(self):
        import fw_project
        self.assertEqual(fw_pipeline.ASSET_KIND_DIRS, fw_project.ASSET_KIND_DIRS)

    def test_invalid_kind_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                fw_pipeline.pipeline_root(directory, 'M1', 'bogus')


if __name__ == '__main__':
    unittest.main()
