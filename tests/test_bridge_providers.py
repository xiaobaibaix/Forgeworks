import io
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
_argv = sys.argv
sys.argv = [_argv[0]]
import bridge
import fw_providers
sys.argv = _argv


def _ccsettings(key='tsk_1234567890', base='https://ark.cn-beijing.volces.com/api/compatible',
                model='doubao-seedream-5-0-pro-260628'):
    return json.dumps({'env': {'ANTHROPIC_API_KEY': key, 'ANTHROPIC_BASE_URL': base,
                               'ANTHROPIC_MODEL': model}, 'model': 'opus[1m]'}, ensure_ascii=False)


def _write_ccswitch(path, rows):
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, settings_config TEXT)')
    connection.executemany('INSERT INTO providers VALUES (?, ?, ?, ?)', rows)
    connection.commit()
    connection.close()


class _FakeResponse:
    status = 200

    def read(self, size=None):
        return b'{}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ProviderSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'bridge_config.json'
        self.path.write_text(json.dumps({
            '_说明': '保留我',
            'blender': {'path': '/opt/blender'},
            'providers': {'ark': {'api_key': 'ark-old', 'endpoint': 'https://ark.cn-beijing.volces.com/api/v3'}},
        }, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def saved(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_view_never_returns_api_key(self):
        view = bridge.provider_settings_view(self.saved())
        self.assertTrue(view['ark']['configured'])
        self.assertFalse(view['tripo']['configured'])
        self.assertNotIn('api_key', json.dumps(view))

    def test_save_writes_key_and_keeps_unrelated_sections(self):
        view = bridge.save_provider_settings(
            {'providers': {'tripo': {'api_key': ' t-123 '}}}, str(self.path))
        data = self.saved()
        self.assertEqual(data['providers']['tripo']['api_key'], 't-123')
        self.assertEqual(data['providers']['ark']['api_key'], 'ark-old')
        self.assertEqual(data['_说明'], '保留我')
        self.assertEqual(data['blender']['path'], '/opt/blender')
        self.assertTrue(view['tripo']['configured'])

    def test_blank_key_keeps_existing(self):
        bridge.save_provider_settings({'providers': {'ark': {'api_key': '   '}}}, str(self.path))
        self.assertEqual(self.saved()['providers']['ark']['api_key'], 'ark-old')

    def test_clear_key_removes_it(self):
        view = bridge.save_provider_settings(
            {'providers': {'ark': {'clearKey': True}}}, str(self.path))
        self.assertNotIn('api_key', self.saved()['providers']['ark'])
        self.assertFalse(view['ark']['configured'])

    def test_ark_models_and_endpoint_are_saved(self):
        bridge.save_provider_settings({'providers': {'ark': {
            'endpoint': 'https://ark.cn-beijing.volces.com/api/compatible/',
            'image_model': 'doubao-seedream-5-0-pro-260628',
            'model3d_model': 'doubao-seed3d-2-0-260328',
        }}}, str(self.path))
        ark = self.saved()['providers']['ark']
        self.assertEqual(ark['endpoint'], 'https://ark.cn-beijing.volces.com/api/compatible')
        self.assertEqual(ark['image_model'], 'doubao-seedream-5-0-pro-260628')

    def test_rejects_non_volces_endpoint(self):
        with self.assertRaises(ValueError):
            bridge.save_provider_settings(
                {'providers': {'ark': {'endpoint': 'https://evil.example.com/api/v3'}}}, str(self.path))
        with self.assertRaises(ValueError):
            bridge.save_provider_settings(
                {'providers': {'ark': {'endpoint': 'http://ark.cn-beijing.volces.com/api/v3'}}}, str(self.path))

    def test_rejects_unknown_provider_and_bad_model(self):
        with self.assertRaises(ValueError):
            bridge.save_provider_settings({'providers': {'openai': {'api_key': 'x'}}}, str(self.path))
        with self.assertRaises(ValueError):
            bridge.save_provider_settings(
                {'providers': {'ark': {'image_model': 'bad model/name'}}}, str(self.path))

    def test_empty_payload_rejected(self):
        with self.assertRaises(ValueError):
            bridge.save_provider_settings({}, str(self.path))


class CcSwitchImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.db = str(self.base / 'cc-switch.db')
        self.config = self.base / 'bridge_config.json'
        self.config.write_text(json.dumps({
            '_说明': '保留我',
            'providers': {'tripo': {'api_key': 'tripo-old'}},
        }, ensure_ascii=False), encoding='utf-8')
        _write_ccswitch(self.db, [
            ('img', 'claude', '火山 Seedream 图像生成', _ccsettings()),
            ('model', 'claude', '火山 Seed3D 模型生成',
             _ccsettings(model='doubao-seed3d-2-0-260328')),
            ('llm', 'claude', '火山Agentplan', _ccsettings(model='deepseek-v4-1-flash-261017')),
            ('zhipu', 'claude', 'Zhipu', _ccsettings(base='https://api.z.ai/api/anthropic', model='glm-4')),
            ('nokey', 'claude', '空 Key', _ccsettings(key='')),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_candidates_only_list_volces_generation_models(self):
        candidates = bridge.ccswitch_candidates(self.db)
        self.assertEqual([item['id'] for item in candidates], ['img', 'model'])
        self.assertEqual(candidates[0]['field'], 'image_model')
        self.assertEqual(candidates[1]['field'], 'model3d_model')
        self.assertEqual(candidates[0]['keyHint'], '…7890')
        self.assertNotIn('tsk_1234567890', json.dumps(candidates))

    def test_import_writes_key_endpoint_and_model(self):
        view = bridge.import_ccswitch_provider('model', self.db, str(self.config))
        data = json.loads(self.config.read_text(encoding='utf-8'))
        self.assertEqual(data['providers']['ark']['api_key'], 'tsk_1234567890')
        self.assertEqual(data['providers']['ark']['endpoint'],
                         'https://ark.cn-beijing.volces.com/api/compatible')
        self.assertEqual(data['providers']['ark']['model3d_model'], 'doubao-seed3d-2-0-260328')
        self.assertEqual(data['providers']['tripo']['api_key'], 'tripo-old')
        self.assertEqual(data['_说明'], '保留我')
        self.assertTrue(view['ark']['configured'])
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_import_rejects_unknown_or_non_generation_entry(self):
        with self.assertRaises(ValueError):
            bridge.import_ccswitch_provider('llm', self.db, str(self.config))
        with self.assertRaises(ValueError):
            bridge.import_ccswitch_provider('missing', self.db, str(self.config))

    def test_missing_db_lists_nothing(self):
        self.assertEqual(bridge.ccswitch_candidates(str(self.base / 'nope.db')), [])


class PipelineTaskOutputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.task = {'taskId': 'arkimg_abc123', 'state': 'success', 'provider': 'ark',
                     'output': {'generated_image_url': 'https://ark-content.volces.com/x.png'}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_synchronous_image_is_stored_immediately(self):
        with mock.patch.object(bridge.fw_providers, 'download_image',
                               return_value=(b'\x89PNG\r\n\x1a\n', 'png')):
            task = bridge.store_task_output(self.root, 'Fe', 'element', 'textToImage', self.task)
        path = Path(self.root) / '_Source' / '元素' / 'Fe' / 'pipeline' / 'outputs' / 'image_arkimg_abc123.png'
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), b'\x89PNG\r\n\x1a\n')
        self.assertEqual(task['output']['imagePath'], 'outputs/image_arkimg_abc123.png')
        self.assertNotIn('generated_image_url', task['output'])

    def test_download_failure_keeps_remote_url(self):
        with mock.patch.object(bridge.fw_providers, 'download_image',
                               side_effect=RuntimeError('boom')):
            task = bridge.store_task_output(self.root, 'Fe', 'element', 'textToImage', self.task)
        self.assertEqual(task['output'], {'generated_image_url': 'https://ark-content.volces.com/x.png'})

    def test_non_image_nodes_are_untouched(self):
        with mock.patch.object(bridge.fw_providers, 'download_image') as download:
            task = bridge.store_task_output(self.root, 'Fe', 'element', 'imageTo3D', self.task)
        download.assert_not_called()
        self.assertEqual(task, self.task)


class PipelinePartTaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.pipeline = Path(self.root) / '_Source' / '元素' / 'Fe' / 'pipeline'
        self.parts = self.pipeline / 'parts'
        self.outputs = self.pipeline / 'outputs'
        self.parts.mkdir(parents=True)
        self.outputs.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _contract(self, parts):
        view = {'width': 1000, 'height': 1000, 'ground': 900, 'pxPerMeter': 100}
        return {'schemaVersion': 1, 'assetId': 'Fe',
                'views': {'front': dict(view), 'side': dict(view)}, 'parts': parts}

    def _write_contract(self, relative='parts/partspec.json'):
        path = self.pipeline / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._contract([
            {'id': 'part_0', 'name': '车身', 'description': '方正外壳', 'mesh': 'part_0.glb',
             'front': [100, 100, 100, 100], 'side': [100, 100, 100, 100]},
            {'id': 'part_1', 'name': '车顶', 'mesh': 'part_1.glb',
             'front': [100, 100, 100, 100], 'side': [100, 100, 100, 100]},
        ]), ensure_ascii=False), encoding='utf-8')
        return path

    def test_part_prompt_repeats_name_description_and_base(self):
        prompt = bridge._part_prompt('整机是方正 SUV', {'id': 'part_0', 'name': '车身',
                                                      'description': '方正外壳'})
        self.assertIn('整机是方正 SUV', prompt)
        self.assertIn('【只生成这个部件】车身 — 方正外壳', prompt)
        self.assertIn('纯色', prompt)

    def test_contract_path_walks_upstream_edges(self):
        graph = {'edges': [{'from': 'spec', 'to': 'image', 'in': 'contract'}]}
        nodes = {'spec': {'id': 'spec', 'result': {'output': {'contractPath': 'parts/partspec.json'}}},
                 'image': {'id': 'image'}}
        self.assertEqual(bridge._contract_path_upstream(graph, nodes, nodes['image']),
                         'parts/partspec.json')
        self.assertIsNone(bridge._contract_path_upstream({'edges': []}, nodes, nodes['image']))

    def test_load_contract_part_rejects_traversal_and_missing(self):
        self._write_contract()
        absolute, part = bridge._load_contract_part(self.root, 'Fe', 'element',
                                                    'parts/partspec.json', 'part_1')
        self.assertTrue(absolute.endswith('partspec.json'))
        self.assertEqual(part['name'], '车顶')
        with self.assertRaises(ValueError):
            bridge._load_contract_part(self.root, 'Fe', 'element', '../partspec.json', 'part_0')
        with self.assertRaises(ValueError):
            bridge._load_contract_part(self.root, 'Fe', 'element', 'parts/partspec.json', 'part_9')

    def test_part_entries_keeps_existing_state_and_adds_skeleton(self):
        upstream = {'result': {'output': {'parts': [{'id': 'part_0', 'name': '车身'},
                                                    {'id': 'part_1', 'name': '车顶'}]}}}
        node = {'result': {'parts': {'part_0': {'state': 'success',
                                                'output': {'imagePath': 'outputs/image_a.png'}}}}}
        entries = bridge._part_entries(node, upstream)
        self.assertEqual(entries['part_0']['state'], 'success')
        self.assertEqual(entries['part_0']['output']['imagePath'], 'outputs/image_a.png')
        self.assertEqual(entries['part_1']['state'], 'pending')
        self.assertEqual(entries['part_1']['name'], '车顶')

    def test_sync_part_node_aggregates_progress(self):
        node = {'result': {'parts': {'part_0': {'name': '车身', 'state': 'success'},
                                     'part_1': {'name': '车顶', 'state': 'queued'}}}}
        bridge._sync_part_node(node)
        self.assertEqual(node['result']['state'], 'queued')
        self.assertEqual(node['result']['output']['done'], 1)
        self.assertEqual(node['result']['output']['total'], 2)
        self.assertEqual(node['result']['output']['parts'][0]['name'], '车身')

    def test_store_part_image_writes_outputs_and_entry(self):
        entry = {}
        task = {'taskId': 'task_img', 'state': 'success', 'provider': 'tripo',
                'output': {'generated_image_url': 'https://example.com/a.png'}}
        with mock.patch.object(bridge.fw_providers, 'download_image',
                               return_value=(b'\x89PNG\r\n\x1a\n', 'png')):
            bridge._store_part_image(self.root, 'Fe', 'element', entry, task)
        self.assertTrue((self.outputs / 'image_task_img.png').is_file())
        self.assertEqual(entry['output']['imagePath'], 'outputs/image_task_img.png')

    def test_store_part_model_writes_glb_and_patches_contract(self):
        contract_path = self._write_contract()
        part = {'id': 'part_1', 'name': '车顶'}
        entry = {'output': {'imagePath': 'outputs/image_a.png'}}
        task = {'taskId': 'task_model', 'state': 'success'}
        with mock.patch.object(bridge.fw_providers, 'download_model', return_value=b'glb'):
            bridge._store_part_model(self.root, 'Fe', 'element', str(contract_path), part, entry,
                                     task, {'model_url': 'https://example.com/a.glb'})
        self.assertTrue((self.parts / 'model_task_model.glb').is_file())
        self.assertEqual(entry['output']['modelPath'], 'parts/model_task_model.glb')
        self.assertEqual(entry['output']['imagePath'], 'outputs/image_a.png')
        contract = json.loads(contract_path.read_text(encoding='utf-8'))
        self.assertEqual(contract['parts'][1]['mesh'], 'model_task_model.glb')
        self.assertEqual(contract['parts'][0]['mesh'], 'part_0.glb')

    def test_part_input_image_builds_data_uri(self):
        (self.outputs / 'image_a.png').write_bytes(b'png')
        data = bridge._part_input_image(self.root, 'Fe', 'element',
                                        {'output': {'imagePath': 'outputs/image_a.png'}})
        self.assertTrue(data.startswith('data:image/png;base64,'))
        self.assertIsNone(bridge._part_input_image(self.root, 'Fe', 'element', {}))


class ProviderConnectionTest(unittest.TestCase):
    def test_unconfigured_provider_reports_missing_key(self):
        result = fw_providers.test_connection({}, 'ark')
        self.assertFalse(result['configured'])
        self.assertFalse(result['ok'])

    def test_ark_success_probes_models_endpoint(self):
        config = {'providers': {'ark': {'api_key': 'k'}}}
        with mock.patch.object(fw_providers.urllib.request, 'urlopen', return_value=_FakeResponse()):
            result = fw_providers.test_connection(config, 'ark')
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 200)

    def test_tripo_missing_probe_task_means_authenticated(self):
        config = {'providers': {'tripo': {'api_key': 'k'}}}
        error = urllib.error.HTTPError('https://openapi.tripo3d.ai/v3/tasks/probe',
                                       404, 'Not Found', {}, None)
        with mock.patch.object(fw_providers.urllib.request, 'urlopen', side_effect=error):
            result = fw_providers.test_connection(config, 'tripo')
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 404)

    def test_authentication_failure_is_reported(self):
        config = {'providers': {'tripo': {'api_key': 'bad'}}}
        error = urllib.error.HTTPError('https://openapi.tripo3d.ai/v3/tasks/probe',
                                       401, 'Unauthorized', {}, None)
        with mock.patch.object(fw_providers.urllib.request, 'urlopen', side_effect=error):
            result = fw_providers.test_connection(config, 'tripo')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 401)
        self.assertIn('API Key', result['error'])

    def test_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            fw_providers.test_connection({}, 'openai')


