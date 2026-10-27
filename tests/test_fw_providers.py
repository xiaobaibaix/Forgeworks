import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fw_providers', ROOT / 'tools' / 'fw_providers.py')
fw_providers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw_providers)

ARK_CONFIG = {'providers': {'ark': {'api_key': 'ark-test', 'endpoint': 'https://ark.cn-beijing.volces.com/api/v3'}}}
IMAGE_URL = 'https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/a.png'
MODEL_URL = 'https://ark-content-cn-beijing.tos-cn-beijing.volces.com/a.glb'


class ProviderPickTest(unittest.TestCase):
    def test_falls_back_to_configured_provider_when_node_names_unconfigured_one(self):
        self.assertEqual(fw_providers._pick_provider(ARK_CONFIG, {'provider': 'tripo'}, True), 'ark')

    def test_strict_mode_keeps_explicit_unconfigured_provider(self):
        self.assertEqual(fw_providers._pick_provider(ARK_CONFIG, {'provider': 'tripo'}), 'tripo')

    def test_prefers_explicit_provider_when_configured(self):
        config = {'providers': {'ark': {'api_key': 'ark'}, 'tripo': {'api_key': 't'}}}
        self.assertEqual(fw_providers._pick_provider(config, {'provider': 'tripo'}, True), 'tripo')


class ArkSubmitTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.original = fw_providers._ark_request

    def tearDown(self):
        fw_providers._ark_request = self.original

    def test_image_submit_returns_ready_url(self):
        def fake(config, path, payload=None, timeout=60):
            self.calls.append((path, payload))
            return {'data': [{'url': IMAGE_URL}], 'usage': {'generated_images': 1}}
        fw_providers._ark_request = fake

        task = fw_providers.submit(ARK_CONFIG, 'textToImage', {'provider': 'ark'}, 'wooden crate')

        self.assertEqual(task['provider'], 'ark')
        self.assertEqual(task['state'], 'success')
        self.assertEqual(task['output']['generated_image_url'], IMAGE_URL)
        self.assertEqual(self.calls[0][0], '/images/generations')
        self.assertEqual(self.calls[0][1]['response_format'], 'url')

    def test_image3d_submit_sends_data_uri_and_returns_task(self):
        def fake(config, path, payload=None, timeout=60):
            self.calls.append((path, payload))
            return {'id': 'cgt-20261023143146-z9hl7'}
        fw_providers._ark_request = fake

        task = fw_providers.submit(ARK_CONFIG, 'imageTo3D', {'provider': 'ark'}, 'a crate',
                                   None, 'data:image/png;base64,AAAA')

        self.assertEqual(task['taskId'], 'cgt-20261023143146-z9hl7')
        content = self.calls[0][1]['content']
        self.assertEqual(content[0], {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}})
        self.assertEqual(content[1], {'type': 'text', 'text': 'a crate'})

    def test_image3d_requires_input_image(self):
        with self.assertRaises(ValueError):
            fw_providers.submit(ARK_CONFIG, 'imageTo3D', {'provider': 'ark'}, '', None, None)

    def test_image_submit_forwards_reference_image(self):
        def fake(config, path, payload=None, timeout=60):
            self.calls.append((path, payload))
            return {'data': [{'url': IMAGE_URL}]}
        fw_providers._ark_request = fake

        fw_providers.submit(ARK_CONFIG, 'textToImage', {'provider': 'ark'}, '【车身】拆件',
                            None, 'data:image/png;base64,AAAA')

        self.assertEqual(self.calls[0][1]['image'], 'data:image/png;base64,AAAA')

    def test_reference_image_requires_ark_provider(self):
        config = {'providers': {'tripo': {'api_key': 't'}}}
        with self.assertRaises(ValueError):
            fw_providers.submit(config, 'textToImage', {'provider': 'tripo'}, '【车身】拆件',
                                None, 'data:image/png;base64,AAAA')


class ArkPollTest(unittest.TestCase):
    def setUp(self):
        self.original = fw_providers._ark_request

    def tearDown(self):
        fw_providers._ark_request = self.original

    def test_poll_maps_succeeded_and_model_url(self):
        fw_providers._ark_request = lambda *args, **kwargs: {
            'status': 'succeeded', 'content': {'model_url': MODEL_URL}}
        result = fw_providers.poll(ARK_CONFIG, {'provider': 'ark', 'taskId': 'cgt-20261023143146-z9hl7',
                                                'requestType': 'imageTo3D'})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['progress'], 100)
        self.assertEqual(result['output']['model_url'], MODEL_URL)

    def test_poll_maps_expired_to_cancelled(self):
        fw_providers._ark_request = lambda *args, **kwargs: {'status': 'expired'}
        result = fw_providers.poll(ARK_CONFIG, {'provider': 'ark', 'taskId': 'cgt-20261023143146-z9hl7',
                                                'requestType': 'imageTo3D'})
        self.assertEqual(result['status'], 'cancelled')

    def test_image_task_poll_uses_stored_url_without_remote_call(self):
        def fail(*args, **kwargs):
            raise AssertionError('image poll must not call the API')
        fw_providers._ark_request = fail
        result = fw_providers.poll(ARK_CONFIG, {'provider': 'ark', 'taskId': 'arkimg_abcdef',
                                                'requestType': 'textToImage',
                                                'output': {'generated_image_url': IMAGE_URL}})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['output']['generated_image_url'], IMAGE_URL)


