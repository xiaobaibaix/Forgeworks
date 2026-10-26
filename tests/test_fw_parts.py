import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_parts


def _contract(overrides=None):
    data = {
        'schemaVersion': 1,
        'assetId': 'M1',
        'views': {
            'front': {'width': 1000, 'height': 1000, 'ground': 900, 'pxPerMeter': 100},
            'side': {'width': 1000, 'height': 1000, 'ground': 900, 'pxPerMeter': 100},
        },
        'parts': [{
            'id': 'body', 'name': '机身', 'mesh': 'parts/body.glb',
            'front': [400, 300, 200, 500], 'side': [300, 340, 400, 500],
        }],
    }
    for key, value in (overrides or {}).items():
        data[key] = value
    return data


class ContractValidationTest(unittest.TestCase):
    def test_valid_contract_fills_defaults(self):
        contract = fw_parts.normalize_contract(_contract())
        part = contract['parts'][0]
        self.assertEqual(part['fit'], 'contain')
        self.assertAlmostEqual(part['overlap'], fw_parts.DEFAULT_OVERLAP)
        self.assertEqual(part['rotationZ'], 0)
        self.assertIsNone(part['scale'])
        self.assertFalse(contract['views']['side']['flipX'])

    def test_missing_side_view_rejected(self):
        data = _contract()
        data['views'].pop('side')
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)

    def test_schema_version_rejected(self):
        data = _contract()
        data['schemaVersion'] = 2
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)

    def test_mesh_path_cannot_escape_contract_dir(self):
        data = _contract()
        data['parts'][0]['mesh'] = '../outside.glb'
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)

    def test_duplicate_part_id_rejected(self):
        data = _contract()
        data['parts'].append(dict(data['parts'][0]))
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)

    def test_box_must_have_positive_size(self):
        data = _contract()
        data['parts'][0]['front'] = [400, 300, 0, 500]
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)

    def test_overlap_out_of_range_rejected(self):
        data = _contract()
        data['parts'][0]['overlap'] = 0.9
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)

    def test_ground_must_stay_inside_image(self):
        data = _contract()
        data['views']['front']['ground'] = 1200
        with self.assertRaises(ValueError):
            fw_parts.normalize_contract(data)


class ViewMappingTest(unittest.TestCase):
    def test_front_box_maps_to_world_x_and_z(self):
        view = fw_parts.normalize_contract(_contract())['views']['front']
        (left, right), (bottom, top) = fw_parts.view_world_range(view, [400, 300, 200, 500])
        self.assertAlmostEqual(left, -1.0)
        self.assertAlmostEqual(right, 1.0)
        self.assertAlmostEqual(bottom, 1.0)
        self.assertAlmostEqual(top, 6.0)

    def test_flip_x_mirrors_side_view(self):
        contract = fw_parts.normalize_contract(_contract())
        view = dict(contract['views']['side'], flipX=True)
        (left, right), _ = fw_parts.view_world_range(view, [100, 300, 200, 500])
        self.assertAlmostEqual(left, 2.0)
        self.assertAlmostEqual(right, 4.0)

    def test_target_box_takes_depth_from_side_view(self):
        contract = fw_parts.normalize_contract(_contract())
        box, warnings = fw_parts.target_box(contract['views'], contract['parts'][0])
        self.assertEqual(warnings, [])
        self.assertAlmostEqual(box['min'][0], -1.0)
        self.assertAlmostEqual(box['max'][0], 1.0)
        self.assertAlmostEqual(box['min'][1], -2.0)
        self.assertAlmostEqual(box['max'][1], 2.0)
        self.assertAlmostEqual(box['min'][2], 1.0)
        self.assertAlmostEqual(box['max'][2], 6.0)

    def test_height_mismatch_produces_warning(self):
        contract = fw_parts.normalize_contract(_contract())
        contract['parts'][0]['side'] = [300, 400, 400, 400]
        _, warnings = fw_parts.target_box(contract['views'], contract['parts'][0])
        self.assertTrue(warnings)