class ProviderParameterTest(unittest.TestCase):
    config = {'providers': {'tripo': {'api_key': 'k'}, 'ark': {'api_key': 'k'}}}

    def _capture_tripo(self, params):
        captured = {}

        def fake(url, api_key, payload=None, timeout=30):
            captured.update(payload)
            return {'task_id': 'task_abcdef'}

        with mock.patch.object(fw_providers, '_request', side_effect=fake):
            fw_providers._tripo_submit(self.config, 'imageTo3D', params, '', 'task_input')
        return captured

    def test_tripo_image_to_3d_forwards_quality_options(self):
        body = self._capture_tripo({
            'texture': True, 'pbr': True, 'faceLimit': 12000, 'smartLowPoly': True,
            'textureQuality': 'detailed', 'autoSize': True, 'orientation': 'align_image',
            'modelSeed': 7, 'textureSeed': 9, 'tripoModel': 'v3.0-20250812',
        })
        self.assertEqual(body['face_limit'], 12000)
        self.assertEqual(body['texture_quality'], 'detailed')
        self.assertTrue(body['auto_size'])
        self.assertEqual(body['orientation'], 'align_image')
        self.assertEqual(body['model_seed'], 7)
        self.assertEqual(body['texture_seed'], 9)
        self.assertEqual(body['model'], 'v3.0-20250812')

    def test_tripo_texture_only_options_are_dropped_without_texture(self):
        body = self._capture_tripo({
            'texture': False, 'pbr': True, 'textureQuality': 'detailed',
            'autoSize': True, 'orientation': 'align_image', 'textureSeed': 5,
        })
        self.assertFalse(body['pbr'])
        for key in ('texture_quality', 'auto_size', 'orientation', 'texture_seed'):
            self.assertNotIn(key, body)

    def test_tripo_face_limit_is_clamped(self):
        self.assertEqual(self._capture_tripo({'texture': False, 'faceLimit': 10})['face_limit'], 500)
        self.assertEqual(self._capture_tripo({'texture': False, 'faceLimit': 999999})['face_limit'], 150000)

    def test_ark_text_to_image_forwards_size_and_format(self):
        captured = {}

        def fake(config, path, payload=None, timeout=60):
            captured.update(payload)
            return {'data': [{'url': 'https://ark-content.volces.com/x.png'}]}

        with mock.patch.object(fw_providers, '_ark_request', side_effect=fake):
            fw_providers._ark_submit(self.config, 'textToImage',
                                     {'size': '2K', 'outputFormat': 'jpeg', 'watermark': True}, 'prompt', '')
        self.assertEqual(captured['size'], '2K')
        self.assertEqual(captured['output_format'], 'jpeg')
        self.assertTrue(captured['watermark'])


