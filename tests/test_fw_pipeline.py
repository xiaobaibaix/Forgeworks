import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_pipeline
import fw_spec


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


def _assembly_decimate_graph(asset_id='M1', with_mesh=False):
    nodes = [
        {'id': 'model', 'type': 'partModel', 'params': {},
         'result': {'state': 'done',
                    'providerTask': {'taskId': 'model_body', 'state': 'success',
                                     'output': {'modelPath': 'outputs/model_body.glb'}},
                    'output': {'assembly': {
             'schemaVersion': 1, 'assemblyId': 'asm_partModel_body', 'assetId': asset_id,
             'meshPath': 'outputs/model_body.glb',
             'parts': [{'id': 'partModel_body', 'role': 'body',
                        'meshPath': 'outputs/model_body.glb'}],
             'connectors': [{'id': 'body:boom_base', 'pos': [0, 0, 0],
                             'axis': [1, 0, 0]}],
             'mates': [], 'warnings': []}}}},
        {'id': 'dec', 'type': 'decimate', 'params': {'targetFaces': 900}},
    ]
    edges = [{'from': 'model', 'out': 'assembly', 'to': 'dec', 'in': 'assembly'}]
    if with_mesh:
        nodes.append({'id': 'mesh', 'type': 'imageTo3D', 'params': {},
                      'result': {'providerTask': {'state': 'success',
                                                  'output': {'modelPath': 'model_up.glb'}}}})
        edges.append({'from': 'mesh', 'out': 'mesh', 'to': 'dec', 'in': 'mesh'})
    return {'schemaVersion': 1, 'assetId': asset_id, 'revision': 0,
            'nodes': nodes, 'edges': edges}


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

    def test_decimate_rejects_mesh_and_assembly_inputs_together(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError) as ctx:
                fw_pipeline.save_graph(directory, 'M1', _assembly_decimate_graph(with_mesh=True),
                                       kind='machine')
        self.assertTrue(str(ctx.exception).startswith('DECIMATE_INPUT_CONFLICT'))

    def test_decimate_assembly_mode_preserves_connectors(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs'
            outputs.mkdir(parents=True)
            (outputs / 'model_body.glb').write_bytes(b'glb')
            _save_ready(directory, _assembly_decimate_graph())

            def fake_run(blender_path, source, output, target_faces):
                self.assertTrue(source.endswith('model_body.glb'))
                Path(output).write_bytes(b'decimated')
                return {'valid': True, 'trianglesBefore': 12000, 'trianglesAfter': 900,
                        'targetFaces': target_faces,
                        'boundsBefore': [4.0, 2.0, 1.0],
                        'boundsAfter': [4.0, 2.0, 1.0]}

            with mock.patch.object(fw_pipeline, '_decimate_with_blender', side_effect=fake_run), \
                    mock.patch.object(fw_pipeline, 'spec_for_node',
                                      return_value=fw_spec.template_spec('M1')), \
                    mock.patch.object(fw_pipeline, '_fit_is_current', return_value=True):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['id'] == 'dec')
            self.assertEqual(node['result']['state'], 'done')
            output = node['result']['output']
            decimated = 'outputs/model_decimate_dec_900.glb'
            self.assertEqual(output['assembly']['meshPath'], decimated)
            self.assertEqual([part['meshPath'] for part in output['assembly']['parts']],
                             [decimated])
            self.assertEqual(output['assembly']['connectors'][0]['id'], 'body:boom_base')
            self.assertEqual(output['bboxDrift'], 0.0)
            self.assertEqual(output['warnings'], [])

    def test_decimate_assembly_mode_warns_on_bbox_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs'
            outputs.mkdir(parents=True)
            (outputs / 'model_body.glb').write_bytes(b'glb')
            _save_ready(directory, _assembly_decimate_graph())

            def fake_run(blender_path, source, output, target_faces):
                Path(output).write_bytes(b'decimated')
                return {'valid': True, 'trianglesBefore': 12000, 'trianglesAfter': 900,
                        'targetFaces': target_faces,
                        'boundsBefore': [4.0, 2.0, 1.0],
                        'boundsAfter': [4.0, 2.04, 1.0]}

            with mock.patch.object(fw_pipeline, '_decimate_with_blender', side_effect=fake_run), \
                    mock.patch.object(fw_pipeline, 'spec_for_node',
                                      return_value=fw_spec.template_spec('M1')), \
                    mock.patch.object(fw_pipeline, '_fit_is_current', return_value=True):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['id'] == 'dec')
            output = node['result']['output']
            self.assertAlmostEqual(output['bboxDrift'], 0.02)
            self.assertTrue(any(warning.startswith('DECIMATE_BBOX_DRIFT')
                                for warning in output['warnings']))


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


