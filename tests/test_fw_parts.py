import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_parts


def _bbox(low, high):
    return {'min': list(low), 'max': list(high)}


def _layout():
    return {
        'schemaVersion': 1,
        'assetId': 'M1',
        'nodeId': 'assemble_1',
        'assemblyPrompt': '车身居中',
        'parts': [{
            'id': 'partModel_1', 'name': '车身', 'mesh': 'outputs/a.glb',
            'description': '外壳', 'sourceBbox': _bbox([0, -1, 0], [2, 1, 1]),
        }],
    }


class LayoutValidationTest(unittest.TestCase):
    def test_valid_layout_fills_defaults(self):
        layout = fw_parts.normalize_layout(_layout())
        part = layout['parts'][0]
        self.assertEqual(part['scale'], 1.0)
        self.assertEqual(part['translate'], [0.0, 0.0, 0.0])
        self.assertEqual(part['rotationZ'], 0.0)
        self.assertTrue(part['ground'])
        self.assertEqual(layout['assemblyPrompt'], '车身居中')

    def test_flat_part_allowed(self):
        data = _layout()
        data['parts'][0]['sourceBbox'] = _bbox([0, 0, 0], [2, 2, 0])
        fw_parts.normalize_layout(data)

    def test_degenerate_bbox_rejected(self):
        data = _layout()
        data['parts'][0]['sourceBbox'] = _bbox([1, 1, 1], [1, 1, 1])
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_schema_version_rejected(self):
        data = _layout()
        data['schemaVersion'] = 2
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_absolute_mesh_rejected(self):
        data = _layout()
        data['parts'][0]['mesh'] = '/tmp/a.glb'
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_mesh_traversal_rejected(self):
        data = _layout()
        data['parts'][0]['mesh'] = '../a.glb'
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_duplicate_mesh_rejected(self):
        data = _layout()
        data['parts'].append(dict(data['parts'][0], id='partModel_2'))
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_non_positive_scale_rejected(self):
        data = _layout()
        data['parts'][0]['scale'] = 0
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_non_boolean_ground_rejected(self):
        data = _layout()
        data['parts'][0]['ground'] = 'yes'
        with self.assertRaises(ValueError):
            fw_parts.normalize_layout(data)

    def test_load_missing_layout_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(fw_parts.load_layout(os.path.join(temp, 'none.json')))

    def test_load_malformed_layout_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, 'layout.json')
            Path(path).write_text('{not json', encoding='utf-8')
            with self.assertRaises(ValueError):
                fw_parts.load_layout(path)

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, 'nested', 'layout.json')
            layout = fw_parts.normalize_layout(_layout())
            fw_parts.save_layout(path, layout)
            self.assertEqual(fw_parts.load_layout(path), layout)