class ProviderErrorTest(unittest.TestCase):
    def test_tripo_error_body_is_surfaced(self):
        body = json.dumps({'code': 2010, 'status': 'error',
                           'message': "You don't have enough credit to create this task",
                           'suggestion': 'Please purchase more credit'}).encode()
        error = urllib.error.HTTPError('https://openapi.tripo3d.ai/v3/generation/text-to-image',
                                       403, 'Forbidden', {}, io.BytesIO(body))
        with mock.patch.object(fw_providers.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                fw_providers._request('https://openapi.tripo3d.ai/v3/generation/text-to-image',
                                      'k', {'prompt': 'x'})
        message = str(raised.exception)
        self.assertIn('Tripo 2010', message)
        self.assertIn('HTTP 403', message)
        self.assertIn('credit', message)

    def test_tripo_error_without_json_keeps_status(self):
        error = urllib.error.HTTPError('https://openapi.tripo3d.ai/v3/generation/text-to-image',
                                       403, 'Forbidden', {}, io.BytesIO(b'not json'))
        with mock.patch.object(fw_providers.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                fw_providers._request('https://openapi.tripo3d.ai/v3/generation/text-to-image', 'k', {})
        self.assertEqual(str(raised.exception), 'Provider HTTP 403')


if __name__ == '__main__':
    unittest.main()
