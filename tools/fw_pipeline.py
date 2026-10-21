#!/usr/bin/env python3
"""Persistent, local-first asset pipeline graph services."""

import hashlib
import json
import os
import re
import time
import uuid

NODE_TYPES = {
    'prompt': {'in': {}, 'out': {'text': 'text'}},
    'textToImage': {'in': {'text': 'text'}, 'out': {'image': 'image'}},
    'imageTo3D': {'in': {'image': 'image'}, 'out': {'mesh': 'mesh'}},
    'decimate': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'styleApply': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'validate': {'in': {'mesh': 'mesh'}, 'out': {'report': 'report'}},
    'manualEdit': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'variant': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'imageExport': {'in': {'image': 'image'}, 'out': {}},
    'export': {'in': {'mesh': 'mesh', 'report': 'report'}, 'out': {}},
}


def _digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_graph(graph):
    if not isinstance(graph, dict) or graph.get('schemaVersion') != 1:
        raise ValueError('graph schemaVersion 必须为 1')
    nodes, edges = graph.get('nodes'), graph.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) > 200 or len(edges) > 500:
        raise ValueError('nodes/edges 格式非法或超出数量限制')
    if len(json.dumps(graph, ensure_ascii=False).encode('utf-8')) > 4 * 1024 * 1024:
        raise ValueError('流水线图超过 4 MB 限制')
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', str(node.get('id', ''))):
            raise ValueError('节点 ID 非法')
        if node['id'] in by_id or node.get('type') not in NODE_TYPES:
            raise ValueError('节点 ID 重复或类型未知')
        if not isinstance(node.get('params', {}), dict):
            raise ValueError('节点 params 必须是对象')
        if len(json.dumps(node.get('params', {}), ensure_ascii=False).encode('utf-8')) > 256 * 1024:
            raise ValueError('节点参数超过 256 KB 限制')
        by_id[node['id']] = node
    adjacency = {key: [] for key in by_id}
    incoming = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError('连线格式非法')
        source, target = by_id.get(edge.get('from')), by_id.get(edge.get('to'))
        if not source or not target:
            raise ValueError('连线引用了不存在的节点')
        out_type = NODE_TYPES[source['type']]['out'].get(edge.get('out'))
        in_type = NODE_TYPES[target['type']]['in'].get(edge.get('in'))
        if not out_type or out_type != in_type:
            raise ValueError('连线端口类型不匹配')
        key = (target['id'], edge['in'])
        if key in incoming:
            raise ValueError('输入端口只能有一条连线')
        incoming.add(key)
        adjacency[source['id']].append(target['id'])
    visiting, visited, order = set(), set(), []
    def visit(node_id):
        if node_id in visiting:
            raise ValueError('流水线存在循环依赖')
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in adjacency[node_id]:
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)
        order.append(node_id)
    for node_id in by_id:
        visit(node_id)
    return by_id, list(reversed(order))


def pipeline_root(forgeworks_root, asset_id):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', str(asset_id or '')):
        raise ValueError('资产 ID 非法')
    return os.path.join(forgeworks_root, '_Source', 'pipeline', asset_id)


def load_graph(forgeworks_root, asset_id):
    path = os.path.join(pipeline_root(forgeworks_root, asset_id), 'graph.json')
    try:
        with open(path, encoding='utf-8') as stream:
            graph = json.load(stream)
    except FileNotFoundError:
        graph = {'schemaVersion': 1, 'assetId': asset_id, 'revision': 0, 'nodes': [], 'edges': [], 'updatedAt': None}
    validate_graph(graph)
    return graph


