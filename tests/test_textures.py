import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location('fw_textures', ROOT / 'tools' / 'fw_textures.py')
fw_textures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fw_textures)


class FakeProviders:
    def __init__(self, poll_state='success', image=b'\x89PNG-fake'):
        self.poll_state = poll_state
        self.image = image
        self.submitted = []
        self.ids = {}

    def submit(self, config, kind, options, prompt):
        self.assert_kind = kind
        task_id = 'task-%d' % (len(self.submitted) + 1)
        self.submitted.append({'kind': kind, 'options': options, 'prompt': prompt})
        return {'taskId': task_id, 'provider': 'tripo'}

    def poll(self, config, task_id):
        return {'status': self.poll_state, 'progress': 100, 'output': {}}

    def download_image(self, url):
        return self.image, 'png'


class TextureCatalogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_catalog_is_empty_when_missing(self):
        catalog = fw_textures.load_catalog(str(self.root), 'industrial')
        self.assertEqual(catalog['items'], {})
        self.assertEqual(catalog['styleId'], 'industrial')

    def test_catalog_drops_unknown_keys_and_missing_files(self):
        directory = self.root / '_Source' / 'Materials' / 'industrial'
        directory.mkdir(parents=True)
        (directory / 'textures.json').write_text(json.dumps({'items': {
            'steel': {'state': 'ready', 'file': 'gone.png'},
            'bogus': {'state': 'ready', 'file': 'bogus.png'},
        }}), encoding='utf-8')

        catalog = fw_textures.load_catalog(str(self.root), 'industrial')

        self.assertNotIn('bogus', catalog['items'])
        self.assertEqual(catalog['items']['steel']['state'], 'missing')
        self.assertIsNone(catalog['items']['steel']['file'])

    def test_ids_reject_traversal(self):
        for value in ('../etc', 'a/b', '', 'x' * 65):
            with self.assertRaises(ValueError):
                fw_textures.style_id(value)
        with self.assertRaises(ValueError):
            fw_textures.asset_key('../steel')

    def test_prompt_includes_style_hint_and_caps_length(self):
        prompt = fw_textures.build_prompt('steel', '黄铜蒸汽朋克，暗色金属')
        self.assertIn('黄铜蒸汽朋克', prompt)
        self.assertIn('rolled steel plate', prompt)
        self.assertIn('neutral grey', prompt)
        self.assertLessEqual(len(prompt), 1200)


class TextureJobTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.providers = FakeProviders()

    def tearDown(self):
        self._tmp.cleanup()

    def submit(self, keys, force=False):
        return fw_textures.submit_many(
            self.providers, {}, str(self.root), 'industrial', keys,
            style_hint='工厂', size='1K', force=force)

    def test_submit_records_queued_items(self):
        result = self.submit(['steel', 'glass'])

        self.assertEqual(result['submitted'], ['steel', 'glass'])
        self.assertEqual(len(self.providers.submitted), 2)
        catalog = fw_textures.load_catalog(str(self.root), 'industrial')
        self.assertEqual(catalog['items']['steel']['state'], 'queued')
        self.assertEqual(catalog['items']['steel']['taskId'], 'task-1')
        self.assertTrue((self.root / '_Source' / 'Materials' / 'industrial' / 'textures.json').is_file())

    def test_submit_skips_ready_and_inflight(self):
        self.submit(['steel'])
        second = self.submit(['steel'])
        self.assertEqual(second['submitted'], [])
        self.assertEqual(second['skipped'][0]['reason'], '任务进行中')

        catalog = fw_textures.load_catalog(str(self.root), 'industrial')
        catalog['items']['steel'].update(state='ready', file='steel.png')
        directory = self.root / '_Source' / 'Materials' / 'industrial'
        (directory / 'steel.png').write_bytes(b'png')
        fw_textures.save_catalog(str(self.root), 'industrial', catalog)

        third = self.submit(['steel'])
        self.assertEqual(third['skipped'][0]['reason'], '已生成')
        forced = self.submit(['steel'], force=True)
        self.assertEqual(forced['submitted'], ['steel'])

    def test_poll_success_downloads_file(self):
        self.submit(['steel'])
        catalog, item = fw_textures.poll_one(
            self.providers, {}, str(self.root), 'industrial', 'steel')

        directory = self.root / '_Source' / 'Materials' / 'industrial'
        self.assertEqual(item['state'], 'ready')
        self.assertEqual(item['file'], 'steel.png')
        self.assertEqual((directory / 'steel.png').read_bytes(), b'\x89PNG-fake')
        self.assertEqual(item['sha1'], hashlib.sha1(b'\x89PNG-fake').hexdigest())
        self.assertEqual(catalog['items']['steel']['state'], 'ready')

    def test_poll_failure_marks_item(self):
        self.providers.poll_state = 'failed'
        self.submit(['steel'])
        _, item = fw_textures.poll_one(
            self.providers, {}, str(self.root), 'industrial', 'steel')
        self.assertEqual(item['state'], 'failed')
        self.assertTrue(item['error'])

    def test_texture_file_requires_ready_item(self):
        with self.assertRaises(ValueError):
            fw_textures.texture_file(str(self.root), 'industrial', 'steel')

        self.submit(['steel'])
        fw_textures.poll_one(self.providers, {}, str(self.root), 'industrial', 'steel')
        path, content_type = fw_textures.texture_file(str(self.root), 'industrial', 'steel')
        self.assertEqual(pathlib.Path(path).name, 'steel.png')
        self.assertEqual(content_type, 'image/png')


if __name__ == '__main__':
    unittest.main()
