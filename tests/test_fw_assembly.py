import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_assembly


def _assembly(mesh_path='outputs/model_body.glb', part_id='partModel_body'):
    return {
        'schemaVersion': 1,
        'assemblyId': 'asm_' + part_id,
        'assetId': 'M1',
        'meshPath': mesh_path,
        'parts': [{'id': part_id, 'role': 'body', 'meshPath': mesh_path,
                   'anchorNorm': [0.5, 0.5, 0.5]}],
        'connectors': [{'id': 'body:boom_base', 'partId': part_id,
                        'pos': [0.504, 0.0, 0.28], 'axis': [1, 0, 0]}],
        'mates': [],
        'warnings': [],
    }


class AssemblyForNodeTest(unittest.TestCase):
    def _graph(self, state='done', with_assembly=True):
        output = {'assembly': _assembly()} if with_assembly else {}
        return (
            {'edges': [{'from': 'model', 'out': 'assembly', 'to': 'dec', 'in': 'assembly'}]},
            {'model': {'id': 'model', 'type': 'partModel',
                       'result': {'state': state, 'output': output}}},
        )

    def test_returns_none_without_edge(self):
        self.assertIsNone(fw_assembly.assembly_for_node({'edges': []}, {}, 'dec'))

    def test_reads_assembly_from_upstream(self):
        graph, by_id = self._graph()
        self.assertEqual(fw_assembly.assembly_for_node(graph, by_id, 'dec')['meshPath'],
                         'outputs/model_body.glb')

    def test_missing_upstream_node_raises(self):
        graph, _ = self._graph()
        with self.assertRaises(ValueError) as ctx:
            fw_assembly.assembly_for_node(graph, {}, 'dec')
        self.assertTrue(str(ctx.exception).startswith('ASSEMBLY_MISSING'))

    def test_not_ready_upstream_raises(self):
        graph, by_id = self._graph(state='running')
        with self.assertRaises(ValueError) as ctx:
            fw_assembly.assembly_for_node(graph, by_id, 'dec')
        self.assertIn('未就绪', str(ctx.exception))

    def test_upstream_without_assembly_raises(self):
        graph, by_id = self._graph(with_assembly=False)
        with self.assertRaises(ValueError) as ctx:
            fw_assembly.assembly_for_node(graph, by_id, 'dec')
        self.assertIn('没有 assembly', str(ctx.exception))


class RetargetAssemblyTest(unittest.TestCase):
    def test_retargets_mesh_without_touching_connectors_or_mates(self):
        assembly = _assembly()
        assembly['mates'] = [{'a': 'body:boom_base', 'b': 'boom:base'}]
        updated = fw_assembly.retarget_assembly(assembly, 'outputs/model_dec.glb')
        self.assertEqual(updated['meshPath'], 'outputs/model_dec.glb')
        self.assertEqual([part['meshPath'] for part in updated['parts']],
                         ['outputs/model_dec.glb'])
        self.assertEqual(updated['connectors'], assembly['connectors'])
        self.assertEqual(updated['mates'], assembly['mates'])
        self.assertEqual(assembly['meshPath'], 'outputs/model_body.glb')
        self.assertIsNot(updated['parts'][0], assembly['parts'][0])


def _part_assembly(role, mesh, port_id, pos, axis, normal):
    return {
        'schemaVersion': 1,
        'assemblyId': 'asm_' + role,
        'assetId': 'M1',
        'meshPath': mesh,
        'parts': [{'partId': 'partModel_' + role, 'role': role, 'meshPath': mesh}],
        'connectors': [{'id': role + ':' + port_id, 'owner': role, 'radiusM': 0.05,
                        'frame': {'pos': list(pos), 'axis': list(axis),
                                  'normal': list(normal)}}],
        'mates': [],
        'warnings': [],
    }


def _roof_on_body(normal_b=(1, 0, 0)):
    body = _part_assembly('body', 'outputs/body.glb', 'roof_mount',
                          [0, 0, 0.35], [0, 0, 1], [1, 0, 0])
    roof = _part_assembly('roof', 'outputs/roof.glb', 'mount',
                          [0, 0, 0.1], [0, 0, -1], normal_b)
    connection = {'id': 'c_roof_body', 'a': 'roof:mount', 'b': 'body:roof_mount'}
    return body, roof, connection


