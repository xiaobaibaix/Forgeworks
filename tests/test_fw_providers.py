import importlib.util
import pathlib
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


if __name__ == '__main__':
    unittest.main()