class ResolveMeshTest(unittest.TestCase):
    def test_relative_mesh_resolves_inside_root(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'outputs' / 'a.glb'
            target.parent.mkdir()
            target.write_bytes(b'glb')
            self.assertEqual(fw_parts.resolve_layout_mesh(temp, 'outputs/a.glb'),
                             os.path.realpath(target))

    def test_absolute_mesh_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                fw_parts.resolve_layout_mesh(temp, '/tmp/a.glb')

    def test_missing_mesh_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                fw_parts.resolve_layout_mesh(temp, 'outputs/missing.glb')

    def test_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                fw_parts.resolve_layout_mesh(temp, '../a.glb')


class AutoLayoutTest(unittest.TestCase):
    def test_parts_line_up_with_gap_and_ground(self):
        entries = [
            {'id': 'a', 'name': 'A', 'mesh': 'a.glb',
             'sourceBbox': _bbox([0, -1, 0], [2, 1, 1])},
            {'id': 'b', 'name': 'B', 'mesh': 'b.glb',
             'sourceBbox': _bbox([-1, -1, 0.5], [1, 1, 3])},
        ]
        laid_out = fw_parts.auto_layout(entries, gap=0.02)
        self.assertEqual(laid_out[0]['translate'], [0.0, 0.0, 0.0])
        self.assertAlmostEqual(laid_out[1]['translate'][0], 3.02)
        self.assertAlmostEqual(laid_out[1]['translate'][1], 0.0)
        self.assertAlmostEqual(laid_out[1]['translate'][2], -0.5)
        for item in laid_out:
            self.assertEqual(item['scale'], 1.0)
            self.assertEqual(item['rotationZ'], 0.0)
            self.assertTrue(item['ground'])

    def test_missing_bbox_rejected(self):
        with self.assertRaises(ValueError):
            fw_parts.auto_layout([{'id': 'a', 'mesh': 'a.glb'}])

    def test_invalid_bbox_rejected(self):
        with self.assertRaises(ValueError):
            fw_parts.auto_layout([{'id': 'a', 'mesh': 'a.glb',
                                   'sourceBbox': _bbox([0, 0, 0], [0, 0, 0])}])


class AssemblePartsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'outputs').mkdir()
        self.measured = {
            'a': {'min': [0, -1, 0], 'max': [2, 1, 1], 'triangles': 10},
            'b': {'min': [-1, -1, 0.5], 'max': [1, 1, 3], 'triangles': 20},
        }
        for name in self.measured:
            (self.root / 'outputs' / (name + '.glb')).write_bytes(b'glb')
        self.layout_path = self.root / 'parts' / 'layout_assemble_1.json'
        self.output_path = self.root / 'outputs' / 'model_assembly_assemble_1.glb'
        self.plan = None

    def tearDown(self):
        self.temp.cleanup()

    def _parts(self, *names):
        return [{'id': 'partModel_' + name, 'name': name.upper(),
                 'mesh': 'outputs/%s.glb' % name} for name in names]

    def _assemble(self, parts, reset=False):
        def measure(_blender, paths):
            return {os.path.realpath(path): dict(self.measured[Path(path).stem]) for path in paths}

        def run(_blender, arguments, _label):
            with open(arguments[arguments.index('--plan') + 1], encoding='utf-8') as stream:
                self.plan = json.load(stream)
            return {'valid': True, 'parts': [
                {'id': item['id'], 'name': item['name'],
                 'min': [0, 0, 0], 'max': [1, 1, 1], 'triangles': 10}
                for item in self.plan['parts']]}

        with mock.patch.object(fw_parts, 'measure_parts', side_effect=measure), \
                mock.patch.object(fw_parts, '_run_blender', side_effect=run):
            return fw_parts.assemble_parts(
                parts, str(self.output_path), str(self.layout_path), str(self.root),
                assembly_prompt='车身居中', reset=reset, blender_path='blender',
                asset_id='M1', node_id='assemble_1')

    def test_new_layout_is_generated_and_saved(self):
        result = self._assemble(self._parts('a', 'b'))
        self.assertEqual(result['meshPath'], 'model_assembly_assemble_1.glb')
        self.assertEqual(result['triangles'], 20)
        self.assertEqual(result['engine'], 'blender')
        self.assertTrue(result['warnings'])
        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertEqual([part['id'] for part in layout['parts']], ['partModel_a', 'partModel_b'])
        self.assertEqual(layout['assemblyPrompt'], '车身居中')
        self.assertEqual(layout['nodeId'], 'assemble_1')
        self.assertAlmostEqual(layout['parts'][1]['translate'][0], 3.02)
        self.assertEqual(self.plan['parts'][1]['translate'][2], -0.5)
        self.assertTrue(os.path.isfile(str(self.output_path)[:-4] + '.report.json'))

    def test_existing_transforms_are_preserved(self):
        existing = fw_parts.normalize_layout(_layout())
        existing['parts'][0].update({'scale': 2.0, 'translate': [5, 6, 7],
                                     'rotationZ': 90, 'ground': False})
        fw_parts.save_layout(str(self.layout_path), existing)
        result = self._assemble(self._parts('a'))
        plan_part = self.plan['parts'][0]
        self.assertEqual(plan_part['scale'], 2.0)
        self.assertEqual(plan_part['translate'], [5.0, 6.0, 7.0])
        self.assertEqual(plan_part['rotationZ'], 90.0)
        self.assertFalse(any('自动' in warning for warning in result['warnings']))

    def test_edited_name_survives_reassembly(self):
        existing = fw_parts.normalize_layout(_layout())
        existing['parts'][0]['name'] = '自定义车身'
        fw_parts.save_layout(str(self.layout_path), existing)
        self._assemble(self._parts('a'))
        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertEqual(layout['parts'][0]['name'], '自定义车身')

    def test_ground_recomputes_height_after_scale_change(self):
        existing = fw_parts.normalize_layout(_layout())
        existing['parts'][0]['mesh'] = 'outputs/b.glb'
        existing['parts'][0].update({'scale': 2.0, 'translate': [0, 0, 9], 'ground': True})
        fw_parts.save_layout(str(self.layout_path), existing)
        self._assemble(self._parts('b'))
        self.assertAlmostEqual(self.plan['parts'][0]['translate'][2], -1.0)
        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertAlmostEqual(layout['parts'][0]['translate'][2], -1.0)

    def test_removed_part_is_dropped(self):
        self._assemble(self._parts('a', 'b'))
        result = self._assemble(self._parts('a'))
        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertEqual([part['mesh'] for part in layout['parts']], ['outputs/a.glb'])
        self.assertTrue(any('已不再接入' in warning for warning in result['warnings']))

    def test_new_part_is_appended(self):
        self._assemble(self._parts('a'))
        result = self._assemble(self._parts('a', 'b'))
        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertEqual(len(layout['parts']), 2)
        self.assertAlmostEqual(layout['parts'][1]['translate'][0], 3.02)
        self.assertTrue(any('自动补位' in warning for warning in result['warnings']))

    def test_reset_discards_existing_layout(self):
        existing = fw_parts.normalize_layout(_layout())
        existing['parts'][0].update({'scale': 2.0, 'translate': [5, 6, 7]})
        fw_parts.save_layout(str(self.layout_path), existing)
        self._assemble(self._parts('a'), reset=True)
        self.assertEqual(self.plan['parts'][0]['scale'], 1.0)
        self.assertEqual(self.plan['parts'][0]['translate'], [0.0, 0.0, 0.0])

    def test_duplicate_mesh_rejected(self):
        parts = self._parts('a')
        with self.assertRaises(ValueError):
            self._assemble(parts + parts)

    def test_mesh_outside_root_rejected(self):
        with self.assertRaises(ValueError):
            self._assemble([{'id': 'x', 'mesh': '../a.glb'}])

    def test_empty_parts_rejected(self):
        with self.assertRaises(ValueError):
            self._assemble([])

    def test_missing_blender_rejected(self):
        with mock.patch.object(fw_parts, 'find_blender', return_value=None):
            with self.assertRaises(ValueError):
                fw_parts.assemble_parts(self._parts('a'), str(self.output_path),
                                        str(self.layout_path), str(self.root))


if __name__ == '__main__':
    unittest.main()