class MateMathTest(unittest.TestCase):
    def test_plan_aligns_anti_parallel_ports_with_offset(self):
        body, roof, connection = _roof_on_body()
        plan = fw_assembly.mate_plan(connection, body, roof, offset_m=-0.002)
        self.assertEqual(plan['portA'], 'body:roof_mount')
        self.assertEqual(plan['portB'], 'roof:mount')
        for actual, expected in zip(plan['rotation'], [0, 0, 0, 1]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(plan['translation'][2], 0.248, places=6)
        self.assertAlmostEqual(plan['gapM'], 0.0, places=6)
        self.assertAlmostEqual(plan['appliedOffsetM'], 0.002, places=6)
        self.assertAlmostEqual(plan['axisErrorDeg'], 0.0, places=4)

    def test_plan_twists_child_about_parent_axis(self):
        body, roof, connection = _roof_on_body(normal_b=(0, 1, 0))
        plan = fw_assembly.mate_plan(connection, body, roof)
        rotated = fw_assembly._quat_rotate(plan['rotation'], [0, 1, 0])
        for actual, expected in zip(rotated, [1, 0, 0]):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_plan_can_skip_twist_alignment(self):
        body, roof, connection = _roof_on_body(normal_b=(0, 1, 0))
        plan = fw_assembly.mate_plan(connection, body, roof, align_twist=False)
        for actual, expected in zip(plan['rotation'], [0, 0, 0, 1]):
            self.assertAlmostEqual(actual, expected)

    def test_plan_reports_axis_error_for_crossed_ports(self):
        body = _part_assembly('body', 'outputs/body.glb', 'roof_mount',
                              [0, 0, 0.35], [1, 0, 0], [0, 0, 1])
        roof = _part_assembly('roof', 'outputs/roof.glb', 'mount',
                              [0, 0, 0.1], [0, 1, 0], [0, 0, 1])
        connection = {'id': 'c_roof_body', 'a': 'roof:mount', 'b': 'body:roof_mount'}
        plan = fw_assembly.mate_plan(connection, body, roof)
        self.assertGreater(plan['axisErrorDeg'], 5)

    def test_plan_requires_unique_connection_when_id_missing(self):
        body, roof, connection = _roof_on_body()
        spec = {'connections': [connection]}
        self.assertEqual(
            fw_assembly.connection_for(spec, '', 'body', 'roof')['id'], 'c_roof_body')
        with self.assertRaises(ValueError) as ctx:
            fw_assembly.connection_for({'connections': []}, '', 'body', 'roof')
        self.assertTrue(str(ctx.exception).startswith('MATE_CONNECTION_MISSING'))

    def test_missing_connector_is_reported(self):
        body, roof, connection = _roof_on_body()
        roof['connectors'] = []
        with self.assertRaises(ValueError) as ctx:
            fw_assembly.mate_plan(connection, body, roof)
        self.assertTrue(str(ctx.exception).startswith('MATE_CONNECTOR_MISSING'))

    def test_connector_frame_accepts_flat_and_nested_shapes(self):
        flat = {'id': 'x', 'pos': [0, 1, 2], 'axis': [0, 0, 2], 'normal': [0, 1, 0]}
        nested = {'id': 'x', 'owner': 'body',
                  'frame': {'pos': [0, 1, 2], 'axis': [0, 0, 2], 'normal': [0, 1, 0]}}
        for shape in (flat, nested):
            frame = fw_assembly.connector_frame(shape)
            self.assertEqual(frame['pos'], [0.0, 1.0, 2.0])
            self.assertEqual(frame['axis'], [0.0, 0.0, 1.0])
            self.assertEqual(frame['normal'], [0.0, 1.0, 0.0])

    def test_assembly_for_node_reads_named_ports(self):
        body, roof, _ = _roof_on_body()
        graph = {'edges': [{'from': 'a', 'out': 'assembly', 'to': 'm', 'in': 'a'},
                           {'from': 'b', 'out': 'assembly', 'to': 'm', 'in': 'b'}]}
        by_id = {'a': {'result': {'state': 'done', 'output': {'assembly': body}}},
                 'b': {'result': {'state': 'done', 'output': {'assembly': roof}}}}
        self.assertEqual(fw_assembly.assembly_for_node(graph, by_id, 'm', port='a'),
                         body)
        self.assertEqual(fw_assembly.assembly_for_node(graph, by_id, 'm', port='b'),
                         roof)


class MergeAssemblyTest(unittest.TestCase):
    def test_merge_keeps_parent_frame_and_transforms_child(self):
        body, roof, connection = _roof_on_body()
        plan = fw_assembly.mate_plan(connection, body, roof, offset_m=-0.002)
        report = {'gapM': 0.0, 'appliedOffsetM': 0.002, 'axisErrorDeg': 0.0,
                  'groundShift': [0, 0, 0]}
        merged = fw_assembly.merge_assembly(body, roof, plan, report,
                                            assembly_id='asm_mate_1')
        self.assertEqual(merged['assemblyId'], 'asm_mate_1')
        self.assertEqual([part['role'] for part in merged['parts']], ['body', 'roof'])
        self.assertEqual([item['id'] for item in merged['connectors']],
                         ['body:roof_mount', 'roof:mount'])
        self.assertEqual(merged['connectors'][0], body['connectors'][0])
        self.assertAlmostEqual(merged['connectors'][1]['frame']['pos'][2], 0.348)
        self.assertEqual(merged['mates'][0]['id'], 'c_roof_body')
        self.assertEqual(merged['mates'][0]['a'], 'body:roof_mount')
        self.assertEqual(merged['mates'][0]['b'], 'roof:mount')
        self.assertEqual(merged['mates'][0]['status'], 'ok')
        self.assertIsNot(merged['connectors'][1], roof['connectors'][0])

    def test_merge_applies_ground_shift_to_all_connectors(self):
        body, roof, connection = _roof_on_body()
        plan = fw_assembly.mate_plan(connection, body, roof)
        report = {'gapM': 0.0, 'appliedOffsetM': 0.0, 'axisErrorDeg': 0.0,
                  'groundShift': [0, 0, -0.1]}
        merged = fw_assembly.merge_assembly(body, roof, plan, report, ground=True)
        self.assertAlmostEqual(merged['connectors'][0]['frame']['pos'][2], 0.25)
        self.assertAlmostEqual(merged['connectors'][1]['frame']['pos'][2], 0.248)

    def test_merge_warns_on_axis_error_and_offset_drift(self):
        body, roof, connection = _roof_on_body()
        plan = fw_assembly.mate_plan(connection, body, roof, offset_m=-0.002)
        report = {'gapM': 0.0, 'appliedOffsetM': 0.005, 'axisErrorDeg': 3.0,
                  'warnings': ['Blender 提示']}
        merged = fw_assembly.merge_assembly(body, roof, plan, report)
        self.assertEqual(merged['mates'][0]['status'], 'warn')
        self.assertIn('Blender 提示', merged['warnings'])
        self.assertTrue(any(item.startswith('MATE_AXIS_ERROR') for item in merged['warnings']))
        self.assertTrue(any(item.startswith('MATE_OFFSET_DRIFT') for item in merged['warnings']))
        report['axisErrorDeg'] = 6.0
        merged = fw_assembly.merge_assembly(body, roof, plan, report)
        self.assertEqual(merged['mates'][0]['status'], 'error')


class BboxDriftTest(unittest.TestCase):
    def test_max_relative_change(self):
        self.assertAlmostEqual(
            fw_assembly.bbox_drift([4.0, 2.0, 1.0], [4.0, 2.2, 1.0]), 0.1)

    def test_missing_or_invalid_data_returns_zero(self):
        for before, after in ((None, [1, 1, 1]), ([1, 1], [1, 1, 1]),
                              (['x', 1, 1], [1, 1, 1]), ([0, 1, 1], [5, 1, 1])):
            with self.subTest(before=before, after=after):
                self.assertEqual(fw_assembly.bbox_drift(before, after), 0.0)


if __name__ == '__main__':
    unittest.main()
