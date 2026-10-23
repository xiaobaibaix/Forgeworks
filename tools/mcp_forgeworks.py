#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forgeworks MCP 服务器（stdio JSON-RPC，零第三方依赖）。

把本地 Bridge 的 REST 能力暴露给 AI：读取/增删改项目实体、扫描、发布、
生成管线。默认连接 http://127.0.0.1:8787，可用 FORGEWORKS_BRIDGE 覆盖。

用法：
    python3 tools/mcp_forgeworks.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

BRIDGE = os.environ.get('FORGEWORKS_BRIDGE', 'http://127.0.0.1:8787').rstrip('/')
SERVER_NAME = 'forgeworks'
SERVER_VERSION = '0.1.0'
PROTOCOL_VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')
COLLECTIONS = ('elements', 'items', 'machines', 'recipes', 'techs')


class BridgeError(RuntimeError):
    pass


def request(route, body=None, timeout=30):
    url = BRIDGE + '/api/' + route
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, method='GET' if body is None else 'POST',
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        payload = error.read().decode('utf-8', 'replace')
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = {'ok': False, 'error': 'Bridge HTTP %d' % error.code}
        parsed.setdefault('httpStatus', error.code)
        return parsed
    except urllib.error.URLError as error:
        raise BridgeError('无法连接 Forgeworks Bridge（%s）：%s。请先运行 python3 tools/bridge.py'
                          % (BRIDGE, error.reason))
    try:
        return json.loads(payload)
    except ValueError:
        return {'ok': True, 'body': payload}


def _require(args, key):
    value = args.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError('缺少参数: %s' % key)
    return value


def _content_and_revision():
    result = request('project/content')
    if not result.get('ok'):
        raise BridgeError(result.get('error') or '读取项目内容失败')
    return result.get('content') or {}, result.get('revision') or ''


def tool_status(args):
    return request('status')


def tool_get_content(args):
    content, revision = _content_and_revision()
    return {'ok': True, 'revision': revision, 'project': request('status').get('project'),
            'content': content}


def tool_list_entities(args):
    content, revision = _content_and_revision()
    coll = args.get('coll')
    if coll is not None and coll not in COLLECTIONS:
        raise ValueError('coll 必须是 %s 之一' % ', '.join(COLLECTIONS))
    groups = [coll] if coll else list(COLLECTIONS)
    rows = {}
    for name in groups:
        items = content.get(name)
        rows[name] = [
            {key: item.get(key) for key in ('id', 'name', 'symbol', 'type', 'tier')
             if key in item}
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
        ]
    return {'ok': True, 'revision': revision, 'entities': rows}


def tool_get_entity(args):
    coll = _require(args, 'coll')
    entity_id = _require(args, 'id')
    if coll not in COLLECTIONS:
        raise ValueError('coll 必须是 %s 之一' % ', '.join(COLLECTIONS))
    content, revision = _content_and_revision()
    for item in content.get(coll) or []:
        if isinstance(item, dict) and item.get('id') == entity_id:
            return {'ok': True, 'revision': revision, 'coll': coll, 'entity': item}
    raise BridgeError('实体不存在: %s/%s' % (coll, entity_id))


def tool_upsert_entity(args):
    coll = _require(args, 'coll')
    entity = _require(args, 'entity')
    payload = {'coll': coll, 'entity': entity, 'source': 'mcp'}
    if args.get('baseRevision') is not None:
        payload['baseRevision'] = args.get('baseRevision')
    return request('content/entity', payload)


def tool_delete_entity(args):
    payload = {'coll': _require(args, 'coll'), 'id': _require(args, 'id'), 'source': 'mcp'}
    if args.get('baseRevision') is not None:
        payload['baseRevision'] = args.get('baseRevision')
    return request('content/entity/delete', payload)


def tool_scan(args):
    return request('manifest/scan', {})


def tool_publish(args):
    payload = {}
    if args.get('ids') is not None:
        payload['ids'] = args.get('ids')
    return request('project/publish', payload)


def tool_open_project(args):
    return request('project/bind', {'path': _require(args, 'path')})


def tool_create_project(args):
    return request('project/create', {'parent': _require(args, 'parent'),
                                      'name': _require(args, 'name')})


def tool_conflicts(args):
    return request('conflicts')


def tool_pipeline_get(args):
    asset_id = _require(args, 'assetId')
    kind = args.get('kind') or 'machine'
    return request('pipeline/graph/%s?kind=%s' % (asset_id, kind))


def tool_pipeline_save(args):
    return request('pipeline/graph/save', {
        'assetId': _require(args, 'assetId'),
        'kind': args.get('kind') or 'machine',
        'graph': _require(args, 'graph'),
    })


def tool_pipeline_run(args):
    payload = {'assetId': _require(args, 'assetId'), 'kind': args.get('kind') or 'machine'}
    for key in ('nodeId', 'through'):
        if args.get(key) is not None:
            payload[key] = args.get(key)
    return request('pipeline/run', payload)


EMPTY_SCHEMA = {'type': 'object', 'properties': {}, 'additionalProperties': False}


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties,
            'required': list(required), 'additionalProperties': False}


COLL_PROP = {'type': 'string', 'enum': list(COLLECTIONS), 'description': '内容集合'}
ENTITY_PROP = {'type': 'object', 'description': '完整实体对象，必须含非空 id',
               'additionalProperties': True}