def save_graph(forgeworks_root, asset_id, graph):
    by_id, order = validate_graph(graph)
    graph = dict(graph, assetId=asset_id, revision=int(graph.get('revision') or 0) + 1,
                 updatedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    root = pipeline_root(forgeworks_root, asset_id)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, 'graph.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(graph, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    previous = {}
    for node_id in order:
        node = by_id[node_id]
        upstream = [edge for edge in graph['edges'] if edge['to'] == node_id]
        input_hash = _digest([(edge, previous.get(edge['from'])) for edge in upstream])
        param_hash = _digest({'type': node['type'], 'params': node.get('params', {})})
        signature = _digest([input_hash, param_hash])
        old = node.get('result') or {}
        state = 'done' if old.get('signature') == signature and old.get('state') == 'done' else 'dirty'
        node['result'] = dict(old, state=state, signature=signature, inputHash=input_hash, paramHash=param_hash)
        previous[node_id] = signature
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(graph, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return graph


def execute_local(forgeworks_root, asset_id, target_id=None, through=False):
    graph = load_graph(forgeworks_root, asset_id)
    by_id, order = validate_graph(graph)
    if target_id and target_id not in by_id:
        raise ValueError('目标节点不存在')
    if target_id and not through:
        order = [target_id]
    elif target_id:
        order = order[:order.index(target_id) + 1]
    outputs = {}
    for node_id in order:
        node = by_id[node_id]
        if node['type'] in ('textToImage', 'imageTo3D'):
            node.setdefault('result', {})
            task = node['result'].get('providerTask') or {}
            if task.get('state') == 'success':
                node['result']['state'] = 'done'
            elif task.get('state') in ('queued', 'running'):
                node['result']['state'] = task['state']
            else:
                node['result']['state'] = 'blocked'
                node['result']['error'] = '远程生成未执行：请在配置 Provider 密钥后由用户主动发起'
            continue
        if node['type'] == 'prompt':
            node.setdefault('result', {})['state'] = 'done'
            node['result']['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            node['result']['output'] = {'text': str(node.get('params', {}).get('text', ''))[:12000]}
        elif node['type'] == 'imageExport':
            edge = next((item for item in graph['edges'] if item.get('to') == node_id and item.get('in') == 'image'), None)
            source = by_id.get(edge.get('from')) if edge else None
            source_output = (((source or {}).get('result') or {}).get('providerTask') or {}).get('output') or {}
            image_path = source_output.get('imagePath')
            if image_path and os.path.isfile(os.path.join(pipeline_root(forgeworks_root, asset_id), image_path)):
                node.setdefault('result', {})['state'] = 'done'
                node['result']['output'] = {'imagePath': image_path}
            else:
                node.setdefault('result', {})['state'] = 'blocked'
                node['result']['error'] = '上游图片任务尚未成功，图像输出不可用'
        else:
            node.setdefault('result', {})['state'] = 'blocked'
            node['result']['error'] = '该处理器尚未实现；为避免产生虚假结果，此节点不标记为完成'
        if node['type'] == 'export':
            node['result']['state'] = 'blocked'
            node['result']['error'] = '导出需通过同步导出流程并满足 validate 门禁'
        outputs[node_id] = node.get('result', {}).get('output')
    graph['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    root = pipeline_root(forgeworks_root, asset_id)
    with open(os.path.join(root, 'graph.json'), 'w', encoding='utf-8') as stream:
        json.dump(graph, stream, ensure_ascii=False, indent=2)
    return {'graph': graph, 'ran': order}


def starter_graph(asset_id, template='machine'):
    nodes = [
        {'id': 'prompt', 'type': 'prompt', 'x': 80, 'y': 100, 'params': {'text': ''}},
        {'id': 'image', 'type': 'textToImage', 'x': 340, 'y': 100, 'params': {'provider': 'tripo'}},
        {'id': 'model', 'type': 'imageTo3D', 'x': 600, 'y': 100, 'params': {'provider': 'tripo', 'texture': False}},
        {'id': 'style', 'type': 'styleApply', 'x': 860, 'y': 100, 'params': {}},
        {'id': 'validate', 'type': 'validate', 'x': 1120, 'y': 100, 'params': {'maxTriangles': 20000}},
        {'id': 'export', 'type': 'export', 'x': 1380, 'y': 100, 'params': {}},
    ]
    edges = [{'from': 'prompt', 'out': 'text', 'to': 'image', 'in': 'text'},
             {'from': 'image', 'out': 'image', 'to': 'model', 'in': 'image'},
             {'from': 'model', 'out': 'mesh', 'to': 'style', 'in': 'mesh'},
             {'from': 'style', 'out': 'mesh', 'to': 'validate', 'in': 'mesh'},
             {'from': 'validate', 'out': 'report', 'to': 'export', 'in': 'report'},
             {'from': 'style', 'out': 'mesh', 'to': 'export', 'in': 'mesh'}]
    if template == 'icon':
        nodes = [nodes[0], nodes[1], {'id': 'imageExport', 'type': 'imageExport', 'x': 600, 'y': 100, 'params': {}}]
        edges = [{'from': 'prompt', 'out': 'text', 'to': 'image', 'in': 'text'},
                 {'from': 'image', 'out': 'image', 'to': 'imageExport', 'in': 'image'}]
    elif template == 'item':
        nodes[2]['params'].update({'faceLimit': 10000, 'smartLowPoly': True, 'texture': False})
    else:
        template = 'machine'
    return {'schemaVersion': 1, 'assetId': asset_id, 'template': template, 'revision': 0, 'nodes': nodes, 'edges': edges}
