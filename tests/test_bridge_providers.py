import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
_argv = sys.argv
sys.argv = [_argv[0]]
import bridge
sys.argv = _argv


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


if __name__ == '__main__':
    unittest.main()
