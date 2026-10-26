import json
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


def _contract_json(parts):
    view = {'width': 1000, 'height': 1000, 'ground': 900, 'pxPerMeter': 100}
    return {
        'schemaVersion': 1, 'assetId': 'M1',
        'views': {'front': dict(view), 'side': dict(view)},
        'parts': parts,
    }


def _part_payload(index):
    return {'id': 'part_%d' % index, 'name': '切片 %d' % index,
            'mesh': 'part_%d.glb' % index,
            'front': [100, 100, 100 + index * 10, 100],
            'side': [100, 100, 100 + index * 10, 100]}


class PipelinePartsTest(unittest.TestCase):
    def test_parts_template_orders_split_chain(self):
        graph = fw_pipeline.starter_graph('M1', 'parts')
        _, order = fw_pipeline.validate_graph(graph)
        self.assertLess(order.index('model'), order.index('partSpec'))
        self.assertLess(order.index('partSpec'), order.index('partImage'))
        self.assertLess(order.index('partImage'), order.index('partModel'))
        self.assertLess(order.index('partModel'), order.index('assemble'))
        self.assertLess(order.index('assemble'), order.index('style'))

    def test_part_spec_bootstraps_and_renames_from_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs' / 'model_up.glb'
            upstream.parent.mkdir(parents=True)
            upstream.write_bytes(b'glb')
            graph = fw_pipeline.starter_graph('M1', 'parts')
            prompt = next(node for node in graph['nodes'] if node['type'] == 'prompt')
            prompt['params']['text'] = '整机\n【必须包含的部件】\n· 车身 — 外壳\n· 车顶\n· 车轮'
            model = next(node for node in graph['nodes'] if node['id'] == 'model')
            model['result'] = {'providerTask': {'state': 'success', 'output': {'modelPath': 'model_up.glb'}}}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')

            def fake_bootstrap(source, out_dir, parts=3, axis='z', blender_path=None, asset_id=None):
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                path = Path(out_dir) / 'partspec.json'
                path.write_text(json.dumps(_contract_json([_part_payload(i) for i in range(parts)]),
                                           ensure_ascii=False), encoding='utf-8')
                return {'contract': str(path), 'parts': parts}

            with mock.patch.object(fw_pipeline.fw_parts, 'bootstrap', side_effect=fake_bootstrap):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine', blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'partSpec')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['contractPath'], 'parts/partspec.json')
            self.assertEqual([part['name'] for part in node['result']['output']['parts']],
                             ['车身', '车顶', '车轮'])
            self.assertIn('part_0', node['result']['parts'])
            self.assertEqual(node['result']['parts']['part_0']['state'], 'pending')

    def test_part_spec_blocked_without_blender(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / '_Source' / '机器' / 'M1' / 'pipeline' / 'outputs' / 'model_up.glb'
            upstream.parent.mkdir(parents=True)
            upstream.write_bytes(b'glb')
            graph = fw_pipeline.starter_graph('M1', 'parts')
            model = next(node for node in graph['nodes'] if node['id'] == 'model')
            model['result'] = {'providerTask': {'state': 'success', 'output': {'modelPath': 'model_up.glb'}}}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'partSpec')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('Blender', node['result']['error'])

    def test_part_image_aggregates_states_and_keeps_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = fw_pipeline.starter_graph('M1', 'parts')
            spec = next(node for node in graph['nodes'] if node['type'] == 'partSpec')
            spec['result'] = {'state': 'done', 'output': {
                'contractPath': 'parts/partspec.json',
                'parts': [{'id': 'part_0', 'name': '车身'}, {'id': 'part_1', 'name': '车顶'}]}}
            image = next(node for node in graph['nodes'] if node['type'] == 'partImage')
            image['result'] = {'parts': {
                'part_0': {'state': 'success', 'output': {'imagePath': 'outputs/image_a.png'}},
                'part_1': {'state': 'running'},
            }}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', target_id='partImage', kind='machine')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'partImage')
            self.assertEqual(node['result']['state'], 'running')
            self.assertEqual(node['result']['output']['done'], 1)
            self.assertEqual(node['result']['parts']['part_0']['output']['imagePath'],
                             'outputs/image_a.png')
            self.assertEqual(node['result']['parts']['part_1']['name'], '车顶')

            graph = result['graph']
            image = next(node for node in graph['nodes'] if node['type'] == 'partImage')
            image['result']['parts']['part_1']['state'] = 'success'
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', target_id='partImage', kind='machine')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'partImage')
            self.assertEqual(node['result']['state'], 'done')

    def test_queued_part_state_survives_save(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = fw_pipeline.save_graph(directory, 'M1',
                                           fw_pipeline.starter_graph('M1', 'parts'), kind='machine')
            image = next(node for node in graph['nodes'] if node['type'] == 'partImage')
            image['result'] = dict(image.get('result') or {}, state='queued',
                                   parts={'part_0': {'state': 'queued'}})
            saved = fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            node = next(item for item in saved['nodes'] if item['type'] == 'partImage')
            self.assertEqual(node['result']['state'], 'queued')

    def test_assemble_writes_assembly_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts_dir = root / '_Source' / '机器' / 'M1' / 'pipeline' / 'parts'
            parts_dir.mkdir(parents=True)
            (parts_dir / 'partspec.json').write_text('{}', encoding='utf-8')
            graph = fw_pipeline.starter_graph('M1', 'parts')
            model = next(node for node in graph['nodes'] if node['type'] == 'partModel')
            model['result'] = {'state': 'done', 'output': {'contractPath': 'parts/partspec.json'}}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')

            def fake_assemble(contract_path, output_path, blender_path=None):
                Path(output_path).write_bytes(b'glb')
                return {'parts': [{'triangles': 120}, {'triangles': 80}]}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble', side_effect=fake_assemble):
                result = fw_pipeline.execute_local(directory, 'M1', target_id='assemble',
                                                   kind='machine', blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['meshPath'], 'model_assembly_assemble.glb')
            self.assertEqual(node['result']['output']['triangles'], 200)
            self.assertTrue((parts_dir.parent / 'outputs' / 'model_assembly_assemble.glb').is_file())

    def test_assemble_falls_back_to_partspec_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts_dir = root / '_Source' / '机器' / 'M1' / 'pipeline' / 'parts'
            parts_dir.mkdir(parents=True)
            (parts_dir / 'partspec.json').write_text('{}', encoding='utf-8')
            graph = fw_pipeline.starter_graph('M1', 'parts')
            spec = next(node for node in graph['nodes'] if node['type'] == 'partSpec')
            spec['result'] = {'state': 'done', 'output': {'contractPath': 'parts/partspec.json'}}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')

            def fake_assemble(contract_path, output_path, blender_path=None):
                Path(output_path).write_bytes(b'glb')
                return {'parts': [{'triangles': 10}]}

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble', side_effect=fake_assemble):
                result = fw_pipeline.execute_local(directory, 'M1', target_id='assemble',
                                                   kind='machine', blender_path='/fake/blender')
            node = next(item for item in result['graph']['nodes'] if item['type'] == 'assemble')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['parts'], 1)

    def test_assemble_applies_node_params_to_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts_dir = root / '_Source' / '机器' / 'M1' / 'pipeline' / 'parts'
            parts_dir.mkdir(parents=True)
            (parts_dir / 'partspec.json').write_text(json.dumps({
                'views': {'front': {}, 'side': {}},
                'parts': [{'id': 'part_0', 'name': '车身', 'mesh': 'part_0.glb',
                           'fit': 'contain', 'overlap': 0.0}],
            }), encoding='utf-8')
            graph = fw_pipeline.starter_graph('M1', 'parts')
            spec = next(node for node in graph['nodes'] if node['type'] == 'partSpec')
            spec['result'] = {'state': 'done', 'output': {'contractPath': 'parts/partspec.json'}}
            fw_pipeline.save_graph(directory, 'M1', graph, kind='machine')
            saved = fw_pipeline.load_graph(directory, 'M1', kind='machine')
            assemble = next(node for node in saved['nodes'] if node['type'] == 'assemble')
            assemble['params'] = {'fit': 'height', 'overlap': 0.05}
            fw_pipeline.save_graph(directory, 'M1', saved, kind='machine')

            with mock.patch.object(fw_pipeline.fw_parts, 'assemble',
                                   side_effect=lambda *a, **k: {'parts': []}):
                fw_pipeline.execute_local(directory, 'M1', target_id='assemble',
                                          kind='machine', blender_path='/fake/blender')
            contract = json.loads((parts_dir / 'partspec.json').read_text(encoding='utf-8'))
            self.assertEqual(contract['parts'][0]['fit'], 'height')
            self.assertEqual(contract['parts'][0]['overlap'], 0.05)


if __name__ == '__main__':
    unittest.main()