def _decimated_assemble_graph(asset_id='M1'):
    nodes = [
        {'id': 'prompt_body', 'type': 'prompt', 'params': {'text': '红色车身'}},
        {'id': 'partImage_body', 'type': 'partImage', 'params': {},
         'result': {'output': {'partName': '车身'}}},
        _part_model_node('partModel_body'),
        {'id': 'decimate_body', 'type': 'decimate', 'params': {'targetFaces': 10000},
         'result': {'state': 'done', 'output': {'meshPath': 'model_decimate_body_10000.glb'}}},
        {'id': 'overall', 'type': 'textToImage', 'params': {'provider': 'ark'},
         'result': {'providerTask': {'state': 'success',
                                     'output': {'imagePath': 'outputs/image_overall.png'}}}},
        {'id': 'prompt_assemble', 'type': 'prompt', 'params': {'text': '车身居中'}},
        {'id': 'assemble', 'type': 'assemble', 'params': {'resetLayout': True}},
    ]
    edges = [
        {'from': 'prompt_body', 'out': 'text', 'to': 'partImage_body', 'in': 'text'},
        {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
        {'from': 'partModel_body', 'out': 'mesh', 'to': 'decimate_body', 'in': 'mesh'},
        {'from': 'decimate_body', 'out': 'part', 'to': 'assemble', 'in': 'part'},
        {'from': 'overall', 'out': 'image', 'to': 'assemble', 'in': 'image'},
        {'from': 'prompt_assemble', 'out': 'text', 'to': 'assemble', 'in': 'text'},
    ]
    return {'schemaVersion': 1, 'assetId': asset_id, 'revision': 0,
            'nodes': nodes, 'edges': edges}


class PipelinePartsTest(unittest.TestCase):
    def test_parts_template_builds_one_chain_per_part(self):
        graph = fw_pipeline.starter_graph('M1', 'parts')
        _, order = fw_pipeline.validate_graph(graph)
        parts = ('body', 'roof', 'wheel', 'door', 'side_window', 'rear_window')
        self.assertLess(order.index('prompt_body'), order.index('partImage_body'))
        self.assertLess(order.index('partImage_body'), order.index('partModel_body'))
        edges = {(edge['from'], edge['out'], edge['to'], edge['in']) for edge in graph['edges']}
        for part in parts:
            self.assertLess(order.index('partImage_' + part), order.index('partModel_' + part))
            self.assertLess(order.index('partModel_' + part), order.index('decimate_' + part))
            self.assertLess(order.index('decimate_' + part), order.index('assemble'))
            self.assertIn(('partModel_' + part, 'mesh', 'decimate_' + part, 'mesh'), edges)
        self.assertLess(order.index('prompt_assemble'), order.index('assemble'))
        self.assertLess(order.index('assemble'), order.index('style'))
        self.assertNotIn('partSpec', {node['type'] for node in graph['nodes']})
        sources = [edge['from'] for edge in graph['edges']
                   if edge['to'] == 'assemble' and edge['in'] == 'part']
        self.assertEqual(sorted(sources), sorted('decimate_' + part for part in parts))

    def test_parts_template_splits_parts_from_overall_image(self):
        graph = fw_pipeline.starter_graph('M1', 'parts')
        by_id = {node['id']: node for node in graph['nodes']}
        self.assertEqual(by_id['overall']['type'], 'textToImage')
        self.assertEqual(by_id['overall']['params']['provider'], 'ark')
        parts = ('body', 'roof', 'wheel', 'door', 'side_window', 'rear_window')
        for part in parts:
            self.assertEqual(by_id['partImage_' + part]['params']['provider'], 'ark')
            self.assertEqual(by_id['partModel_' + part]['params']['provider'], 'ark')
        edges = {(edge['from'], edge['out'], edge['to'], edge['in']) for edge in graph['edges']}
        self.assertIn(('prompt_overall', 'text', 'overall', 'text'), edges)
        for part in parts:
            self.assertIn(('overall', 'image', 'partImage_' + part, 'image'), edges)

    def test_parts_template_decimates_parts_before_assembly(self):
        graph = fw_pipeline.starter_graph('M1', 'parts')
        assemble = next(node for node in graph['nodes'] if node['id'] == 'assemble')
        # 减面由显式节点完成，组装内部不再重复减面。
        self.assertEqual(assemble['params']['decimateFaces'], 0)
        self.assertTrue(assemble['params']['visionAssist'])
        decimates = [node for node in graph['nodes'] if node['type'] == 'decimate']
        self.assertEqual(len(decimates), 6)
        self.assertTrue(all(node['params']['targetFaces'] == 10000 for node in decimates))
        self.assertIn(('overall', 'image', 'assemble', 'image'),
                      {(edge['from'], edge['out'], edge['to'], edge['in']) for edge in graph['edges']})

    def test_part_image_accepts_text_and_image_inputs(self):
        self.assertEqual(fw_pipeline.NODE_TYPES['partImage']['in'],
                         {'text': 'text', 'image': 'image', 'spec': 'spec'})

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
                              reset=False, blender_path=None, asset_id='', node_id='',
                              preserve_absent=False, decimate_faces=0, layout_mode='coherent',
                              layout_hints=None, reference_image=''):
                self.assertEqual([part['id'] for part in parts],
                                 ['partModel_body', 'partModel_roof'])
                self.assertFalse(preserve_absent)
                self.assertEqual([part['name'] for part in parts], ['车身', '车顶'])
                self.assertEqual([part['mesh'] for part in parts],
                                 ['outputs/model_partModel_body.glb', 'outputs/model_partModel_roof.glb'])
                self.assertEqual(assembly_prompt, '车身居中，车顶在上')
                self.assertTrue(reset)
                self.assertEqual(decimate_faces, 10000)
                self.assertEqual(layout_mode, 'coherent')
                self.assertEqual(layout_hints, {})
                self.assertEqual(reference_image, '')
                self.assertTrue(output_path.endswith('model_assembly_assemble.glb'))
                self.assertTrue(layout_path.replace('\\', '/').endswith('parts/layout_assemble.json'))
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

    def test_assemble_skips_parts_that_are_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _save_ready(directory, _assemble_graph())
            roof = next(node for node in graph['nodes'] if node['id'] == 'partModel_roof')
            roof['result']['providerTask'] = {'state': 'running'}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')

            def fake_assemble(parts, output_path, layout_path, root, assembly_prompt='',
                              reset=False, blender_path=None, asset_id='', node_id='',
                              preserve_absent=False, decimate_faces=0, layout_mode='coherent',
                              layout_hints=None, reference_image=''):
                self.assertEqual([part['id'] for part in parts], ['partModel_body'])
                self.assertTrue(preserve_absent)
                self.assertEqual(decimate_faces, 10000)
                self.assertEqual(layout_mode, 'coherent')
                return {'meshPath': os.path.basename(output_path), 'outputPath': output_path,
                        'layoutPath': layout_path,
                        'parts': [{'id': 'partModel_body', 'name': '车身', 'triangles': 10}],
                        'triangles': 10, 'warnings': [], 'engine': 'blender',
                        'updatedAt': '2026-10-26T00:00:00Z'}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts',
                                   side_effect=fake_assemble):
                result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertTrue(node['result']['output']['partial'])
            self.assertEqual(len(node['result']['output']['missingParts']), 1)
            self.assertIn('partModel_roof', node['result']['output']['missingParts'][0])
            self.assertIn('running', node['result']['output']['missingParts'][0])
            self.assertTrue(any('残缺' in warning
                                for warning in node['result']['output']['warnings']))

    def test_assemble_without_part_edges_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _assemble_graph()
            graph['edges'] = [edge for edge in graph['edges'] if edge['in'] != 'part']
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('没有接入', node['result']['error'])

    def test_assemble_skips_stale_part_model(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _save_ready(directory, _assemble_graph())
            roof = next(node for node in graph['nodes'] if node['id'] == 'partModel_roof')
            roof['result']['state'] = 'dirty'
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')

            def fake_assemble(parts, output_path, layout_path, root, **kwargs):
                self.assertEqual([part['id'] for part in parts], ['partModel_body'])
                return {'meshPath': os.path.basename(output_path), 'outputPath': output_path,
                        'layoutPath': layout_path,
                        'parts': [{'id': 'partModel_body', 'name': '车身', 'triangles': 10}],
                        'triangles': 10, 'warnings': [], 'engine': 'blender',
                        'updatedAt': '2026-10-26T00:00:00Z'}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts',
                                   side_effect=fake_assemble):
                result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertIn('上游已变更', node['result']['output']['missingParts'][0])

    def test_assemble_blocked_when_no_part_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = _save_ready(directory, _assemble_graph())
            for node in graph['nodes']:
                if node['type'] == 'partModel':
                    node['result']['providerTask'] = {'state': 'running'}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts') as assemble:
                result = self._execute(directory)
            assemble.assert_not_called()
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('没有可用的单件模型', node['result']['error'])
            self.assertIn('partModel_body', node['result']['error'])

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

    def _prepare_decimated(self, directory):
        saved = fw_pipeline.save_graph(directory, 'M1', _decimated_assemble_graph(), kind='machine')
        for node in saved['nodes']:
            if node['id'] == 'decimate_body':
                node['result']['state'] = 'done'
        fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')
        root = fw_pipeline.pipeline_root(directory, 'M1', 'machine')
        outputs = os.path.join(root, 'outputs')
        os.makedirs(outputs, exist_ok=True)
        Path(os.path.join(outputs, 'image_overall.png')).write_bytes(b'png')

    def test_assemble_uses_decimated_part_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            self._prepare_decimated(directory)

            def fake_assemble(parts, output_path, layout_path, root, **kwargs):
                self.assertEqual([part['id'] for part in parts], ['partModel_body'])
                self.assertEqual([part['name'] for part in parts], ['车身'])
                self.assertEqual([part['mesh'] for part in parts],
                                 ['outputs/model_decimate_body_10000.glb'])
                self.assertEqual(kwargs.get('layout_hints'), {'groundLengthRatio': 1.3})
                self.assertEqual(kwargs.get('reference_image'), 'outputs/image_overall.png')
                return {'meshPath': os.path.basename(output_path), 'outputPath': output_path,
                        'layoutPath': layout_path, 'layoutHints': kwargs.get('layout_hints'),
                        'parts': [{'id': 'partModel_body', 'name': '车身', 'triangles': 10}],
                        'triangles': 10, 'warnings': [], 'engine': 'blender',
                        'updatedAt': '2026-10-26T00:00:00Z'}

            def fake_vision(config, image_path, parts, prompt='', model=''):
                self.assertEqual(os.path.basename(image_path), 'image_overall.png')
                self.assertEqual([part['id'] for part in parts], ['partModel_body'])
                return {'groundLengthRatio': 1.3}, {'model': 'mock-vision', 'notes': '履带偏长'}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts', side_effect=fake_assemble), \
                    mock.patch.object(fw_pipeline.fw_providers, 'analyze_layout', side_effect=fake_vision):
                result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['id'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['layoutHints'], {'groundLengthRatio': 1.3})
            self.assertEqual(node['result']['output']['referenceImage'], 'outputs/image_overall.png')
            self.assertEqual(node['result']['output']['vision'],
                             {'enabled': True, 'state': 'done',
                              'referenceImage': 'outputs/image_overall.png',
                              'model': 'mock-vision', 'notes': '履带偏长'})

    def test_vision_failure_falls_back_to_default_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            self._prepare_decimated(directory)

            def fake_assemble(parts, output_path, layout_path, root, **kwargs):
                self.assertEqual(kwargs.get('layout_hints'), {})
                return {'meshPath': os.path.basename(output_path), 'outputPath': output_path,
                        'layoutPath': layout_path,
                        'parts': [{'id': 'partModel_body', 'name': '车身', 'triangles': 10}],
                        'triangles': 10, 'warnings': [], 'engine': 'blender',
                        'updatedAt': '2026-10-26T00:00:00Z'}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble_parts',
                                   side_effect=fake_assemble), \
                    mock.patch.object(fw_pipeline.fw_providers, 'analyze_layout',
                                      side_effect=RuntimeError('Ark API key 未配置')):
                result = self._execute(directory)
            node = next(item for item in result['graph']['nodes'] if item['id'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['vision']['state'], 'failed')
            self.assertTrue(any('视觉分析失败' in warning
                                for warning in node['result']['output']['warnings']))

    def test_decimate_part_input_requires_decimate_result(self):
        graph = _decimated_assemble_graph()
        by_id = {node['id']: node for node in graph['nodes']}
        by_id['decimate_body']['result'] = {'state': 'blocked'}
        with self.assertRaises(ValueError) as raised:
            fw_pipeline._assemble_part_inputs(graph, by_id, 'assemble')
        self.assertIn('decimate_body', str(raised.exception))


class PipelineConcurrencyTest(unittest.TestCase):
    def _provider_graph(self):
        return {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'img_a', 'type': 'textToImage', 'params': {'provider': 'ark'},
                 'result': {'providerTask': {'taskId': 'arkimg_aaaa', 'provider': 'ark', 'state': 'queued'}}},
                {'id': 'img_b', 'type': 'textToImage', 'params': {'provider': 'ark'},
                 'result': {'providerTask': {'taskId': 'arkimg_bbbb', 'provider': 'ark', 'state': 'running'}}},
            ],
            'edges': [],
        }

    def test_concurrent_client_saves_keep_both_provider_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            fw_pipeline.save_graph(directory, 'M1', self._provider_graph(), kind='machine')
            snapshots = [fw_pipeline.load_graph(directory, 'M1', kind='machine') for _ in range(2)]
            # 模拟两个都缺少远程任务结果的过期客户端快照
            for graph in snapshots:
                for node in graph['nodes']:
                    node['result'] = {}
            barrier = threading.Barrier(2)
            errors = []

            def worker(graph):
                try:
                    barrier.wait()
                    fw_pipeline.save_client_graph(directory, 'M1', graph, kind='machine')
                except Exception as error:  # pragma: no cover - 失败时给出线程内原因
                    errors.append(error)

            threads = [threading.Thread(target=worker, args=(graph,)) for graph in snapshots]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            final = fw_pipeline.load_graph(directory, 'M1', kind='machine')
            task_ids = {node['result']['providerTask']['taskId'] for node in final['nodes']}
            self.assertEqual(task_ids, {'arkimg_aaaa', 'arkimg_bbbb'})

    def test_concurrent_updates_do_not_lose_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = {
                'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                'nodes': [
                    {'id': 'a', 'type': 'prompt', 'params': {'text': 'a'}},
                    {'id': 'b', 'type': 'prompt', 'params': {'text': 'b'}},
                ],
                'edges': [],
            }
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            barrier = threading.Barrier(2)
            errors = []

            def worker(node_id):
                def apply(latest):
                    node = next(item for item in latest['nodes'] if item['id'] == node_id)
                    node.setdefault('result', {})['marker'] = node_id
                    return latest
                try:
                    barrier.wait()
                    fw_pipeline.update_graph(directory, 'M1', 'machine', apply)
                except Exception as error:  # pragma: no cover
                    errors.append(error)

            threads = [threading.Thread(target=worker, args=(node_id,)) for node_id in ('a', 'b')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            final = fw_pipeline.load_graph(directory, 'M1', kind='machine')
            markers = {node['id']: node['result'].get('marker') for node in final['nodes']}
            self.assertEqual(markers, {'a': 'a', 'b': 'b'})

    def test_revision_is_monotonic_for_stale_client_graphs(self):
        with tempfile.TemporaryDirectory() as directory:
            saved = fw_pipeline.save_graph(directory, 'M1', self._provider_graph(), kind='machine')
            first_revision = saved['revision']
            saved['revision'] = 0
            again = fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')
            self.assertGreater(again['revision'], first_revision)


class SpecPipelineTest(unittest.TestCase):
    def test_node_types_include_p1_ports(self):
        self.assertEqual(fw_pipeline.NODE_TYPES['blueprint']['out']['spec'], 'spec')
        self.assertEqual(fw_pipeline.NODE_TYPES['partImage']['in']['spec'], 'spec')
        self.assertEqual(fw_pipeline.NODE_TYPES['partImage']['out']['ports'], 'ports')
        self.assertEqual(fw_pipeline.NODE_TYPES['partModel']['in']['ports'], 'ports')
        self.assertEqual(fw_pipeline.NODE_TYPES['partModel']['out']['assembly'], 'assembly')
        self.assertIn('blueprint', fw_pipeline.PROVIDER_TYPES)

    def test_validate_graph_accepts_spec_and_ports_edges(self):
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'blueprint', 'type': 'blueprint', 'params': {}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {}},
                {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
            ],
            'edges': [
                {'from': 'blueprint', 'out': 'spec', 'to': 'partImage_body', 'in': 'spec'},
                {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
                {'from': 'partImage_body', 'out': 'ports', 'to': 'partModel_body', 'in': 'ports'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'partModel_body', 'in': 'spec'},
            ],
        }
        fw_pipeline.validate_graph(graph)
        graph['edges'].append({'from': 'blueprint', 'out': 'spec',
                               'to': 'partModel_body', 'in': 'mesh'})
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_spec_for_node_reads_upstream_output_and_spec_file(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = fw_spec.template_spec('M1')
            path = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'spec.json'
            fw_spec.write_spec(str(path), spec)
            graph = {
                'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                'nodes': [
                    {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                     'result': {'state': 'done', 'output': {'specPath': 'spec.json', 'spec': spec}}},
                    {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                ],
                'edges': [{'from': 'blueprint', 'out': 'spec',
                           'to': 'partModel_body', 'in': 'spec'}],
            }
            by_id, _ = fw_pipeline.validate_graph(graph)
            loaded = fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph, by_id,
                                               'partModel_body')
            self.assertEqual(loaded['parts']['body']['role'], 'body')
            self.assertEqual(fw_pipeline.part_role_for_node(graph, by_id, 'partModel_body'), 'body')

    def test_spec_for_node_falls_back_to_spec_file_when_upstream_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = fw_spec.template_spec('M1')
            path = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'spec.json'
            fw_spec.write_spec(str(path), spec)
            for result in (None, {'state': None}):
                blueprint = {'id': 'blueprint', 'type': 'blueprint', 'params': {}}
                if result is not None:
                    blueprint['result'] = result
                graph = {
                    'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                    'nodes': [
                        blueprint,
                        {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                    ],
                    'edges': [{'from': 'blueprint', 'out': 'spec',
                               'to': 'partModel_body', 'in': 'spec'}],
                }
                by_id, _ = fw_pipeline.validate_graph(graph)
                loaded = fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph,
                                                   by_id, 'partModel_body')
                self.assertEqual(loaded['assetId'], 'M1')

    def test_spec_for_node_rejects_spec_path_outside_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = fw_spec.template_spec('M1')
            path = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'spec.json'
            fw_spec.write_spec(str(path), spec)
            (Path(directory) / 'secret.json').write_text(json.dumps(spec), encoding='utf-8')
            for spec_path in ('../../../../secret.json', '../../etc/passwd'):
                graph = {
                    'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                    'nodes': [
                        {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                         'result': {'state': 'done', 'output': {'specPath': spec_path}}},
                        {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                    ],
                    'edges': [{'from': 'blueprint', 'out': 'spec',
                               'to': 'partModel_body', 'in': 'spec'}],
                }
                by_id, _ = fw_pipeline.validate_graph(graph)
                with self.assertRaisesRegex(ValueError, '^SPEC_(MISSING|INVALID)'):
                    fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph, by_id,
                                              'partModel_body')

    def test_spec_for_node_rejects_stale_spec_when_upstream_dirty(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = fw_spec.template_spec('M1')
            path = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'spec.json'
            fw_spec.write_spec(str(path), spec)
            for state in ('dirty', 'blocked', 'error'):
                graph = {
                    'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                    'nodes': [
                        {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                         'result': {'state': state, 'output': {'specPath': 'spec.json'}}},
                        {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                    ],
                    'edges': [{'from': 'blueprint', 'out': 'spec',
                               'to': 'partModel_body', 'in': 'spec'}],
                }
                by_id, _ = fw_pipeline.validate_graph(graph)
                with self.assertRaisesRegex(ValueError, '^SPEC_MISSING'):
                    fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph, by_id,
                                              'partModel_body')
                graph['nodes'][0]['result']['output']['spec'] = spec
                with self.assertRaisesRegex(ValueError, '^SPEC_MISSING'):
                    fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph, by_id,
                                              'partModel_body')
                graph['nodes'][0]['result']['state'] = 'done'
                self.assertEqual(fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph,
                                                           by_id, 'partModel_body')['assetId'], 'M1')

    def test_ports_for_node_prefers_ports_input(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = {
                'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                'nodes': [
                    {'id': 'partImage_body', 'type': 'partImage', 'params': {},
                     'result': {'state': 'done', 'output': {'ports': [{'id': 'p'}]}}},
                    {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                ],
                'edges': [{'from': 'partImage_body', 'out': 'ports',
                           'to': 'partModel_body', 'in': 'ports'}],
            }
            by_id, _ = fw_pipeline.validate_graph(graph)
            self.assertEqual(fw_pipeline.ports_for_node(directory, 'M1', 'machine', graph,
                                                        by_id, 'partModel_body'),
                             [{'id': 'p'}])


class ThreeViewExecutionTest(unittest.TestCase):
    def _write_sheet(self, path):
        image = Image.new('RGB', (900, 300), 'white')
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(('black', 'gray', 'red')):
            draw.rectangle([index * 300 + 10, 20, (index + 1) * 300 - 10, 280], fill=color)
        image.save(path)

    def test_successful_sheet_is_cropped_into_panels(self):
        spec = fw_spec.template_spec('M1')
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                 'result': {'state': 'done', 'output': {'spec': spec}}},
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'threeView_overall', 'type': 'threeView',
                 'params': {'annotate': True},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'tv_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/sheet.png'}}}},
            ],
            'edges': [
                {'from': 'overall', 'out': 'image', 'to': 'threeView_overall', 'in': 'image'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'threeView_overall', 'in': 'spec'},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            saved = fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            for node in saved['nodes']:
                node['result']['state'] = 'done'
            fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')
            outputs = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'outputs'
            outputs.mkdir(parents=True, exist_ok=True)
            self._write_sheet(outputs / 'sheet.png')
            result = fw_pipeline.execute_local(directory, 'M1', target_id='threeView_overall',
                                               kind='machine')
            node = next(item for item in result['graph']['nodes']
                        if item['id'] == 'threeView_overall')
            output = node['result']['output']
            self.assertEqual(output['sheetPath'], 'outputs/sheet.png')
            for key in ('frontPath', 'sidePath', 'topPath', 'annotatedPath'):
                self.assertTrue(output[key].startswith('outputs/'), key)
                self.assertTrue((Path(fw_pipeline.pipeline_root(directory, 'M1'))
                                 / output[key]).is_file(), key)
            self.assertEqual(output['warnings'], [])


class SpecExecutionTest(unittest.TestCase):
    def _graph(self, spec):
        return {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'blueprint', 'type': 'blueprint', 'params': {'overallLengthM': 7.2},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'spec_1', 'state': 'success',
                     'output': {'spec': spec, 'specPath': 'spec.json'}}}},
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_body', 'state': 'success',
                     'output': {'imagePath': 'outputs/body.png'}},
                     'output': {'partName': '车身'}}},
                {'id': 'partModel_body', 'type': 'partModel', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'model_body', 'state': 'success',
                     'output': {'modelPath': 'outputs/model_body.glb'}}}},
            ],
            'edges': [
                {'from': 'blueprint', 'out': 'spec', 'to': 'partImage_body', 'in': 'spec'},
                {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
                {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
                {'from': 'partImage_body', 'out': 'ports', 'to': 'partModel_body', 'in': 'ports'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'partModel_body', 'in': 'spec'},
            ],
        }

    def _fake_fit_report(self):
        return {
            'valid': True,
            'fit': {'mode': 'uniform', 'scale': 1.0, 'scalePerAxis': [1.0, 1.0, 1.0],
                    'aspectError': 0.02, 'rotationDeg': [0, 0, 0], 'grounded': False,
                    'ambiguous': False,
                    'measuredBbox': {'min': [-2.1, -0.8, -0.7], 'max': [2.1, 0.8, 0.7]}},
            'ports': [{'id': 'boom_base', 'type': 'pin', 'anchorNorm': [0.62, 0.5, 0.7],
                       'pos': [0.504, 0.0, 0.28], 'axis': [1, 0, 0],
                       'normal': [0, 0, 1], 'radiusM': 0.08}],
            'triangles': 1200,
        }

    def _measure_graph(self, spec, size):
        graph = self._graph(spec)
        graph['nodes'].append({
            'id': 'blueprint_body', 'type': 'blueprint',
            'params': {'scope': 'part', 'role': 'body'},
            'result': {'state': 'done', 'providerTask': {
                'taskId': 'measure_1', 'state': 'success',
                'output': {'role': 'body', 'measure': {
                    'schemaVersion': 1, 'scope': 'part', 'role': 'body',
                    'partId': 'blueprint_body', 'sizeM': list(size), 'forward': '+X',
                    'confidence': 0.7,
                    'anchor': {'overallLengthM': 7.2, 'template': 'excavator'},
                    'views': {}, 'notes': ''}}}},
        })
        graph['edges'].append({'from': 'blueprint_body', 'out': 'measure',
                               'to': 'partModel_body', 'in': 'measure'})
        return graph

    def _prepare(self, directory, spec, graph=None):
        saved = fw_pipeline.save_graph(directory, 'M1', graph or self._graph(spec),
                                       kind='machine')
        # 首次保存会把未签名结果打回 dirty；二次保存保留已执行状态，贴近真实运行后的图
        for node in saved['nodes']:
            node['result']['state'] = 'done'
        fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')
        outputs = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'outputs'
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / 'model_body.glb').write_bytes(b'glb')
        return outputs

    def test_blueprint_output_is_copied_to_node_result(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            blueprint = next(node for node in result['graph']['nodes']
                             if node['id'] == 'blueprint')
            self.assertEqual(blueprint['result']['output']['spec']['assetId'], 'M1')

    def test_blueprint_part_measure_is_attached_without_spec(self):
        spec = fw_spec.template_spec('M1', template='car')
        measure = {
            'schemaVersion': 1, 'scope': 'part', 'role': 'wheel',
            'partId': 'blueprint_wheel', 'sizeM': [4.0, 1.7, 0.7], 'forward': '+X',
            'confidence': 0.8, 'anchor': {'overallLengthM': 4.2, 'template': 'car'},
            'views': {}, 'notes': '',
        }
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'spec_1', 'state': 'success',
                     'output': {'spec': spec, 'specPath': 'spec.json'}}}},
                {'id': 'sheet', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/sheet.png'}}}},
                {'id': 'blueprint_wheel', 'type': 'blueprint',
                 'params': {'scope': 'part', 'role': 'wheel'},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'measure_1', 'state': 'success',
                     'output': {'measure': measure, 'role': 'wheel'}}}},
            ],
            'edges': [
                {'from': 'blueprint', 'out': 'spec', 'to': 'blueprint_wheel', 'in': 'spec'},
                {'from': 'sheet', 'out': 'image', 'to': 'blueprint_wheel', 'in': 'image'},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            saved = fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            for node in saved['nodes']:
                node['result']['state'] = 'done'
            fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(item for item in result['graph']['nodes']
                        if item['id'] == 'blueprint_wheel')
            output = node['result']['output']
            self.assertEqual(output['measure']['sizeM'], [4.0, 1.7, 0.7])
            self.assertEqual(output['role'], 'wheel')
            self.assertNotIn('spec', output)

    def test_part_image_gets_role_and_anchor_ports_from_spec(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            part_image = next(node for node in result['graph']['nodes']
                              if node['id'] == 'partImage_body')
            self.assertEqual(part_image['result']['output']['role'], 'body')
            self.assertEqual(part_image['result']['output']['ports'][0]['id'], 'boom_base')
            self.assertNotIn('pos', part_image['result']['output']['ports'][0])

    def test_part_model_fit_writes_ports_assembly_and_report(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='blender')
            node = next(node for node in result['graph']['nodes']
                        if node['id'] == 'partModel_body')
            output = node['result']['output']
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(output['role'], 'body')
            self.assertAlmostEqual(output['fit']['scale'], 1.0)
            self.assertEqual(output['assembly']['assemblyId'], 'asm_partModel_body')
            self.assertEqual(output['assembly']['connectors'][0]['id'], 'body:boom_base')
            self.assertEqual(output['assembly']['parts'][0]['role'], 'body')

    def test_part_model_fit_is_cached_by_task_and_spec_hash(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            outputs = self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()) as fit:
                first = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                  blender_path='blender')
                fw_pipeline.save_graph(directory, 'M1', first['graph'], kind='machine')
                (outputs / 'model_fit_partModel_body.glb').write_bytes(b'glb')
                fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                          blender_path='blender')
            self.assertEqual(fit.call_count, 1)

    def test_part_model_fit_failure_blocks_node_with_error_code(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            with mock.patch.object(
                    fw_pipeline, '_fit_with_blender',
                    return_value={'valid': False, 'errors': ['boom']}):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='blender')
            node = next(node for node in result['graph']['nodes']
                        if node['id'] == 'partModel_body')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertTrue(node['result']['error'].startswith('FIT_ASPECT_MISMATCH'))

    def test_part_model_malformed_report_blocks_instead_of_raising(self):
        spec = fw_spec.template_spec('M1')
        cases = [
            ('non-numeric aspect', {'valid': True, 'fit': {'aspectError': 'nope'},
                                    'ports': 'bad'}),
            ('scalar pos', {'valid': True, 'fit': {'aspectError': 0.02},
                            'ports': [{'pos': 5, 'axis': [1, 0, 0],
                                       'normal': [0, 0, 1]}]}),
            ('short axis', {'valid': True, 'fit': {'aspectError': 0.02},
                            'ports': [{'pos': [0, 0, 0], 'axis': [1, 0],
                                       'normal': [0, 0, 1]}]}),
            ('string radius', {'valid': True, 'fit': {'aspectError': 0.02},
                               'ports': [{'pos': [0, 0, 0], 'axis': [1, 0, 0],
                                          'normal': [0, 0, 1], 'radiusM': 'x'}]}),
            ('overflow pos', {'valid': True, 'fit': {'aspectError': 0.02},
                              'ports': [{'pos': [10 ** 400, 0, 0], 'axis': [1, 0, 0],
                                         'normal': [0, 0, 1]}]}),
            ('overflow aspect', {'valid': True, 'fit': {'aspectError': 10 ** 400},
                                 'ports': []}),
        ]
        for label, report in cases:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as directory:
                    self._prepare(directory, spec)
                    with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                           return_value=report):
                        result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                           blender_path='blender')
                    node = next(node for node in result['graph']['nodes']
                                if node['id'] == 'partModel_body')
                    self.assertEqual(node['result']['state'], 'blocked')
                    self.assertTrue(
                        node['result']['error'].startswith('FIT_ASPECT_MISMATCH'))

    def test_part_model_missing_port_vector_blocks_instead_of_raising(self):
        spec = fw_spec.template_spec('M1')
        cases = [
            ('missing pos', {'axis': [1, 0, 0], 'normal': [0, 0, 1]}),
            ('null normal', {'pos': [0, 0, 0], 'axis': [1, 0, 0], 'normal': None}),
        ]
        for label, port in cases:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as directory:
                    self._prepare(directory, spec)
                    report = {'valid': True, 'fit': {'aspectError': 0.02},
                              'ports': [port]}
                    with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                           return_value=report):
                        result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                           blender_path='blender')
                    node = next(node for node in result['graph']['nodes']
                                if node['id'] == 'partModel_body')
                    self.assertEqual(node['result']['state'], 'blocked')
                    self.assertTrue(
                        node['result']['error'].startswith('FIT_ASPECT_MISMATCH'))

    def test_part_model_passes_metric_ports_to_blender(self):
        spec = fw_spec.template_spec('M1')
        plans = []

        def capture(_blender_path, plan):
            plans.append(plan)
            return self._fake_fit_report()

        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender', side_effect=capture):
                fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                          blender_path='blender')
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]['targetSizeM'], spec['parts']['body']['sizeM'])
        self.assertTrue(plans[0]['ports'])
        for port in plans[0]['ports']:
            self.assertEqual(port['anchor'], port['anchorNorm'])

    def test_part_model_refits_when_fit_mode_changes(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            outputs = self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()) as fit:
                first = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                  blender_path='blender')
                (outputs / 'model_fit_partModel_body.glb').write_bytes(b'glb')
                node = next(node for node in first['graph']['nodes']
                            if node['id'] == 'partModel_body')
                node['params']['fitMode'] = 'perAxis'
                fw_pipeline.save_graph(directory, 'M1', first['graph'], kind='machine')
                fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                          blender_path='blender')
            self.assertEqual(fit.call_count, 2)

    def test_part_model_refits_when_ground_changes(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            outputs = self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()) as fit:
                first = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                  blender_path='blender')
                (outputs / 'model_fit_partModel_body.glb').write_bytes(b'glb')
                node = next(node for node in first['graph']['nodes']
                            if node['id'] == 'partModel_body')
                node['params']['ground'] = True
                fw_pipeline.save_graph(directory, 'M1', first['graph'], kind='machine')
                fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                          blender_path='blender')
            self.assertEqual(fit.call_count, 2)

    def test_part_model_measure_size_overrides_spec(self):
        spec = fw_spec.template_spec('M1')
        target = [value * 0.5 for value in spec['parts']['body']['sizeM']]
        plans = []

        def capture(_blender_path, plan):
            plans.append(plan)
            return self._fake_fit_report()

        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec, self._measure_graph(spec, target))
            with mock.patch.object(fw_pipeline, '_fit_with_blender', side_effect=capture):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='blender')
        node = next(item for item in result['graph']['nodes']
                    if item['id'] == 'partModel_body')
        self.assertEqual(node['result']['state'], 'done')
        self.assertEqual(plans[0]['targetSizeM'], target)
        self.assertEqual(node['result']['output']['fit']['targetSource'], 'measure')
        self.assertTrue(node['result']['output']['fitMeasureHash'])

    def test_part_model_refits_when_measure_changes(self):
        spec = fw_spec.template_spec('M1')
        first_size = [value * 0.5 for value in spec['parts']['body']['sizeM']]
        second_size = [value * 0.6 for value in spec['parts']['body']['sizeM']]
        with tempfile.TemporaryDirectory() as directory:
            outputs = self._prepare(directory, spec, self._measure_graph(spec, first_size))
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()) as fit:
                first = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                  blender_path='blender')
                (outputs / 'model_fit_partModel_body.glb').write_bytes(b'glb')
                node = next(item for item in first['graph']['nodes']
                            if item['id'] == 'blueprint_body')
                node['result']['providerTask']['output']['measure']['sizeM'] = second_size
                fw_pipeline.save_graph(directory, 'M1', first['graph'], kind='machine')
                fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                          blender_path='blender')
            self.assertEqual(fit.call_count, 2)

    def test_part_model_rejects_measure_with_other_role(self):
        spec = fw_spec.template_spec('M1')
        target = [value * 0.5 for value in spec['parts']['body']['sizeM']]
        with tempfile.TemporaryDirectory() as directory:
            graph = self._measure_graph(spec, target)
            measure_node = next(item for item in graph['nodes']
                                if item['id'] == 'blueprint_body')
            measure_node['result']['providerTask']['output']['measure']['role'] = 'boom'
            self._prepare(directory, spec, graph)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='blender')
            node = next(item for item in result['graph']['nodes']
                        if item['id'] == 'partModel_body')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertTrue(node['result']['error'].startswith('SPEC_INVALID'))


