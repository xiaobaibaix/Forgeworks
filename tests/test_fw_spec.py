import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_spec


class SpecValidationTest(unittest.TestCase):
    def test_excavator_template_is_valid(self):
        spec = fw_spec.template_spec('MC_EXCAVATOR')
        validated = fw_spec.validate_spec(spec)
        self.assertEqual(validated['schemaVersion'], 1)
        self.assertEqual(validated['units'], 'm')
        self.assertEqual(validated['assembly']['rootRole'], 'body')
        for role in ('body', 'track', 'boom', 'bucket', 'cab'):
            self.assertIn(role, validated['parts'])
            self.assertEqual(len(validated['parts'][role]['sizeM']), 3)

    def test_car_template_is_valid(self):
        spec = fw_spec.template_spec('MC_CAR', template='car')
        self.assertEqual(spec['assembly']['rootRole'], 'body')
        self.assertEqual(set(spec['parts']), {'body', 'roof', 'wheel'})
        self.assertAlmostEqual(spec['overall']['lengthM'], 4.2)
        self.assertAlmostEqual(spec['parts']['body']['sizeM'][2], 0.7)
        ports = {connection['id'] for connection in spec['connections']}
        self.assertEqual(ports, {'c_roof_body', 'c_wheel_body_front', 'c_wheel_body_rear'})

    def test_unknown_template_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SPEC_UNANCHORED'):
            fw_spec.template_spec('M1', template='spaceship')
        with self.assertRaisesRegex(ValueError, 'SPEC_UNANCHORED'):
            fw_spec.from_vision({'parts': {}}, template='spaceship')

    def test_from_vision_accepts_car_template(self):
        raw = {
            'overall': {'lengthM': 4.2},
            'parts': {
                'roof': {'sizeM': [2.4, 1.4, 0.2], 'confidence': 0.8},
                'boom': {'sizeM': [1.0, 1.0, 1.0]},
            },
            'connections': [],
        }
        spec = fw_spec.from_vision(raw, overall_length_m=4.2, template='car',
                                   asset_id='MC_CAR')
        self.assertEqual(set(spec['parts']), {'body', 'roof', 'wheel'})
        self.assertNotIn('boom', spec['parts'])
        self.assertAlmostEqual(spec['parts']['roof']['sizeM'][0], 2.4)
        self.assertAlmostEqual(spec['parts']['body']['sizeM'][0], 4.2)

    def test_missing_overall_is_rejected(self):
        spec = fw_spec.template_spec('M1')
        del spec['overall']
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_negative_part_size_is_rejected(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['parts']['body']['sizeM'][0] = -1
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_unknown_connection_port_is_rejected(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['connections'][0]['a'] = 'bucket:no_such_port'
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_duplicate_port_connection_warns_and_is_skipped(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        duplicate = copy.deepcopy(spec['connections'][0])
        duplicate['id'] = 'c_duplicate'
        spec['connections'].append(duplicate)
        warnings = []
        validated = fw_spec.validate_spec(spec, warnings)
        self.assertEqual([item['id'] for item in validated['connections']].count('c_duplicate'), 0)
        self.assertTrue(any('重复' in warning for warning in warnings))

    def test_from_vision_uses_template_for_missing_parts_and_scales_to_anchor(self):
        raw = {
            'overall': {'lengthM': 7.2},
            'parts': {'bucket': {'sizeM': [1.0, 1.0, 1.0], 'confidence': 0.8}},
            'connections': [],
        }
        spec = fw_spec.from_vision(raw, overall_length_m=14.4, asset_id='M1')
        self.assertEqual(spec['overall']['source'], 'user')
        self.assertAlmostEqual(spec['overall']['lengthM'], 14.4)
        self.assertIn('body', spec['parts'])
        self.assertAlmostEqual(spec['parts']['body']['sizeM'][0], 8.4)
        self.assertAlmostEqual(spec['parts']['bucket']['sizeM'][0], 2.0)
        self.assertAlmostEqual(spec['parts']['bucket']['ports'][0]['radiusM'], 0.12)
        self.assertEqual(spec['connections'][0]['id'], 'c_bucket_boom')

    def test_from_vision_uses_model_overall_as_scale_base(self):
        raw = {
            'overall': {'lengthM': 14.4, 'widthM': 4.8, 'heightM': 6.2},
            'parts': {'bucket': {'sizeM': [2.3, 2.4, 2.1]}},
            'connections': [],
        }
        spec = fw_spec.from_vision(raw, overall_length_m=14.4, asset_id='M1')
        self.assertAlmostEqual(spec['overall']['lengthM'], 14.4)
        self.assertAlmostEqual(spec['overall']['widthM'], 4.8)
        self.assertAlmostEqual(spec['overall']['heightM'], 6.2)
        self.assertAlmostEqual(spec['parts']['bucket']['sizeM'][0], 2.3)
        self.assertAlmostEqual(spec['parts']['body']['sizeM'][0], 8.4)

    def test_from_vision_without_anchor_normalizes_model_sizes_to_template(self):
        raw = {
            'overall': {'lengthM': 14.4},
            'parts': {'bucket': {'sizeM': [2.0, 2.0, 2.0]}},
            'connections': [],
        }
        spec = fw_spec.from_vision(raw, asset_id='M1')
        self.assertEqual(spec['overall']['source'], 'template')
        self.assertAlmostEqual(spec['overall']['lengthM'], 7.2)
        self.assertAlmostEqual(spec['parts']['bucket']['sizeM'][0], 1.0)
        self.assertAlmostEqual(spec['parts']['body']['sizeM'][0], 4.2)

    def test_non_finite_numbers_are_rejected(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['overall']['lengthM'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['parts']['body']['sizeM'][0] = float('inf')
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_read_write_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pipeline' / 'spec.json'
            original = fw_spec.template_spec('M1')
            fw_spec.write_spec(str(path), original)
            self.assertTrue(path.is_file())
            self.assertEqual(fw_spec.read_spec(str(path))['assetId'], 'M1')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['units'], 'm')

    def test_read_spec_missing_file_raises_spec_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'no_such_spec.json'
            with self.assertRaisesRegex(ValueError, '^SPEC_MISSING'):
                fw_spec.read_spec(str(path))

    def test_read_spec_wraps_broken_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spec.json'
            path.write_text('{not json', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '^SPEC_INVALID'):
                fw_spec.read_spec(str(path))

    def test_role_for_node_handles_prefixes_and_chinese_names(self):
        self.assertEqual(fw_spec.role_for_node('partModel_body'), 'body')
        self.assertEqual(fw_spec.role_for_node('partImage_side_window', '侧窗'), 'window')
        self.assertEqual(fw_spec.role_for_node('partModel_boom', '动臂'), 'boom')
        self.assertEqual(fw_spec.role_for_node('mystery'), '')

    def test_anchor_ports_keep_anchor_but_have_no_metric_pos(self):
        part = fw_spec.template_spec('M1')['parts']['bucket']
        ports = fw_spec.anchor_ports(part)
        self.assertEqual(ports[0]['id'], 'ear_pin')
        self.assertEqual(ports[0]['anchorNorm'], [0.02, 0.5, 0.78])
        self.assertNotIn('pos', ports[0])


class FitMathTest(unittest.TestCase):
    def test_twenty_four_proper_rotations_without_mirrors(self):
        candidates = fw_spec.orientation_candidates()
        self.assertEqual(len(candidates), 24)
        self.assertTrue(all(item['det'] == 1 for item in candidates))
        self.assertEqual(len({tuple(map(tuple, item['matrix'])) for item in candidates}), 24)

    def test_uniform_scale_matches_known_box(self):
        fit = fw_spec.choose_orientation([2, 1, 0.5], [4, 2, 1], '+X', 'uniform')
        self.assertAlmostEqual(fit['scale'], 2.0, places=9)
        self.assertAlmostEqual(fit['aspectError'], 0.0, places=9)
        self.assertEqual([round(value) for value in fit['rotationDeg']], [0, 0, 0])

    def test_axis_swap_chooses_quarter_turn(self):
        fit = fw_spec.choose_orientation([2, 1, 1], [1, 2, 1], '+X', 'uniform')
        self.assertAlmostEqual(fit['scale'], 1.0, places=9)
        self.assertAlmostEqual(fit['aspectError'], 0.0, places=9)
        self.assertEqual(abs(round(fit['rotationDeg'][2])), 90)

    def test_uniform_cube_is_not_ambiguous(self):
        fit = fw_spec.choose_orientation([1, 1, 1], [1, 1, 1], '+X', 'uniform')
        self.assertIs(fit['ambiguous'], False)

    def test_near_equal_size_allocations_are_ambiguous(self):
        # 两个尺寸分配分差约 0.005，低于 ORIENTATION_AMBIGUITY。
        fit = fw_spec.choose_orientation([2, 1, 0.995], [2, 0.995, 1], '+X', 'uniform')
        self.assertIs(fit['ambiguous'], True)

    def test_clear_axis_mapping_is_not_ambiguous(self):
        fit = fw_spec.choose_orientation([2, 1, 0.5], [4, 2, 1], '+X', 'uniform')
        self.assertIs(fit['ambiguous'], False)
        self.assertEqual([round(value) for value in fit['rotationDeg']], [0, 0, 0])

    def test_per_axis_scale_is_exact(self):
        # 目标 [4,2,1] 让恒等朝向成为首个最优解，缩放后每一轴都应精确命中。
        fit = fw_spec.choose_orientation([2, 1, 1], [4, 2, 1], '+X', 'perAxis')
        self.assertEqual(len(fit['scalePerAxis']), 3)
        self.assertAlmostEqual(fit['scalePerAxis'][0] * 2, 4, places=6)
        self.assertAlmostEqual(fit['scalePerAxis'][1] * 1, 2, places=6)
        self.assertAlmostEqual(fit['scalePerAxis'][2] * 1, 1, places=6)

    def test_center_anchor_resolves_to_bbox_center(self):
        ports = fw_spec.resolve_ports(
            [{'id': 'p', 'anchor': [0.5, 0.5, 0.5], 'axis': [1, 0, 0],
              'normal': [0, 0, 1], 'radiusM': 0.1}],
            {'min': [-1, -2, -3], 'max': [1, 2, 3]})
        self.assertEqual(ports[0]['pos'], [0.0, 0.0, 0.0])
        self.assertEqual(ports[0]['axis'], [1.0, 0.0, 0.0])

    def test_non_finite_measured_or_target_is_rejected(self):
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
                fw_spec.choose_orientation([bad, 1, 1], [2, 1, 1], '+X', 'uniform')
            with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
                fw_spec.choose_orientation([2, 1, 1], [bad, 1, 1], '+X', 'uniform')

    def test_rotated_port_axis_uses_same_matrix(self):
        fit = fw_spec.choose_orientation([2, 1, 1], [1, 2, 1], '+X', 'uniform')
        ports = fw_spec.resolve_ports(
            [{'id': 'p', 'anchor': [0.5, 0.5, 0.5], 'axis': [1, 0, 0],
              'normal': [0, 0, 1], 'radiusM': 0.1}],
            {'min': [-1, -1, -1], 'max': [1, 1, 1]}, fit['matrix'])
        self.assertAlmostEqual(abs(ports[0]['axis'][1]), 1.0, places=9)


class MateTreeTest(unittest.TestCase):
    def test_excavator_tree_is_postorder_binary_chain(self):
        tree = fw_spec.build_mate_tree(fw_spec.template_spec('M1'))
        self.assertEqual([node['id'] for node in tree['nodes']][:2],
                         ['mate_boom_bucket', 'mate_body_boom'])
        self.assertEqual(tree['nodes'][0]['connection'], 'c_bucket_boom')
        self.assertEqual(tree['warnings'], [])

    def test_cycle_produces_warning_not_exception(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['parts']['body']['ports'].append(
            {'id': 'loop', 'type': 'pin', 'anchor': [0.5, 0.5, 0.5],
             'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.05})
        spec['parts']['bucket']['ports'].append(
            {'id': 'loop', 'type': 'pin', 'anchor': [0.5, 0.5, 0.5],
             'axis': [-1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.05})
        spec['connections'].append(
            {'id': 'c_loop', 'a': 'body:loop', 'b': 'bucket:loop', 'joint': 'pin'})
        tree = fw_spec.build_mate_tree(spec)
        self.assertTrue(any('环' in warning for warning in tree['warnings']))

    def test_duplicate_port_connection_warning_is_kept(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        duplicate = copy.deepcopy(spec['connections'][0])
        duplicate['id'] = 'c_duplicate'
        spec['connections'].append(duplicate)
        tree = fw_spec.build_mate_tree(spec)
        self.assertTrue(any('重复' in warning for warning in tree['warnings']))


if __name__ == '__main__':
    unittest.main()
