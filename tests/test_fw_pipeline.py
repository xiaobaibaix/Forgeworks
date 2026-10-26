import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def _write_manifest(root, assets):
    sync = Path(root) / '_Sync'
    sync.mkdir(parents=True, exist_ok=True)
    (sync / 'manifest.json').write_text(
        json.dumps({'schemaVersion': 1, 'assets': assets}, ensure_ascii=False),
        encoding='utf-8')


def _export_graph(asset_id):
    return {
        'schemaVersion': 1,
        'assetId': asset_id,
        'revision': 0,
        'nodes': [{'id': 'export', 'type': 'export', 'x': 0, 'y': 0, 'params': {}}],
        'edges': [],
    }


class PipelineExportNodeTest(unittest.TestCase):
    def test_machine_export_done_when_mesh_and_icon_present(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'M1': {
                'kind': 'machine', 'sourceDir': '_Source/机器/钻机',
                'files': {
                    'mesh': [{'path': 'M1.glb'}],
                    'icon': [{'path': 'M1_icon.png'}],
                },
                'exportedAt': '2026-10-24T00:00:00Z',
            }})
            fw_pipeline.save_graph(directory, 'M1', _export_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['sourceDir'], '_Source/机器/钻机')
            self.assertEqual(node['result']['output']['files']['mesh'], ['M1.glb'])
            self.assertEqual(node['result']['output']['exportedAt'], '2026-10-24T00:00:00Z')

    def test_machine_export_blocked_without_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'M1': {
                'kind': 'machine',
                'files': {'mesh': [{'path': 'M1.glb'}]},
            }})
            fw_pipeline.save_graph(directory, 'M1', _export_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('尚未导出到项目', node['result']['error'])

    def test_item_export_done_with_icon_only(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'I1': {
                'kind': 'item',
                'files': {'icon': [{'path': 'I1.png'}]},
                'exportedAt': '2026-10-24T00:00:00Z',
            }})
            fw_pipeline.save_graph(directory, 'I1', _export_graph('I1'), kind='item')
            result = fw_pipeline.execute_local(directory, 'I1', kind='item')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'done')

    def test_element_export_done_with_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'Fe': {
                'kind': 'element',
                'files': {'icon': [{'path': 'Fe.png'}]},
                'exportedAt': '2026-10-24T00:00:00Z',
            }})
            fw_pipeline.save_graph(directory, 'Fe', _export_graph('Fe'), kind='element')
            result = fw_pipeline.execute_local(directory, 'Fe', kind='element')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'done')

    def test_export_blocked_without_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            fw_pipeline.save_graph(directory, 'M1', _export_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'blocked')


def _decimate_graph(asset_id, with_upstream=True):
    nodes = [{'id': 'dec', 'type': 'decimate', 'x': 0, 'y': 0, 'params': {'targetFaces': 900}}]
    edges = []
    if with_upstream:
        nodes.insert(0, {
            'id': 'model', 'type': 'imageTo3D', 'x': 0, 'y': 0, 'params': {},
            'result': {'providerTask': {'state': 'success', 'output': {'modelPath': 'model_up.glb'}}},
        })
        edges.append({'from': 'model', 'out': 'mesh', 'to': 'dec', 'in': 'mesh'})
    return {'schemaVersion': 1, 'assetId': asset_id, 'revision': 0, 'nodes': nodes, 'edges': edges}


