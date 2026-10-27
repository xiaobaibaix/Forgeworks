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
