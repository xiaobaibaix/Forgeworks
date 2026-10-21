import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_pipeline


class PipelineGraphTest(unittest.TestCase):
    def test_starter_graph_includes_asset_stages_in_order(self):
        graph = fw_pipeline.starter_graph('M1')
        by_id, order = fw_pipeline.validate_graph(graph)
        types = {node['type'] for node in graph['nodes']}
        for stage in fw_pipeline.LOCAL_STAGE_TYPES:
            self.assertIn(stage, types)
        self.assertLess(order.index('metadata'), order.index('validate'))
        self.assertLess(order.index('uv'), order.index('lod'))

    def test_browser_derived_stage_survives_save_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = fw_pipeline.starter_graph('M1')
            for node in graph['nodes']:
                if node['type'] == 'lod':
                    node['result'] = {
                        'state': 'done',
                        'source': 'forgeworks-ui',
                        'output': {'levels': [{'level': 0, 'parts': 3}]},
                    }
            saved = fw_pipeline.save_graph(directory, 'M1', graph)
            lod = next(node for node in saved['nodes'] if node['type'] == 'lod')
            self.assertEqual(lod['result']['state'], 'done')

            result = fw_pipeline.execute_local(directory, 'M1')
            lod = next(node for node in result['graph']['nodes'] if node['type'] == 'lod')
            self.assertEqual(lod['result']['state'], 'done')
            self.assertEqual(lod['result']['output']['levels'][0]['parts'], 3)
            uv = next(node for node in result['graph']['nodes'] if node['type'] == 'uv')
            self.assertEqual(uv['result']['state'], 'blocked')

    def test_output_port_may_fan_out_but_input_port_cannot_merge(self):
        graph = fw_pipeline.starter_graph('M1')
        graph['edges'] = [edge for edge in graph['edges'] if edge['from'] != 'metadata']
        graph['edges'].append({'from': 'metadata', 'out': 'mesh', 'to': 'validate', 'in': 'mesh'})
        graph['edges'].append({'from': 'metadata', 'out': 'mesh', 'to': 'export', 'in': 'mesh'})
        fw_pipeline.validate_graph(graph)

        graph['edges'].append({'from': 'uv', 'out': 'mesh', 'to': 'export', 'in': 'mesh'})
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_unknown_node_type_rejected(self):
        graph = fw_pipeline.starter_graph('M1')
        graph['nodes'].append({'id': 'bogus', 'type': 'bogus', 'params': {}})
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)


if __name__ == '__main__':
    unittest.main()