class PipelineDecimateTest(unittest.TestCase):
    def test_target_faces_falls_back_and_clamps(self):
        self.assertEqual(fw_pipeline._decimate_target(None), 900)
        self.assertEqual(fw_pipeline._decimate_target('abc'), 900)
        self.assertEqual(fw_pipeline._decimate_target(1), 50)
        self.assertEqual(fw_pipeline._decimate_target(99999999), 2000000)

    def test_decimate_writes_output_and_records_triangles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs' / 'model_up.glb'
            upstream.parent.mkdir(parents=True)
            upstream.write_bytes(b'glb')
            fw_pipeline.save_graph(directory, 'M1', _decimate_graph('M1'), kind='machine')

            def fake_run(blender_path, source, output, target_faces):
                Path(output).write_bytes(b'decimated')
                return {'valid': True, 'trianglesBefore': 12000, 'trianglesAfter': 900,
                        'targetFaces': target_faces, 'ratio': 0.075}

            with mock.patch.object(fw_pipeline, '_decimate_with_blender', side_effect=fake_run):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine', blender_path='/fake/blender')

            node = next(item for item in result['graph']['nodes'] if item['type'] == 'decimate')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['meshPath'], 'model_decimate_dec_900.glb')
            self.assertEqual(node['result']['output']['trianglesBefore'], 12000)
            self.assertEqual(node['result']['output']['trianglesAfter'], 900)
            self.assertTrue((upstream.parent / 'model_decimate_dec_900.glb').is_file())

    def test_decimate_uses_manifest_mesh_when_no_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset_dir = root / '_Source' / '机器' / '钻机'
            asset_dir.mkdir(parents=True)
            (asset_dir / 'M1.glb').write_bytes(b'glb')
            _write_manifest(directory, {'M1': {
                'kind': 'machine', 'sourceDir': '_Source/机器/钻机',
                'files': {'mesh': [{'path': 'M1.glb'}]},
            }})
            fw_pipeline.save_graph(directory, 'M1', _decimate_graph('M1', with_upstream=False), kind='machine')

            def fake_run(blender_path, source, output, target_faces):
                self.assertTrue(source.endswith('M1.glb'))
                Path(output).write_bytes(b'decimated')
                return {'valid': True, 'trianglesBefore': 5000, 'trianglesAfter': 900, 'targetFaces': 900}

            with mock.patch.object(fw_pipeline, '_decimate_with_blender', side_effect=fake_run):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine', blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'decimate')
            self.assertEqual(node['result']['state'], 'done')

    def test_decimate_blocked_without_blender(self):
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory) / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs' / 'model_up.glb'
            upstream.parent.mkdir(parents=True)
            upstream.write_bytes(b'glb')
            fw_pipeline.save_graph(directory, 'M1', _decimate_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'decimate')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('Blender', node['result']['error'])

    def test_decimate_blocked_without_input_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            fw_pipeline.save_graph(directory, 'M1', _decimate_graph('M1', with_upstream=False), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine', blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'decimate')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('上游 GLB', node['result']['error'])


def _part_model_node(node_id, model_path='outputs/model_%s.glb'):
    return {
        'id': node_id, 'type': 'partModel', 'params': {},
        'result': {'providerTask': {'state': 'success',
                                    'output': {'modelPath': model_path % node_id}}},
    }


def _save_ready(directory, graph):
    saved = fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
    for node in saved['nodes']:
        if node['type'] in ('partImage', 'partModel'):
            node['result']['state'] = 'done'
    return fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')


def _assemble_graph(asset_id='M1'):
    nodes = [
        {'id': 'prompt_body', 'type': 'prompt', 'params': {'text': '红色车身'}},
        {'id': 'partImage_body', 'type': 'partImage', 'params': {},
         'result': {'output': {'partName': '车身'}}},
        _part_model_node('partModel_body'),
        {'id': 'prompt_roof', 'type': 'prompt', 'params': {'text': '灰色车顶'}},
        {'id': 'partImage_roof', 'type': 'partImage', 'params': {},
         'result': {'output': {'partName': '车顶'}}},
        _part_model_node('partModel_roof'),
        {'id': 'prompt_assemble', 'type': 'prompt', 'params': {'text': '车身居中，车顶在上'}},
        {'id': 'assemble', 'type': 'assemble', 'params': {'resetLayout': True}},
    ]
    edges = [
        {'from': 'prompt_body', 'out': 'text', 'to': 'partImage_body', 'in': 'text'},
        {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
        {'from': 'partModel_body', 'out': 'part', 'to': 'assemble', 'in': 'part'},
        {'from': 'prompt_roof', 'out': 'text', 'to': 'partImage_roof', 'in': 'text'},
        {'from': 'partImage_roof', 'out': 'image', 'to': 'partModel_roof', 'in': 'image'},
        {'from': 'partModel_roof', 'out': 'part', 'to': 'assemble', 'in': 'part'},
        {'from': 'prompt_assemble', 'out': 'text', 'to': 'assemble', 'in': 'text'},
    ]
    return {'schemaVersion': 1, 'assetId': asset_id, 'revision': 0,
            'nodes': nodes, 'edges': edges}


class PipelinePartsTest(unittest.TestCase):
    def test_parts_template_builds_one_chain_per_part(self):
        graph = fw_pipeline.starter_graph('M1', 'parts')
        _, order = fw_pipeline.validate_graph(graph)
        self.assertLess(order.index('prompt_body'), order.index('partImage_body'))
        self.assertLess(order.index('partImage_body'), order.index('partModel_body'))
        self.assertLess(order.index('partModel_body'), order.index('assemble'))
        self.assertLess(order.index('partModel_roof'), order.index('assemble'))
        self.assertLess(order.index('prompt_assemble'), order.index('assemble'))
        self.assertLess(order.index('assemble'), order.index('style'))
        self.assertNotIn('partSpec', {node['type'] for node in graph['nodes']})
        assemble_inputs = [edge['in'] for edge in graph['edges'] if edge['to'] == 'assemble']
        self.assertEqual(sorted(assemble_inputs), ['part', 'part', 'text'])

    def test_parts_template_splits_parts_from_overall_image(self):
        graph = fw_pipeline.starter_graph('M1', 'parts')
        by_id = {node['id']: node for node in graph['nodes']}
        self.assertEqual(by_id['overall']['type'], 'textToImage')
        self.assertEqual(by_id['overall']['params']['provider'], 'ark')
        for part in ('body', 'roof'):
            self.assertEqual(by_id['partImage_' + part]['params']['provider'], 'ark')
            self.assertEqual(by_id['partModel_' + part]['params']['provider'], 'ark')
        edges = {(edge['from'], edge['out'], edge['to'], edge['in']) for edge in graph['edges']}
        self.assertIn(('prompt_overall', 'text', 'overall', 'text'), edges)
        for part in ('body', 'roof'):
            self.assertIn(('overall', 'image', 'partImage_' + part, 'image'), edges)

    def test_part_image_accepts_text_and_image_inputs(self):
        self.assertEqual(fw_pipeline.NODE_TYPES['partImage']['in'],
                         {'text': 'text', 'image': 'image'})

    def test_multi_input_port_accepts_several_sources(self):
        fw_pipeline.validate_graph(_assemble_graph())

    def test_duplicate_edge_rejected(self):
        graph = _assemble_graph()
        graph['edges'].append(dict(graph['edges'][2]))
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_single_input_port_still_rejects_second_source(self):
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [{'id': 'p1', 'type': 'prompt', 'params': {}},
                      {'id': 'p2', 'type': 'prompt', 'params': {}},
                      {'id': 'image', 'type': 'textToImage', 'params': {}}],
            'edges': [{'from': 'p1', 'out': 'text', 'to': 'image', 'in': 'text'},
                      {'from': 'p2', 'out': 'text', 'to': 'image', 'in': 'text'}],
        }
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_part_model_without_provider_task_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _assemble_graph()
            body = next(item for item in graph['nodes'] if item['id'] == 'partModel_body')
            body['result'] = {}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', target_id='partModel_body', kind='machine')
            node = next(item for item in result['graph']['nodes'] if item['id'] == 'partModel_body')
            self.assertEqual(node['result']['state'], 'blocked')

    def test_provider_state_survives_save_without_part_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = fw_pipeline.save_graph(directory, 'M1', _assemble_graph(), kind='machine')
            node = next(item for item in graph['nodes'] if item['id'] == 'partModel_body')
            node['result']['state'] = 'running'
            saved = fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            node = next(item for item in saved['nodes'] if item['id'] == 'partModel_body')
            self.assertEqual(node['result']['state'], 'running')

    def _execute(self, directory, blender_path='/fake/blender', target='assemble'):
        return fw_pipeline.execute_local(directory, 'M1', target_id=target, kind='machine',
                                         blender_path=blender_path)

    def test_assemble_feeds_part_models_and_prompt_into_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            _save_ready(directory, _assemble_graph())

            def fake_assemble(parts, output_path, layout_path, root, assembly_prompt='',
                              reset=False, blender_path=None, asset_id='', node_id=''):
                self.assertEqual([part['id'] for part in parts],
                                 ['partModel_body', 'partModel_roof'])
                self.assertEqual([part['name'] for part in parts], ['车身', '车顶'])
                self.assertEqual([part['mesh'] for part in parts],
                                 ['outputs/model_partModel_body.glb', 'outputs/model_partModel_roof.glb'])
                self.assertEqual(assembly_prompt, '车身居中，车顶在上')
                self.assertTrue(reset)
                self.assertTrue(output_path.endswith('model_assembly_assemble.glb'))
                self.assertTrue(layout_path.endswith('parts/layout_assemble.json'))
                return {'meshPath': os.path.basename(output_path), 'outputPath': output_path,
                        'layoutPath': layout_path,
                        'parts': [{'id': 'partModel_body', 'name': '车身', 'triangles': 10},
                                  {'id': 'partModel_roof', 'name': '车顶', 'triangles': 20}],
                        'triangles': 30, 'warnings': [], 'engine': 'blender',
                        'updatedAt': '2026-10-26T00:00:00Z'}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts', side_effect=fake_assemble):
                result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['meshPath'], 'model_assembly_assemble.glb')
            self.assertEqual(node['result']['output']['triangles'], 30)
            self.assertEqual(node['result']['output']['layoutPath'], 'parts/layout_assemble.json')
            self.assertEqual(node['result']['output']['updatedAt'], '2026-10-26T00:00:00Z')

    def test_assemble_blocked_when_a_part_model_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _assemble_graph()
            roof = next(node for node in graph['nodes'] if node['id'] == 'partModel_roof')
            roof['result'] = {'providerTask': {'state': 'running'}}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts') as assemble:
                result = self._execute(directory)
            assemble.assert_not_called()
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('partModel_roof', node['result']['error'])
            self.assertIn('running', node['result']['error'])

    def test_assemble_without_part_edges_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _assemble_graph()
            graph['edges'] = [edge for edge in graph['edges'] if edge['in'] != 'part']
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('没有接入', node['result']['error'])

    def test_assemble_blocked_when_part_model_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _assemble_graph()
            roof = next(node for node in graph['nodes'] if node['id'] == 'partModel_roof')
            roof['result']['state'] = 'dirty'
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts') as assemble:
                result = self._execute(directory)
            assemble.assert_not_called()
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('上游已变更', node['result']['error'])

    def test_run_all_keeps_dirty_provider_result_dirty(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _assemble_graph()
            body = next(node for node in graph['nodes'] if node['id'] == 'partModel_body')
            body['result']['state'] = 'dirty'
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                               blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['id'] == 'partModel_body')
            self.assertEqual(node['result']['state'], 'dirty')

    def test_assemble_blocked_without_blender(self):
        with tempfile.TemporaryDirectory() as directory:
            _save_ready(directory, _assemble_graph())
            result = self._execute(directory, blender_path=None)
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('Blender', node['result']['error'])


if __name__ == '__main__':
    unittest.main()