TOOLS = [
    {'name': 'forgeworks_status',
     'description': '查看 Bridge 状态：当前项目、UE 导出目标、Blender 是否可用。',
     'inputSchema': EMPTY_SCHEMA, 'handler': tool_status},
    {'name': 'forgeworks_get_content',
     'description': '读取整个 project.json 与 revision（后续写入用它做乐观锁）。',
     'inputSchema': EMPTY_SCHEMA, 'handler': tool_get_content},
    {'name': 'forgeworks_list_entities',
     'description': '列出元素/物品/机器/配方/科技的概要（id、name 等）。',
     'inputSchema': _schema({'coll': COLL_PROP}), 'handler': tool_list_entities},
    {'name': 'forgeworks_get_entity',
     'description': '读取单个实体。',
     'inputSchema': _schema({'coll': COLL_PROP, 'id': {'type': 'string'}}, ('coll', 'id')),
     'handler': tool_get_entity},
    {'name': 'forgeworks_upsert_entity',
     'description': '新增或整体替换一个实体。传 baseRevision 可避免覆盖并发修改（冲突返回 409）。',
     'inputSchema': _schema({'coll': COLL_PROP, 'entity': ENTITY_PROP,
                             'baseRevision': {'type': 'string'}}, ('coll', 'entity')),
     'handler': tool_upsert_entity},
    {'name': 'forgeworks_delete_entity',
     'description': '删除一个实体。传 baseRevision 可避免覆盖并发修改。',
     'inputSchema': _schema({'coll': COLL_PROP, 'id': {'type': 'string'},
                             'baseRevision': {'type': 'string'}}, ('coll', 'id')),
     'handler': tool_delete_entity},
    {'name': 'forgeworks_scan',
     'description': '扫描 _Source，核对 manifest 与磁盘文件。',
     'inputSchema': EMPTY_SCHEMA, 'handler': tool_scan},
    {'name': 'forgeworks_publish_to_ue',
     'description': '把资产发布到 UE 导出目标；不传 ids 表示全部。',
     'inputSchema': _schema({'ids': {'type': 'array', 'items': {'type': 'string'}}}),
     'handler': tool_publish},
    {'name': 'forgeworks_open_project',
     'description': '打开/绑定一个 Forgeworks 项目目录。',
     'inputSchema': _schema({'path': {'type': 'string'}}, ('path',)), 'handler': tool_open_project},
    {'name': 'forgeworks_create_project',
     'description': '在 parent 目录下新建 Forgeworks 项目。',
     'inputSchema': _schema({'parent': {'type': 'string'}, 'name': {'type': 'string'}},
                            ('parent', 'name')), 'handler': tool_create_project},
    {'name': 'forgeworks_conflicts',
     'description': '列出待裁决的文件冲突。',
     'inputSchema': EMPTY_SCHEMA, 'handler': tool_conflicts},
    {'name': 'forgeworks_pipeline_get',
     'description': '读取某个资产的生成管线图。',
     'inputSchema': _schema({'assetId': {'type': 'string'}, 'kind': {'type': 'string'}},
                            ('assetId',)), 'handler': tool_pipeline_get},
    {'name': 'forgeworks_pipeline_save',
     'description': '保存生成管线图。',
     'inputSchema': _schema({'assetId': {'type': 'string'}, 'graph': {'type': 'object'},
                             'kind': {'type': 'string'}}, ('assetId', 'graph')),
     'handler': tool_pipeline_save},
    {'name': 'forgeworks_pipeline_run',
     'description': '运行管线节点；through=true 表示连同上游一起跑。',
     'inputSchema': _schema({'assetId': {'type': 'string'}, 'nodeId': {'type': 'string'},
                             'through': {'type': 'boolean'}, 'kind': {'type': 'string'}},
                            ('assetId',)), 'handler': tool_pipeline_run},
]

TOOL_MAP = {tool['name']: tool for tool in TOOLS}


def call_tool(name, arguments):
    tool = TOOL_MAP.get(name)
    if not tool:
        return _tool_result({'ok': False, 'error': '未知工具: %s' % name}, True)
    args = arguments if isinstance(arguments, dict) else {}
    try:
        result = tool['handler'](args)
    except BridgeError as error:
        return _tool_result({'ok': False, 'error': str(error)}, True)
    except ValueError as error:
        return _tool_result({'ok': False, 'error': str(error)}, True)
    return _tool_result(result, not bool(result.get('ok', True)))


def _tool_result(payload, is_error):
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {'content': [{'type': 'text', 'text': text}], 'isError': is_error}


def handle(message):
    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params') or {}
    is_notification = 'id' not in message
    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1]
        return _ok(request_id, {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
        })
    if method in ('notifications/initialized', 'notifications/cancelled'):
        return None
    if method == 'ping':
        return _ok(request_id, {})
    if method == 'tools/list':
        return _ok(request_id, {'tools': [
            {'name': tool['name'], 'description': tool['description'],
             'inputSchema': tool['inputSchema']} for tool in TOOLS]})
    if method == 'tools/call':
        result = call_tool(params.get('name'), params.get('arguments'))
        return _ok(request_id, result)
    if is_notification:
        return None
    return {'jsonrpc': '2.0', 'id': request_id,
            'error': {'code': -32601, 'message': '未知方法: %s' % method}}


def _ok(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def write(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    try:
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            write({'jsonrpc': '2.0', 'id': None,
                   'error': {'code': -32700, 'message': 'JSON 解析失败'}})
            continue
        if not isinstance(message, dict):
            continue
        try:
            response = handle(message)
        except Exception as error:  # 单条消息失败不能拖垮整个会话
            response = {'jsonrpc': '2.0', 'id': message.get('id'),
                        'error': {'code': -32603, 'message': str(error)}}
        if response is not None:
            write(response)


if __name__ == '__main__':
    main()
