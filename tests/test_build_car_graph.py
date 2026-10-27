import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_car_graph
import fw_pipeline
import fw_spec


def _fixture_graph():
    nodes = [
        {'id': 'prompt_overall', 'type': 'prompt', 'x': 0, 'y': 0,
         'params': {'text': '低多边形小汽车'}, 'result': {'state': 'done'}},
        {'id': 'overall', 'type': 'textToImage', 'x': 0, 'y': 0,
         'params': {'provider': 'ark'}, 'result': {'state': 'done'}},
        {'id': 'threeView_overall', 'type': 'threeView', 'x': 0, 'y': 0,
         'params': {'provider': 'ark'}},
        {'id': 'blueprint', 'type': 'blueprint', 'x': 0, 'y': 0,
         'params': {'provider': 'ark', 'template': 'car', 'specLocked': True},
         'result': {'state': 'done', 'output': {'spec': {'schemaVersion': 1}}}},
        {'id': 'prompt_assemble', 'type': 'prompt', 'x': 0, 'y': 0,
         'params': {'text': '旧装配指令'}},
    ]
    for role in build_car_graph.ROLES:
        nodes.extend([
            {'id': 'prompt_' + role, 'type': 'prompt', 'x': 0, 'y': 0,
             'params': {'text': '拆出%s的长指令' % role}},
            {'id': 'partImage_' + role, 'type': 'partImage', 'x': 0, 'y': 0, 'params': {}},
            {'id': 'partModel_' + role, 'type': 'partModel', 'x': 0, 'y': 0, 'params': {}},
            {'id': 'decimate_' + role, 'type': 'decimate', 'x': 0, 'y': 0,
             'params': {'targetFaces': 800}},
        ])
    nodes.extend([
        {'id': 'assemble_1', 'type': 'assemble', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'mate_body_roof', 'type': 'mate', 'x': 0, 'y': 0, 'params': {},
         'result': {'state': 'done', 'output': {'gapM': 0.0}}},
        {'id': 'styleApply_1', 'type': 'styleApply', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'uv_1', 'type': 'uv', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'lod_1', 'type': 'lod', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'collision_1', 'type': 'collision', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'animation_1', 'type': 'animation', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'metadata_1', 'type': 'metadata', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'validate_1', 'type': 'validate', 'x': 0, 'y': 0, 'params': {}},
        {'id': 'export_1', 'type': 'export', 'x': 0, 'y': 0, 'params': {}},
    ])
    return {'schemaVersion': 1, 'assetId': 'MC_CAR', 'template': 'parts',
            'nodes': nodes, 'edges': [], 'revision': 3}


class CarGraphRewireTest(unittest.TestCase):
    def setUp(self):
        spec = fw_spec.template_spec('MC_CAR', template='car')
        self.rewired, self.warnings = build_car_graph.rewire(_fixture_graph(), spec)
        self.by_id = {node['id']: node for node in self.rewired['nodes']}
        self.edges = self.rewired['edges']

    def test_graph_is_valid(self):
        fw_pipeline.validate_graph(self.rewired)

    def test_overall_spec_is_reanalyzed(self):
        overall = self.by_id['blueprint_overall']
        self.assertEqual(overall['params']['scope'], 'overall')
        self.assertFalse(overall['params']['specLocked'])
        self.assertEqual(overall['result']['output']['spec'], {'schemaVersion': 1})
        self.assertNotIn('blueprint', self.by_id)

    def test_part_three_view_uses_concise_subject(self):
        for role in build_car_graph.ROLES:
            self.assertEqual(self.by_id['threeView_' + role]['params']['prompt'],
                             build_car_graph.PART_SUBJECTS[role])
            text_edges = [edge for edge in self.edges
                          if edge['to'] == 'threeView_' + role and edge['in'] == 'text']
            self.assertEqual(text_edges, [])

    def test_parts_chain_dimension_and_measure(self):
        for role in build_car_graph.ROLES:
            self.assertIn(('blueprint_overall', 'spec', 'blueprint_' + role),
                          [(e['from'], e['out'], e['to']) for e in self.edges])
            self.assertIn(('threeView_' + role, 'sheet', 'blueprint_' + role),
                          [(e['from'], e['out'], e['to']) for e in self.edges])
            self.assertIn(('blueprint_' + role, 'measure', 'partModel_' + role),
                          [(e['from'], e['out'], e['to']) for e in self.edges])
            self.assertIn(('blueprint_overall', 'spec', 'partModel_' + role),
                          [(e['from'], e['out'], e['to']) for e in self.edges])
            self.assertIn(('partModel_' + role, 'assembly', 'decimate_' + role),
                          [(e['from'], e['out'], e['to']) for e in self.edges])

    def test_mate_chain_grounds_last_node_only(self):
        self.assertFalse(self.by_id['mate_body_roof']['params']['ground'])
        self.assertTrue(self.by_id['mate_body_wheel']['params']['ground'])
        self.assertEqual(self.by_id['mate_body_roof']['result']['output']['gapM'], 0.0)
        self.assertIn(('decimate_body', 'assembly', 'mate_body_roof'),
                      [(e['from'], e['out'], e['to']) for e in self.edges])
        self.assertIn(('mate_body_roof', 'assembly', 'mate_body_wheel'),
                      [(e['from'], e['out'], e['to']) for e in self.edges])
        self.assertIn(('decimate_wheel', 'assembly', 'mate_body_wheel'),
                      [(e['from'], e['out'], e['to']) for e in self.edges])
        self.assertIn(('mate_body_wheel', 'mesh', 'styleApply_1'),
                      [(e['from'], e['out'], e['to']) for e in self.edges])
        self.assertNotIn('assemble_1', self.by_id)

    def test_tail_chain_is_linear_and_export_waits_for_validate(self):
        order = ['styleApply_1', 'uv_1', 'lod_1', 'collision_1',
                 'animation_1', 'metadata_1', 'validate_1']
        for previous, current in zip(order, order[1:]):
            self.assertIn((previous, 'mesh', current),
                          [(e['from'], e['out'], e['to']) for e in self.edges])
        self.assertIn(('metadata_1', 'mesh', 'export_1'),
                      [(e['from'], e['out'], e['to']) for e in self.edges])
        self.assertIn(('validate_1', 'report', 'export_1'),
                      [(e['from'], e['out'], e['to']) for e in self.edges])

    def test_orphan_assemble_prompt_is_dropped(self):
        self.assertNotIn('prompt_assemble', self.by_id)


if __name__ == '__main__':
    unittest.main()