class FrontendMirrorTest(unittest.TestCase):
    def test_frontend_mirrors_p1_nodes_and_ports(self):
        source = (ROOT / 'js' / 'pipeline.js').read_text(encoding='utf-8')
        compact = ''.join(source.split())
        for expected in (
            "blueprint:{in:['image','spec','text'],out:['spec','measure']}",
            "threeView:{in:['image','spec','text'],out:['sheet','front','side','top']}",
            "partImage:{in:['text','image','spec'],out:['image','ports']}",
            "partModel:{in:['image','spec','ports','measure'],out:['part','mesh','assembly']}",
            "decimate:{in:['mesh','assembly'],out:['mesh','part','assembly']}",
            "blueprint:'尺寸规格'",
            "threeView:'三视图'",
            "pipelineSpecPanel(node,taskOutput)",
            "'scope','分析范围'",
            "output.measure",
            "fit.targetSource==='measure'",
            "output.assembly.parts.length",
            "['textToImage','imageTo3D','partImage','partModel','blueprint','threeView']",
            "visionNode?'DoubaoVision'",
            "visionNode?'ark'",
        ):
            self.assertIn(expected, compact)
        # compact 会删掉字符串内的空格，含空格的模型名字面量改查原始源码
        self.assertIn("visionNode?'Doubao Vision'", source)


if __name__ == '__main__':
    unittest.main()