class PlanPartTest(unittest.TestCase):
    def _part(self, **overrides):
        part = {'id': 'body', 'name': '机身', 'mesh': 'body.glb',
                'fit': 'contain', 'overlap': 0, 'rotationZ': 0, 'scale': None}
        part.update(overrides)
        return part

    def test_contain_scales_uniformly_and_aligns_ground(self):
        target = {'min': [-1, -1, 1], 'max': [1, 1, 5]}
        measured = {'min': [-0.5, -0.5, 0], 'max': [0.5, 0.5, 2]}
        plan = fw_parts.plan_part(self._part(), target, measured)
        self.assertAlmostEqual(plan['scale'], 2.0)
        self.assertEqual(plan['translate'], [0.0, 0.0, 1.0])
        self.assertNotIn('aspect_mismatch', plan['flags'])

    def test_height_fit_uses_z_ratio(self):
        target = {'min': [-1, -2, 1], 'max': [1, 2, 6]}
        measured = {'min': [-0.5, -0.5, 0], 'max': [0.5, 0.5, 2]}
        plan = fw_parts.plan_part(self._part(fit='height'), target, measured)
        self.assertAlmostEqual(plan['scale'], 2.5)

    def test_overlap_expands_part_around_center(self):
        target = {'min': [-1, -2, 1], 'max': [1, 2, 6]}
        measured = {'min': [-0.5, -0.5, 0], 'max': [0.5, 0.5, 2]}
        plan = fw_parts.plan_part(self._part(overlap=0.1), target, measured)
        self.assertAlmostEqual(plan['scale'], 2.2)
        self.assertEqual(plan['translate'], [0.0, 0.0, 1.0])

    def test_rotation_rotates_center_before_translation(self):
        target = {'min': [-1, -1, 0], 'max': [1, 1, 1]}
        measured = {'min': [0, 0, 0], 'max': [2, 1, 1]}
        plan = fw_parts.plan_part(self._part(rotationZ=90), target, measured)
        self.assertAlmostEqual(plan['scale'], 1.0)
        self.assertAlmostEqual(plan['translate'][0], 0.5)
        self.assertAlmostEqual(plan['translate'][1], -1.0)
        self.assertAlmostEqual(plan['translate'][2], 0.0)

    def test_manual_scale_overrides_and_flags(self):
        target = {'min': [-1, -2, 1], 'max': [1, 2, 6]}
        measured = {'min': [-0.5, -0.5, 0], 'max': [0.5, 0.5, 2]}
        plan = fw_parts.plan_part(self._part(scale=0.01), target, measured)
        self.assertAlmostEqual(plan['scale'], 0.01)
        self.assertIn('manual_scale', plan['flags'])
        self.assertIn('scale_outlier', plan['flags'])

    def test_aspect_mismatch_flagged_when_shape_cannot_fit(self):
        target = {'min': [0, 0, 0], 'max': [2, 4, 6]}
        measured = {'min': [-0.5, -0.5, 0], 'max': [0.5, 0.5, 2]}
        plan = fw_parts.plan_part(self._part(), target, measured)
        self.assertAlmostEqual(plan['scale'], 2.0)
        self.assertIn('aspect_mismatch', plan['flags'])

    def test_degenerate_part_box_rejected(self):
        target = {'min': [-1, -2, 1], 'max': [1, 2, 6]}
        measured = {'min': [0, 0, 0], 'max': [0, 1, 1]}
        with self.assertRaises(ValueError):
            fw_parts.plan_part(self._part(), target, measured)


class ContractFromBboxesTest(unittest.TestCase):
    def test_roundtrip_reproduces_part_boxes(self):
        entries = [
            {'id': 'a', 'mesh': 'a.glb', 'bbox': {'min': [0, 0, 0], 'max': [1, 1, 1]}},
            {'id': 'b', 'mesh': 'b.glb', 'bbox': {'min': [1, 0, 1], 'max': [2, 1, 2]}},
        ]
        contract = fw_parts.normalize_contract(
            fw_parts.contract_from_bboxes('CUT_DEMO', entries))
        for entry, part in zip(entries, contract['parts']):
            box, warnings = fw_parts.target_box(contract['views'], part)
            self.assertEqual(warnings, [])
            for axis in range(3):
                self.assertAlmostEqual(box['min'][axis], entry['bbox']['min'][axis], places=3)
                self.assertAlmostEqual(box['max'][axis], entry['bbox']['max'][axis], places=3)

    def test_empty_entries_rejected(self):
        with self.assertRaises(ValueError):
            fw_parts.contract_from_bboxes('CUT_DEMO', [])


class PartNamingTest(unittest.TestCase):
    def test_prompt_list_parses_names_and_descriptions(self):
        text = ('整机描述\n【必须包含的部件】\n'
                '· 车身 — 方正外壳\n'
                '· 车顶：顶部平台\n'
                '- 轮胎、轮毂\n'
                '【其他要求】\n· 不要写进部件\n')
        names = fw_parts.part_names_from_prompt(text)
        self.assertEqual([item['name'] for item in names], ['车身', '车顶', '轮胎', '轮毂'])
        self.assertEqual(names[0]['description'], '方正外壳')
        self.assertEqual(names[1]['description'], '顶部平台')

    def test_prompt_without_section_returns_empty(self):
        self.assertEqual(fw_parts.part_names_from_prompt('只有整机描述'), [])
        self.assertEqual(fw_parts.part_names_from_prompt(None), [])

    def test_prompt_dedupes_repeated_names(self):
        text = '【必须包含的部件】\n· 车身\n· 车身\n· 车顶'
        self.assertEqual([item['name'] for item in fw_parts.part_names_from_prompt(text)],
                         ['车身', '车顶'])

    def test_rename_keeps_ids_and_warns_on_count_mismatch(self):
        contract = fw_parts.normalize_contract(_contract())
        contract['parts'][0]['id'] = 'part_0'
        names = [{'name': '车身', 'description': '外壳'}, {'name': '车轮', 'description': ''}]
        report = fw_parts.rename_contract_parts(contract, names)
        self.assertEqual(contract['parts'][0]['id'], 'part_0')
        self.assertEqual(contract['parts'][0]['name'], '车身')
        self.assertEqual(contract['parts'][0]['description'], '外壳')
        self.assertEqual(report['renamed'], 1)
        self.assertEqual(report['parts'], 1)
        self.assertTrue(report['warnings'])

    def test_rename_without_names_keeps_cut_names(self):
        contract = fw_parts.normalize_contract(_contract())
        before = contract['parts'][0]['name']
        report = fw_parts.rename_contract_parts(contract, [])
        self.assertEqual(contract['parts'][0]['name'], before)
        self.assertEqual(report['renamed'], 0)
        self.assertTrue(report['warnings'])


if __name__ == '__main__':
    unittest.main()
