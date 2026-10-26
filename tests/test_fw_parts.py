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
        'layoutVersion': fw_parts.LAYOUT_VERSION,
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


class CoherentLayoutTest(unittest.TestCase):
    def _entries(self):
        return [
            {'id': 'partModel_body', 'name': '车身', 'mesh': 'body.glb',
             'sourceBbox': _bbox([0, -1, 0], [2, 1, 1])},
            {'id': 'partModel_track', 'name': '履带', 'mesh': 'track.glb',
             'sourceBbox': _bbox([0, -1, 0], [3, 1, 0.5])},
            {'id': 'partModel_cab', 'name': '驾驶室', 'mesh': 'cab.glb',
             'sourceBbox': _bbox([0, -0.5, 0], [0.6, 0.5, 0.8])},
            {'id': 'partModel_boom', 'name': '动臂', 'mesh': 'boom.glb',
             'sourceBbox': _bbox([0, -0.2, 0], [2, 0.2, 0.4])},
            {'id': 'partModel_bucket', 'name': '铲斗', 'mesh': 'bucket.glb',
             'sourceBbox': _bbox([0, -0.5, 0], [0.8, 0.5, 0.6])},
        ]

    def test_parts_stack_into_a_machine_instead_of_side_by_side(self):
        entries = self._entries()
        laid_out = {item['id']: item for item in fw_parts.coherent_layout(entries)}
        self.assertEqual([item['id'] for item in fw_parts.coherent_layout(entries)],
                         [entry['id'] for entry in entries])
        track = laid_out['partModel_track']
        body = laid_out['partModel_body']
        cab = laid_out['partModel_cab']
        boom = laid_out['partModel_boom']
        bucket = laid_out['partModel_bucket']
        self.assertAlmostEqual(track['translate'][2], 0.0)
        self.assertAlmostEqual(track['scale'], 0.8)
        self.assertAlmostEqual(body['translate'][2], 0.4)
        self.assertAlmostEqual(cab['translate'][2] + cab['sourceBbox']['min'][2] * cab['scale'], 1.4)
        self.assertAlmostEqual(boom['translate'][0] + boom['sourceBbox']['min'][0] * boom['scale'], 1.0)
        self.assertGreater(boom['translate'][0], body['translate'][0])
        self.assertAlmostEqual(bucket['translate'][0], 3.2)
        self.assertLess(bucket['translate'][0], boom['translate'][0] + 2.0 * boom['scale'])
        # 铲斗安装耳压进动臂末端，而不是让包围盒顶面去顶动臂底沿。
        bucket_height = ((bucket['sourceBbox']['max'][2] - bucket['sourceBbox']['min'][2])
                         * bucket['scale'])
        ear_top = (bucket['translate'][2] + bucket['sourceBbox']['max'][2] * bucket['scale']
                   - bucket_height * fw_parts.BUCKET_EAR_DROP)
        boom_length = (boom['sourceBbox']['max'][0] - boom['sourceBbox']['min'][0]) * boom['scale']
        boom_tip_low = (boom['translate'][2] + boom['sourceBbox']['min'][2] * boom['scale']
                        + boom_length * fw_parts.BOOM_TIP_RISE)
        self.assertGreater(ear_top, boom_tip_low)
        self.assertLess(ear_top, boom_tip_low + bucket_height * 0.1)

    def test_missing_body_or_unknown_roles_fall_back(self):
        entries = self._entries()
        self.assertIsNone(fw_parts.coherent_layout(entries[1:]))
        entries[0]['name'] = entries[0]['id'] = '甲'
        self.assertIsNone(fw_parts.coherent_layout(entries))

    def test_duplicate_ground_roles_fall_back(self):
        entries = self._entries()
        entries.append(dict(entries[1], id='partModel_track_2', name='第二履带'))
        self.assertIsNone(fw_parts.coherent_layout(entries))

    def test_vision_hints_adjust_proportions_and_cab_side(self):
        entries = self._entries()
        base = {item['id']: item for item in fw_parts.coherent_layout(entries)}
        hinted = {item['id']: item for item in fw_parts.coherent_layout(entries, hints={
            'groundLengthRatio': 1.6, 'boomLengthRatio': 1.5,
            'bucketWidthRatio': 0.8, 'cabSide': 'right'})}
        self.assertGreater(hinted['partModel_track']['scale'],
                           base['partModel_track']['scale'])
        self.assertGreater(hinted['partModel_boom']['scale'],
                           base['partModel_boom']['scale'])
        self.assertGreater(hinted['partModel_bucket']['scale'],
                           base['partModel_bucket']['scale'])
        self.assertGreater(base['partModel_cab']['translate'][1], 0)
        self.assertLess(hinted['partModel_cab']['translate'][1], 0)

    def test_layout_hints_are_range_clamped(self):
        hints = fw_parts.normalize_layout_hints({
            'groundLengthRatio': 99, 'boomLengthRatio': 'abc',
            'bucketWidthRatio': 0.01, 'cabSide': 'up'})
        self.assertEqual(hints, {'groundLengthRatio': 2.0, 'bucketWidthRatio': 0.25})


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

    def _assemble(self, parts, reset=False, preserve_absent=False):
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
                asset_id='M1', node_id='assemble_1', preserve_absent=preserve_absent)

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

    def test_decimate_runs_before_coherent_assembly(self):
        shapes = {
            'body': (_bbox([0, -1, 0], [2, 1, 1]), [0, 1, 1, 0]),
            'track': (_bbox([0, -1, 0], [3, 1, 0.5]), [0, 1, 0.5, 0]),
            'cab': (_bbox([0, -0.5, 0], [0.6, 0.5, 0.8]), [0, 0.5, 0.8, 0]),
        }
        for name, (bbox, _values) in shapes.items():
            self.measured[name] = {'min': bbox['min'], 'max': bbox['max'], 'triangles': 500000}
            (self.root / 'outputs' / (name + '.glb')).write_bytes(b'glb')

        def measure(_blender, paths):
            measured = {}
            for path in paths:
                real = os.path.realpath(path)
                stem = Path(path).stem
                role = next((name for name in shapes if 'partModel_' + name in stem), None)
                if role:
                    bbox = shapes[role][0]
                    measured[real] = {'min': bbox['min'], 'max': bbox['max'], 'triangles': 10000}
                else:
                    item = self.measured[stem]
                    measured[real] = {'min': item['min'], 'max': item['max'],
                                      'triangles': item['triangles']}
            return measured

        def run(_blender, arguments, _label):
            if arguments[1] == 'decimate':
                Path(arguments[arguments.index('--output') + 1]).write_bytes(b'glb')
                return {'valid': True, 'trianglesBefore': 500000, 'trianglesAfter': 10000}
            with open(arguments[arguments.index('--plan') + 1], encoding='utf-8') as stream:
                self.plan = json.load(stream)
            return {'valid': True, 'parts': [
                {'id': item['id'], 'name': item['name'],
                 'min': [0, 0, 0], 'max': [1, 1, 1], 'triangles': 10000}
                for item in self.plan['parts']]}

        with mock.patch.object(fw_parts, 'measure_parts', side_effect=measure), \
                mock.patch.object(fw_parts, '_run_blender', side_effect=run):
            result = fw_parts.assemble_parts(
                self._parts('body', 'track', 'cab'), str(self.output_path),
                str(self.layout_path), str(self.root), blender_path='blender',
                decimate_faces=10000, layout_mode='coherent')

        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertEqual(layout['layoutMode'], 'coherent')
        self.assertEqual(layout['decimateFaces'], 10000)
        self.assertEqual([part['sourceMesh'] for part in layout['parts']],
                         ['outputs/body.glb', 'outputs/track.glb', 'outputs/cab.glb'])
        for part in layout['parts']:
            self.assertTrue(part['mesh'].startswith('parts/decimated/'))
            self.assertIn('partModel_', part['mesh'])
        self.assertEqual(len(result['decimated']), 3)
        self.assertEqual(result['trianglesBefore'], 1500000)
        self.assertEqual(result['triangles'], 30000)
        self.assertEqual(result['layoutMode'], 'coherent')
        self.assertTrue(any('减面' in warning for warning in result['warnings']))
        self.assertEqual([part['mesh'] for part in self.plan['parts']],
                         [os.path.realpath(os.path.join(str(self.root), part['mesh']))
                          for part in layout['parts']])

    def test_coherent_plan_snaps_bucket_to_boom(self):
        self.measured.update({
            'body': {'min': [0, -1, 0], 'max': [2, 1, 1], 'triangles': 10},
            'track': {'min': [0, -1, 0], 'max': [3, 1, 0.5], 'triangles': 10},
            'boom': {'min': [0, -0.2, 0], 'max': [3, 0.2, 1], 'triangles': 10},
            'bucket': {'min': [0, -0.5, 0], 'max': [1, 0.5, 1], 'triangles': 10},
        })
        for name in ('body', 'track', 'boom', 'bucket'):
            (self.root / 'outputs' / (name + '.glb')).write_bytes(b'glb')

        self._assemble(self._parts('body', 'track', 'boom', 'bucket'))

        self.assertEqual(self.plan['snaps'],
                         [{'part': 'partModel_bucket', 'to': 'partModel_boom'}])

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

    def test_preserve_absent_keeps_skipped_part_layout(self):
        self._assemble(self._parts('a', 'b'))
        result = self._assemble(self._parts('a'), preserve_absent=True)
        layout = fw_parts.load_layout(str(self.layout_path))
        self.assertEqual([part['mesh'] for part in layout['parts']],
                         ['outputs/a.glb', 'outputs/b.glb'])
        self.assertEqual([part['id'] for part in self.plan['parts']], ['partModel_a'])
        self.assertTrue(any('保留' in warning for warning in result['warnings']))
        self.assertFalse(any('已不再接入' in warning for warning in result['warnings']))

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

    def test_outdated_layout_rules_are_regenerated(self):
        existing = fw_parts.normalize_layout(_layout())
        existing['layoutVersion'] = fw_parts.LAYOUT_VERSION - 1
        existing['parts'][0].update({'scale': 2.0, 'translate': [5, 6, 7]})
        fw_parts.save_layout(str(self.layout_path), existing)
        result = self._assemble(self._parts('a'))
        self.assertEqual(self.plan['parts'][0]['scale'], 1.0)
        self.assertEqual(self.plan['parts'][0]['translate'], [0.0, 0.0, 0.0])
        self.assertTrue(any('旧版摆放规则' in warning for warning in result['warnings']))

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
