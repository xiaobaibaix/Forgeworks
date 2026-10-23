import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import mcp_forgeworks


def _call(name, arguments=None, request_id=1):
    return mcp_forgeworks.handle({
        'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
        'params': {'name': name, 'arguments': arguments or {}},
    })


class McpProtocolTest(unittest.TestCase):
    def test_initialize_echoes_supported_version(self):
        response = mcp_forgeworks.handle({
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2024-11-05'},
        })
        self.assertEqual(response['result']['protocolVersion'], '2024-11-05')
        self.assertEqual(response['result']['serverInfo']['name'], 'forgeworks')

    def test_unknown_protocol_version_falls_back(self):
        response = mcp_forgeworks.handle({
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '1999-01-01'},
        })
        self.assertEqual(response['result']['protocolVersion'], mcp_forgeworks.PROTOCOL_VERSIONS[-1])

    def test_initialized_notification_has_no_response(self):
        self.assertIsNone(mcp_forgeworks.handle(
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_ping(self):
        self.assertEqual(mcp_forgeworks.handle(
            {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'})['result'], {})

    def test_tools_list_exposes_entity_write_tools(self):
        response = mcp_forgeworks.handle(
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'})
        names = {tool['name'] for tool in response['result']['tools']}
        for name in ('forgeworks_get_content', 'forgeworks_upsert_entity',
                     'forgeworks_delete_entity', 'forgeworks_pipeline_run'):
            self.assertIn(name, names)

    def test_unknown_method_and_tool(self):
        unknown = mcp_forgeworks.handle(
            {'jsonrpc': '2.0', 'id': 4, 'method': 'nope'})
        self.assertEqual(unknown['error']['code'], -32601)
        result = _call('forgeworks_nope')
        self.assertTrue(result['result']['isError'])


class McpToolTest(unittest.TestCase):
    def test_get_entity_finds_row(self):
        content = {'elements': [{'id': 'Fe', 'name': '铁'}]}
        with mock.patch.object(mcp_forgeworks, 'request',
                               return_value={'ok': True, 'content': content, 'revision': 'r1'}):
            result = _call('forgeworks_get_entity', {'coll': 'elements', 'id': 'Fe'})
        payload = json.loads(result['result']['content'][0]['text'])
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['entity']['name'], '铁')
        self.assertEqual(payload['revision'], 'r1')

    def test_get_entity_missing_is_error(self):
        with mock.patch.object(mcp_forgeworks, 'request',
                               return_value={'ok': True, 'content': {}, 'revision': ''}):
            result = _call('forgeworks_get_entity', {'coll': 'elements', 'id': 'Xx'})
        self.assertTrue(result['result']['isError'])

    def test_upsert_forwards_base_revision(self):
        with mock.patch.object(mcp_forgeworks, 'request',
                               return_value={'ok': True, 'revision': 'r2'}) as mocked:
            result = _call('forgeworks_upsert_entity', {
                'coll': 'items', 'entity': {'id': 'I1'}, 'baseRevision': 'r1'})
        self.assertFalse(result['result']['isError'])
        mocked.assert_called_once_with('content/entity', {
            'coll': 'items', 'entity': {'id': 'I1'}, 'source': 'mcp', 'baseRevision': 'r1'})

    def test_conflict_is_reported(self):
        with mock.patch.object(mcp_forgeworks, 'request',
                               return_value={'ok': False, 'conflict': True, 'error': '冲突'}):
            result = _call('forgeworks_upsert_entity',
                           {'coll': 'items', 'entity': {'id': 'I1'}})
        self.assertTrue(result['result']['isError'])

    def test_bridge_offline_message(self):
        with mock.patch.object(mcp_forgeworks, 'request',
                               side_effect=mcp_forgeworks.BridgeError('Bridge 未启动')):
            result = _call('forgeworks_status')
        self.assertTrue(result['result']['isError'])
        self.assertIn('Bridge 未启动', result['result']['content'][0]['text'])


if __name__ == '__main__':
    unittest.main()
