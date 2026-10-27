import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
_argv = sys.argv
sys.argv = [_argv[0]]
import bridge
import fw_pipeline
import fw_providers
import fw_spec
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


class PipelinePartNodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.outputs = Path(self.root) / '_Source' / '元素' / 'Fe' / 'pipeline' / 'outputs'
        self.outputs.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_part_image_prompt_keeps_text_and_adds_single_part_suffix(self):
        prompt = bridge._part_image_prompt('一辆方正的车身，深蓝色')
        self.assertTrue(prompt.startswith('一辆方正的车身，深蓝色'))
        self.assertIn(bridge.PART_IMAGE_SUFFIX, prompt)

    def test_empty_part_image_prompt_is_only_suffix(self):
        self.assertEqual(bridge._part_image_prompt('  '), bridge.PART_IMAGE_SUFFIX)

    def test_part_name_uses_first_line_without_markers(self):
        self.assertEqual(bridge._part_name_from_prompt('【车身】\n深蓝色外壳'), '车身')
        self.assertEqual(bridge._part_name_from_prompt('\n\n车顶'), '车顶')
        self.assertEqual(bridge._part_name_from_prompt(''), '')

    def test_part_name_is_truncated_to_32_characters(self):
        self.assertEqual(len(bridge._part_name_from_prompt('车' * 40)), 32)

    def test_part_image_is_stored_immediately(self):
        task = {'taskId': 'task_img', 'state': 'success', 'provider': 'tripo',
                'output': {'generated_image_url': 'https://example.com/a.png'}}
        with mock.patch.object(bridge.fw_providers, 'download_image',
                               return_value=(b'\x89PNG\r\n\x1a\n', 'png')):
            bridge.store_task_output(self.root, 'Fe', 'element', 'partImage', task)
        self.assertTrue((self.outputs / 'image_task_img.png').is_file())
        self.assertEqual(task['output']['imagePath'], 'outputs/image_task_img.png')

    def test_image_data_url_builds_data_uri(self):
        (self.outputs / 'image_a.png').write_bytes(b'png')
        data = bridge._image_data_url(self.root, 'Fe', 'element', 'outputs/image_a.png')
        self.assertTrue(data.startswith('data:image/png;base64,'))
        self.assertIsNone(bridge._image_data_url(self.root, 'Fe', 'element', None))

    def _reference(self, state='done', image='outputs/image_overall.png'):
        nodes = {'overall': {'id': 'overall', 'type': 'textToImage',
                             'result': {'state': state,
                                        'providerTask': {'output': {'imagePath': image}}}}}
        edges = [{'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'}]
        return nodes, edges

    def test_part_reference_image_requires_image_edge(self):
        with self.assertRaises(ValueError):
            bridge._part_reference_image(self.root, 'Fe', 'element', {}, [])

    def test_part_reference_image_rejects_stale_or_unrun_upstream(self):
        for state in ('dirty', 'queued', 'failed'):
            nodes, edges = self._reference(state=state)
            with self.assertRaises(ValueError):
                bridge._part_reference_image(self.root, 'Fe', 'element', nodes, edges)

    def test_part_reference_image_builds_data_uri(self):
        (self.outputs / 'image_overall.png').write_bytes(b'png')
        nodes, edges = self._reference()
        data = bridge._part_reference_image(self.root, 'Fe', 'element', nodes, edges)
        self.assertTrue(data.startswith('data:image/png;base64,'))

    def test_no_part_id_remains_in_provider_routes(self):
        source = Path(bridge.__file__).read_text(encoding='utf-8')
        self.assertNotIn('partId', source)


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


class PipelineProviderConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []
        created = bridge.create_project(str(self.workspace), '并发工程')
        self.root = Path(created['fwDir'])
        self.server = bridge.Bridge(('127.0.0.1', 0), bridge.BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self.graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'img_a', 'type': 'textToImage', 'x': 0, 'y': 0,
                 'params': {'provider': 'ark', 'prompt': 'a'}},
                {'id': 'img_b', 'type': 'textToImage', 'x': 300, 'y': 0,
                 'params': {'provider': 'ark', 'prompt': 'b'}},
            ],
            'edges': [],
        }
        fw_pipeline.save_graph(str(self.root), 'M1', self.graph, kind='machine')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.tmp.cleanup()

    def _post(self, route, payload):
        request = urllib.request.Request(
            self.origin + '/api/' + route,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Origin': self.origin},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            return json.loads(error.read())

    def _run_parallel(self, jobs):
        results = [None] * len(jobs)
        errors = []

        def worker(index, job):
            try:
                results[index] = job()
            except Exception as error:  # pragma: no cover - 失败时在线程内保留原因
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(index, job))
                   for index, job in enumerate(jobs)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        return results

    def test_simultaneous_submits_keep_both_tasks(self):
        barrier = threading.Barrier(2)

        def fake_submit(config, kind, params, prompt='', input_task_id=None,
                        image_data=None, fallback=False):
            barrier.wait(timeout=10)
            return {'taskId': 'arkimg_' + prompt, 'provider': 'ark', 'state': 'queued',
                    'params': dict(params)}

        with mock.patch.object(bridge.fw_providers, 'submit', side_effect=fake_submit):
            results = self._run_parallel([
                lambda node='img_a': self._post('pipeline/provider/submit', {
                    'assetId': 'M1', 'kind': 'machine', 'nodeId': node, 'confirmRemote': True}),
                lambda node='img_b': self._post('pipeline/provider/submit', {
                    'assetId': 'M1', 'kind': 'machine', 'nodeId': node, 'confirmRemote': True}),
            ])
        self.assertTrue(all(result.get('ok') for result in results), results)
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        tasks = {node['id']: node['result']['providerTask']['taskId'] for node in graph['nodes']}
        self.assertEqual(tasks, {'img_a': 'arkimg_a', 'img_b': 'arkimg_b'})

    def test_simultaneous_stale_saves_keep_provider_tasks(self):
        tasks = {
            'img_a': {'taskId': 'arkimg_aaaa', 'provider': 'ark', 'state': 'queued'},
            'img_b': {'taskId': 'arkimg_bbbb', 'provider': 'ark', 'state': 'running'},
        }
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        for node in graph['nodes']:
            node['result'] = {'providerTask': tasks[node['id']]}
        fw_pipeline.save_graph(str(self.root), 'M1', graph, kind='machine')
        current = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        snapshots = [json.loads(json.dumps(current)) for _ in range(2)]
        for snapshot in snapshots:
            for node in snapshot['nodes']:
                node['result'] = {}
        results = self._run_parallel([
            lambda snapshot=snapshot: self._post('pipeline/graph/save', {
                'assetId': 'M1', 'kind': 'machine', 'graph': snapshot})
            for snapshot in snapshots
        ])
        self.assertTrue(all(result.get('ok') for result in results), results)
        final = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        saved = {node['id']: (node.get('result') or {}).get('providerTask', {}).get('taskId')
                 for node in final['nodes']}
        self.assertEqual(saved, {'img_a': 'arkimg_aaaa', 'img_b': 'arkimg_bbbb'})


class BlueprintBridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []
        created = bridge.create_project(str(self.workspace), '规格工程')
        self.root = Path(created['fwDir'])
        self.server = bridge.Bridge(('127.0.0.1', 0), bridge.BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self.pipeline = Path(fw_pipeline.pipeline_root(str(self.root), 'M1', 'machine'))
        (self.pipeline / 'outputs').mkdir(parents=True, exist_ok=True)
        (self.pipeline / 'outputs' / 'overall.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        self.spec = fw_spec.template_spec('M1')
        self.graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'blueprint', 'type': 'blueprint',
                 'params': {'provider': 'ark', 'overallLengthM': 7.2,
                            'template': 'excavator'}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {'provider': 'ark'},
                 'result': {'output': {'partName': '车身'}}},
            ],
            'edges': [
                {'from': 'overall', 'out': 'image', 'to': 'blueprint', 'in': 'image'},
                {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
            ],
        }
        saved = fw_pipeline.save_graph(str(self.root), 'M1', self.graph, kind='machine')
        # 首次保存会把未签名结果打回 dirty；二次保存保留已执行状态，贴近真实运行后的图
        for node in saved['nodes']:
            node['result']['state'] = 'done'
        fw_pipeline.save_graph(str(self.root), 'M1', saved, kind='machine')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.tmp.cleanup()

    def _post(self, route, payload):
        request = urllib.request.Request(
            self.origin + '/api/' + route,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Origin': self.origin},
            method='POST')
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            return json.loads(error.read())

    def test_blueprint_requires_confirm_remote(self):
        with mock.patch.object(bridge.fw_providers, 'analyze_spec') as analyze:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint'})
        self.assertFalse(result['ok'])
        self.assertIn('确认', result['error'])
        analyze.assert_not_called()

    def test_blueprint_writes_spec_and_node_output(self):
        def fake(config, image_path, parts, prompt='', model='', overall_length=0.0,
                 template='excavator'):
            return {'parts': {}, 'connections': []}, {'model': 'vision', 'notes': ''}

        with mock.patch.object(bridge.fw_providers, 'analyze_spec', side_effect=fake):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        self.assertTrue((self.pipeline / 'spec.json').is_file())
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        node = next(node for node in graph['nodes'] if node['id'] == 'blueprint')
        self.assertEqual(node['result']['state'], 'done')
        self.assertEqual(result['state'], 'done')
        self.assertEqual(node['result']['output']['spec']['assetId'], 'M1')
        self.assertTrue(node['result']['providerTask']['taskId'].startswith('spec_'))

    def _lock_blueprint_params(self):
        def lock(latest):
            for node in latest['nodes']:
                if node['id'] == 'blueprint':
                    node['params']['specLocked'] = True
            return latest
        fw_pipeline.update_graph(str(self.root), 'M1', 'machine', lock)

    def test_blueprint_locked_reads_spec_without_calling_provider(self):
        fw_spec.write_spec(str(self.pipeline / 'spec.json'), self.spec)
        self._lock_blueprint_params()
        with mock.patch.object(bridge.fw_providers, 'analyze_spec') as analyze:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['taskId'], 'spec_locked')
        analyze.assert_not_called()

    def test_blueprint_locked_without_spec_file_does_not_call_provider(self):
        self._lock_blueprint_params()
        with mock.patch.object(bridge.fw_providers, 'analyze_spec') as analyze:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint',
                'confirmRemote': True})
        self.assertFalse(result['ok'], result)
        self.assertIn('SPEC_MISSING', result['error'])
        analyze.assert_not_called()

    def test_blueprint_params_change_during_analysis_is_rejected(self):
        def fake(config, image_path, parts, prompt='', model='', overall_length=0.0,
                 template='excavator'):
            def mutate(latest):
                for node in latest['nodes']:
                    if node['id'] == 'blueprint':
                        node['params']['overallLengthM'] = 8.0
                return latest
            fw_pipeline.update_graph(str(self.root), 'M1', 'machine', mutate)
            return {'parts': {}, 'connections': []}, {'model': 'vision', 'notes': ''}

        with mock.patch.object(bridge.fw_providers, 'analyze_spec', side_effect=fake):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint',
                'confirmRemote': True})
        self.assertFalse(result['ok'], result)
        self.assertIn('参数已修改', result['error'])
        self.assertFalse((self.pipeline / 'spec.json').exists())

    def test_overall_scope_warns_when_multiple_spec_writers(self):
        def add_copy(latest):
            latest['nodes'].append({'id': 'blueprint_copy', 'type': 'blueprint',
                                    'params': {'overallLengthM': 7.2}})
            return latest
        fw_pipeline.update_graph(str(self.root), 'M1', 'machine', add_copy)

        def fake(config, image_path, parts, prompt='', model='', overall_length=0.0,
                 template='excavator'):
            return {'parts': {}, 'connections': []}, {'model': 'vision', 'notes': ''}

        with mock.patch.object(bridge.fw_providers, 'analyze_spec', side_effect=fake):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        node = next(node for node in graph['nodes'] if node['id'] == 'blueprint')
        warnings = node['result'].get('warnings') or []
        self.assertTrue(any('SPEC_WRITER_DUPLICATE' in item for item in warnings), warnings)

    def _save_part_measure_graph(self, params=None):
        (self.pipeline / 'outputs' / 'sheet.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'sheet', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/sheet.png'}}}},
                {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                 'result': {'state': 'done',
                            'output': {'spec': self.spec, 'specPath': 'spec.json'}}},
                {'id': 'blueprint_body', 'type': 'blueprint',
                 'params': dict({'provider': 'ark', 'scope': 'part'}, **(params or {}))},
            ],
            'edges': [
                {'from': 'sheet', 'out': 'image', 'to': 'blueprint_body', 'in': 'image'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'blueprint_body', 'in': 'spec'},
            ],
        }
        saved = fw_pipeline.save_graph(str(self.root), 'M1', graph, kind='machine')
        # 首次保存会把未签名结果打回 dirty；二次保存保留已执行状态，贴近真实运行后的图
        for node in saved['nodes']:
            node['result']['state'] = 'done'
        fw_pipeline.save_graph(str(self.root), 'M1', saved, kind='machine')

    def test_part_scope_writes_measure_without_spec(self):
        self._save_part_measure_graph()

        def fake(config, image_path, parts, scope='overall', role='', label='',
                 overall_length=0.0, template='excavator', prompt='', model=''):
            return ({'parts': {'body': {'sizeM': [1.2, 0.6, 0.5],
                                        'forward': '+X', 'confidence': 0.7}},
                     'notes': ['ok']}, {'model': 'vision', 'notes': 'ok'})

        with mock.patch.object(bridge.fw_providers, 'analyze_dimensions', side_effect=fake):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint_body',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        self.assertFalse((self.pipeline / 'spec.json').exists())
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        node = next(node for node in graph['nodes'] if node['id'] == 'blueprint_body')
        self.assertEqual(node['result']['state'], 'done')
        output = node['result']['output']
        self.assertEqual(output['measure']['role'], 'body')
        self.assertEqual(output['measure']['sizeM'], [1.2, 0.6, 0.5])
        self.assertEqual(output['measure']['anchor']['overallLengthM'], 7.2)
        self.assertNotIn('spec', output)
        self.assertTrue(node['result']['providerTask']['taskId'].startswith('measure_'))

    def test_part_scope_requires_upstream_spec(self):
        (self.pipeline / 'outputs' / 'sheet.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'sheet', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/sheet.png'}}}},
                {'id': 'blueprint_body', 'type': 'blueprint',
                 'params': {'provider': 'ark', 'scope': 'part', 'role': 'body'}},
            ],
            'edges': [
                {'from': 'sheet', 'out': 'image', 'to': 'blueprint_body', 'in': 'image'},
            ],
        }
        saved = fw_pipeline.save_graph(str(self.root), 'M1', graph, kind='machine')
        for node in saved['nodes']:
            node['result']['state'] = 'done'
        fw_pipeline.save_graph(str(self.root), 'M1', saved, kind='machine')
        with mock.patch.object(bridge.fw_providers, 'analyze_dimensions') as analyze:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint_body',
                'confirmRemote': True})
        self.assertFalse(result['ok'], result)
        self.assertIn('SPEC_MISSING', result['error'])
        analyze.assert_not_called()

    def test_part_scope_rejects_spec_locked(self):
        self._save_part_measure_graph({'specLocked': True})
        with mock.patch.object(bridge.fw_providers, 'analyze_dimensions') as analyze:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint_body',
                'confirmRemote': True})
        self.assertFalse(result['ok'], result)
        self.assertIn('specLocked', result['error'])
        analyze.assert_not_called()

    def _save_spec_input_graph(self):
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                 'result': {'state': 'done', 'output': {'spec': self.spec,
                                                        'specPath': 'spec.json'}}},
                {'id': 'prompt_body', 'type': 'prompt', 'params': {'text': '车身'}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {'provider': 'ark'},
                 'result': {'output': {'partName': '车身'}}},
            ],
            'edges': [
                {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
                {'from': 'prompt_body', 'out': 'text', 'to': 'partImage_body', 'in': 'text'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'partImage_body', 'in': 'spec'},
            ],
        }
        saved = fw_pipeline.save_graph(str(self.root), 'M1', graph, kind='machine')
        # 首次保存会把未签名结果打回 dirty；二次保存保留已执行状态，贴近真实运行后的图
        for node in saved['nodes']:
            node['result']['state'] = 'done'
        fw_pipeline.save_graph(str(self.root), 'M1', saved, kind='machine')

    def test_part_image_rejects_dirty_spec_upstream(self):
        self._save_spec_input_graph()
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        next(node for node in graph['nodes'] if node['id'] == 'blueprint')['result']['state'] = 'dirty'
        fw_pipeline.save_graph(str(self.root), 'M1', graph, kind='machine')
        with mock.patch.object(bridge.fw_providers, 'submit') as submit:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'partImage_body',
                'confirmRemote': True})
        self.assertFalse(result['ok'], result)
        self.assertIn('尺寸规格', result['error'])
        submit.assert_not_called()

    def test_part_image_gets_ports_from_spec_input(self):
        self._save_spec_input_graph()
        seen = {}

        def fake_submit(config, kind, params, prompt='', input_task_id=None,
                        image_data=None, fallback=False):
            seen['prompt'] = prompt
            return {'taskId': 'img_body', 'provider': 'ark', 'state': 'success',
                    'output': {}}

        with mock.patch.object(bridge.fw_providers, 'submit', side_effect=fake_submit):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'partImage_body',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        size = self.spec['parts']['body']['sizeM']
        self.assertIn('目标包围盒尺寸', seen['prompt'])
        self.assertIn('X %.2f m' % size[0], seen['prompt'])
        self.assertIn('Y %.2f m' % size[1], seen['prompt'])
        self.assertIn('Z %.2f m' % size[2], seen['prompt'])
        node = next(node for node in result['graph']['nodes']
                    if node['id'] == 'partImage_body')
        self.assertEqual(node['result']['output']['role'], 'body')
        self.assertEqual(node['result']['output']['ports'][0]['id'], 'boom_base')
        self.assertNotIn('pos', node['result']['output']['ports'][0])


if __name__ == '__main__':
    unittest.main()