class DownloadGuardTest(unittest.TestCase):
    def test_accepts_volces_hosts(self):
        self.assertTrue(fw_providers._allowed_download_host('ark-acg-cn-beijing.tos-cn-beijing.volces.com'))
        self.assertTrue(fw_providers._allowed_download_host('cdn.tripo3d.ai'))

    def test_rejects_other_hosts(self):
        self.assertFalse(fw_providers._allowed_download_host('example.com'))
        self.assertFalse(fw_providers._allowed_download_host('volces.com.evil.test'))

    def test_rejects_non_https_image_url(self):
        with self.assertRaises(ValueError):
            fw_providers._check_remote_url('http://ark-acg-cn-beijing.tos-cn-beijing.volces.com/a.png', 'Ark 图片')


class AnalyzeLayoutTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.image = pathlib.Path(self.temp.name) / 'overall.png'
        self.image.write_bytes(b'\x89PNG\r\n')
        self.original = fw_providers._ark_request
        self.calls = []

    def tearDown(self):
        fw_providers._ark_request = self.original
        self.temp.cleanup()

    def _fake(self, content):
        def fake(config, path, payload=None, timeout=60):
            self.calls.append((path, payload))
            return {'choices': [{'message': {'content': content}}]}
        fw_providers._ark_request = fake

    def test_parses_fenced_json_and_sends_image(self):
        self._fake('```json\n{"groundLengthRatio":1.3,"boomLengthRatio":1.6,'
                   '"cabSide":"right","notes":"履带偏长"}\n```')
        hints, meta = fw_providers.analyze_layout(
            ARK_CONFIG, str(self.image), [{'id': 'partModel_body', 'name': '车身'}],
            prompt='车头朝 +X')
        self.assertEqual(hints, {'groundLengthRatio': 1.3, 'boomLengthRatio': 1.6,
                                 'cabSide': 'right'})
        self.assertEqual(meta, {'model': fw_providers.ARK_VISION_MODEL,
                                'notes': '履带偏长'})
        path, payload = self.calls[0]
        self.assertEqual(path, '/chat/completions')
        content = payload['messages'][1]['content']
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))
        self.assertIn('车身', content[0]['text'])

    def test_configured_vision_model_overrides_default(self):
        self._fake('{"cabSide":"left"}')
        config = {'providers': {'ark': {'api_key': 'ark', 'vision_model': 'custom-vision'}}}
        _, meta = fw_providers.analyze_layout(
            config, str(self.image), [{'id': 'partModel_body', 'name': '车身'}])
        self.assertEqual(meta['model'], 'custom-vision')
        self.assertEqual(self.calls[0][1]['model'], 'custom-vision')

    def test_invalid_json_raises(self):
        self._fake('not json')
        with self.assertRaises(RuntimeError):
            fw_providers.analyze_layout(
                ARK_CONFIG, str(self.image), [{'id': 'partModel_body', 'name': '车身'}])

    def test_missing_key_raises_before_request(self):
        with self.assertRaises(ValueError):
            fw_providers.analyze_layout(
                {'providers': {}}, str(self.image), [{'id': 'partModel_body', 'name': '车身'}])


class ArkSpecTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.original = fw_providers._ark_request

    def tearDown(self):
        fw_providers._ark_request = self.original

    def _image(self, directory):
        path = pathlib.Path(directory) / 'overall.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n')
        return str(path)

    def test_parses_fenced_spec_json_and_sends_image(self):
        def fake(config, route, payload=None, timeout=60):
            self.calls.append((route, payload))
            return {'choices': [{'message': {'content':
                '```json\n{"parts":{"bucket":{"sizeM":[1.1,1.2,1.0],'
                '"forward":"+X","confidence":0.7}},"notes":["ok"]}\n```'}}]}

        fw_providers._ark_request = fake
        with tempfile.TemporaryDirectory() as directory:
            raw, meta = fw_providers.analyze_spec(
                ARK_CONFIG, self._image(directory),
                [{'name': '铲斗', 'description': '前端挖斗'}],
                prompt='保持比例', overall_length=7.2, template='excavator')

        self.assertEqual(raw['parts']['bucket']['sizeM'], [1.1, 1.2, 1.0])
        self.assertEqual(meta['model'], fw_providers.ARK_VISION_MODEL)
        self.assertEqual(meta['notes'], 'ok')
        route, payload = self.calls[0]
        self.assertEqual(route, '/chat/completions')
        content = payload['messages'][1]['content']
        self.assertEqual(content[0]['type'], 'text')
        self.assertEqual(content[1]['type'], 'image_url')
        self.assertIn('data:image/png;base64,', content[1]['image_url']['url'])
        self.assertIn('7.200', content[0]['text'])
        self.assertIn('bucket', content[0]['text'])

    def test_invalid_json_raises_runtime_error(self):
        fw_providers._ark_request = lambda *args, **kwargs: {
            'choices': [{'message': {'content': 'not json'}}]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '有效 JSON'):
                fw_providers.analyze_spec(
                    ARK_CONFIG, self._image(directory), [{'name': '车身'}])

    def test_missing_image_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            fw_providers.analyze_spec(
                ARK_CONFIG, 'missing.png', [{'name': '车身'}])

    def test_non_dict_choice_raises_runtime_error_instead_of_attribute_error(self):
        fw_providers._ark_request = lambda *args, **kwargs: {'choices': ['x']}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '有效 JSON'):
                fw_providers.analyze_spec(
                    ARK_CONFIG, self._image(directory), [{'name': '车身'}])

    def test_non_dict_message_raises_runtime_error_instead_of_attribute_error(self):
        fw_providers._ark_request = lambda *args, **kwargs: {
            'choices': [{'message': 'oops'}]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '有效 JSON'):
                fw_providers.analyze_spec(
                    ARK_CONFIG, self._image(directory), [{'name': '车身'}])

    def test_truncated_output_raises_explicit_error(self):
        fw_providers._ark_request = lambda *args, **kwargs: {
            'choices': [{'message': {'content': '{"parts":'}, 'finish_reason': 'length'}]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '截断'):
                fw_providers.analyze_spec(
                    ARK_CONFIG, self._image(directory), [{'name': '车身'}])

    def test_missing_key_raises_before_request(self):
        calls = []

        def fail(*args, **kwargs):
            calls.append(args)
            raise AssertionError('missing key must not trigger a request')
        fw_providers._ark_request = fail
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'API key'):
                fw_providers.analyze_spec(
                    {'providers': {}}, self._image(directory), [{'name': '车身'}])
        self.assertEqual(calls, [])


class AnalyzeDimensionsTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.original = fw_providers._ark_request

    def tearDown(self):
        fw_providers._ark_request = self.original

    def _image(self, directory):
        path = pathlib.Path(directory) / 'wheel.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n')
        return str(path)

    def _fake(self, content):
        def fake(config, route, payload=None, timeout=60):
            self.calls.append((route, payload))
            return {'choices': [{'message': {'content': content}}]}
        return fake

    def test_part_scope_prompt_carries_role_label_and_anchor(self):
        fw_providers._ark_request = self._fake(
            '{"parts":{"wheel":{"sizeM":[4.0,1.7,0.7],"forward":"+X","confidence":0.8}},"notes":["ok"]}')
        with tempfile.TemporaryDirectory() as directory:
            raw, meta = fw_providers.analyze_dimensions(
                ARK_CONFIG, self._image(directory), [], scope='part', role='wheel',
                label='轮组', overall_length=4.2, template='car', prompt='圆轮')
        self.assertEqual(raw['parts']['wheel']['sizeM'], [4.0, 1.7, 0.7])
        self.assertEqual(meta['notes'], 'ok')
        route, payload = self.calls[0]
        self.assertEqual(route, '/chat/completions')
        self.assertEqual(payload['max_tokens'], 600)
        text = payload['messages'][1]['content'][0]['text']
        self.assertIn('轮组', text)
        self.assertIn('wheel', text)
        self.assertIn('4.200', text)
        self.assertIn('car', text)
        self.assertIn('三视图', text)

    def test_part_scope_requires_anchor_before_request(self):
        calls = []

        def fail(*args, **kwargs):
            calls.append(args)
            raise AssertionError('unanchored part analysis must not request')
        fw_providers._ark_request = fail
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'SPEC_UNANCHORED'):
                fw_providers.analyze_dimensions(
                    ARK_CONFIG, self._image(directory), [], scope='part', role='wheel')
        self.assertEqual(calls, [])

    def test_part_scope_requires_role(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
                fw_providers.analyze_dimensions(
                    ARK_CONFIG, self._image(directory), [], scope='part', overall_length=4.2)

    def test_unknown_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_providers.analyze_dimensions(ARK_CONFIG, 'x.png', [], scope='assembly')

    def test_overall_scope_still_lists_parts_and_anchor(self):
        fw_providers._ark_request = self._fake(
            '{"parts":{"bucket":{"sizeM":[1.0,1.0,1.0],"forward":"+X","confidence":0.5}}}')
        with tempfile.TemporaryDirectory() as directory:
            fw_providers.analyze_dimensions(
                ARK_CONFIG, self._image(directory), [{'name': '铲斗'}],
                scope='overall', overall_length=7.2, template='excavator')
        payload = self.calls[0][1]
        self.assertEqual(payload['max_tokens'], 1800)
        text = payload['messages'][1]['content'][0]['text']
        self.assertIn('7.200', text)
        self.assertIn('铲斗', text)


if __name__ == '__main__':
    unittest.main()
