#!/usr/bin/env python3
"""Persistent, local-first asset pipeline graph services."""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

import fw_parts
import fw_providers
import fw_spec
import fw_views

ASSET_KIND_DIRS = {'machine': '机器', 'item': '物品/图标', 'element': '元素', 'data': '数据'}

DECIMATE_DEFAULT_FACES = 900
DECIMATE_MIN_FACES = 50
DECIMATE_MAX_FACES = 2000000
ASSEMBLE_DEFAULT_FACES = 10000
BLENDER_DECIMATE_TIMEOUT = 300

NODE_TYPES = {
    'prompt': {'in': {}, 'out': {'text': 'text'}},
    'textToImage': {'in': {'text': 'text'}, 'out': {'image': 'image'}},
    'imageTo3D': {'in': {'image': 'image'}, 'out': {'mesh': 'mesh'}},
    'blueprint': {'in': {'image': 'image', 'spec': 'spec', 'text': 'text'},
                  'out': {'spec': 'spec', 'measure': 'measure'}},
    'threeView': {'in': {'image': 'image', 'spec': 'spec', 'text': 'text'},
                  'out': {'sheet': 'image', 'front': 'image', 'side': 'image',
                          'top': 'image'}},
    'partImage': {'in': {'text': 'text', 'image': 'image', 'spec': 'spec'},
                  'out': {'image': 'image', 'ports': 'ports'}},
    'partModel': {'in': {'image': 'image', 'spec': 'spec', 'ports': 'ports'},
                  'out': {'part': 'part', 'mesh': 'mesh', 'assembly': 'assembly'}},
    'assemble': {'in': {'text': 'text', 'part': 'part', 'image': 'image'}, 'out': {'mesh': 'mesh'}},
    'decimate': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh', 'part': 'part'}},
    'styleApply': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'uv': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'lod': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'collision': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'animation': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'metadata': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'validate': {'in': {'mesh': 'mesh'}, 'out': {'report': 'report'}},
    'manualEdit': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'variant': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
    'imageExport': {'in': {'image': 'image'}, 'out': {}},
    'export': {'in': {'mesh': 'mesh', 'report': 'report'}, 'out': {}},
}


LOCAL_STAGE_TYPES = ('uv', 'lod', 'collision', 'animation', 'metadata')
PROVIDER_TYPES = ('textToImage', 'imageTo3D', 'partImage', 'partModel',
                  'blueprint', 'threeView')
# 组装要接多件单件模型；其余输入口仍只允许一条连线
MULTI_INPUTS = {('assemble', 'part')}


def _digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


_GRAPH_LOCKS = {}
_GRAPH_LOCKS_GUARD = threading.Lock()


def _graph_lock(root):
    """同一资产的图读改写必须串行；锁按存档目录复用，不跨资产阻塞。"""
    key = os.path.realpath(root)
    with _GRAPH_LOCKS_GUARD:
        lock = _GRAPH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _GRAPH_LOCKS[key] = lock
        return lock


def _graph_hashes(graph, by_id=None, order=None):
    if by_id is None or order is None:
        by_id, order = validate_graph(graph)
    previous, hashes = {}, {}
    for node_id in order:
        node = by_id[node_id]
        upstream = [edge for edge in graph['edges'] if edge['to'] == node_id]
        input_hash = _digest([(edge, previous.get(edge['from'])) for edge in upstream])
        param_hash = _digest({'type': node['type'], 'params': node.get('params', {})})
        signature = _digest([input_hash, param_hash])
        hashes[node_id] = (input_hash, param_hash, signature)
        previous[node_id] = signature
    return hashes


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
    incoming, identities = set(), set()
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
        identity = (source['id'], edge['out'], target['id'], edge['in'])
        if identity in identities:
            raise ValueError('连线重复')
        identities.add(identity)
        key = (target['id'], edge['in'])
        if key in incoming and (target['type'], edge['in']) not in MULTI_INPUTS:
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


def normalize_kind(kind):
    kind = str(kind or 'machine')
    if kind not in ASSET_KIND_DIRS:
        raise ValueError('资产类型非法: %s' % kind)
    return kind


def _valid_asset_id(asset_id):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', str(asset_id or '')):
        raise ValueError('资产 ID 非法')
    return asset_id


def _manifest_source_dir(forgeworks_root, asset_id):
    """manifest 的 sourceDir 是资产目录的唯一真相；独立加载时不引入 fw_project。"""
    try:
        with open(os.path.join(forgeworks_root, '_Sync', 'manifest.json'), encoding='utf-8') as stream:
            manifest = json.load(stream)
    except (OSError, ValueError):
        return None
    record = (manifest.get('assets') or {}).get(asset_id) or {}
    source_dir = record.get('sourceDir')
    if not isinstance(source_dir, str) or not source_dir.strip():
        return None
    source_dir = source_dir.strip().strip('/')
    joined = os.path.join(forgeworks_root, source_dir)
    root = os.path.realpath(forgeworks_root)
    if os.path.commonpath((root, os.path.realpath(joined))) != root or not os.path.isdir(joined):
        return None
    return joined


def _manifest_asset(forgeworks_root, asset_id, kind):
    try:
        with open(os.path.join(forgeworks_root, '_Sync', 'manifest.json'), encoding='utf-8') as stream:
            manifest = json.load(stream)
    except (OSError, ValueError):
        return {}
    record = (manifest.get('assets') or {}).get(asset_id)
    if not isinstance(record, dict) or record.get('kind') != kind:
        return {}
    return record


def pipeline_root(forgeworks_root, asset_id, kind='machine'):
    """存档落在资产自己的文件夹：_Source/<中文分类>/<名称>/pipeline/"""
    asset_id = _valid_asset_id(asset_id)
    kind = normalize_kind(kind)
    source_dir = _manifest_source_dir(forgeworks_root, asset_id)
    if source_dir:
        return os.path.normpath(os.path.join(source_dir, 'pipeline'))
    return os.path.normpath(os.path.join(forgeworks_root, '_Source',
                                         *ASSET_KIND_DIRS[kind].split('/'), asset_id, 'pipeline'))


def legacy_pipeline_root(forgeworks_root, asset_id):
    return os.path.join(forgeworks_root, '_Source', 'pipeline', _valid_asset_id(asset_id))


def _graph_path(forgeworks_root, asset_id, kind):
    return os.path.join(pipeline_root(forgeworks_root, asset_id, kind), 'graph.json')


def _read_graph_file(path):
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def load_graph(forgeworks_root, asset_id, kind='machine'):
    kind = normalize_kind(kind)
    try:
        graph = _read_graph_file(_graph_path(forgeworks_root, asset_id, kind))
    except FileNotFoundError:
        try:
            graph = _read_graph_file(os.path.join(legacy_pipeline_root(forgeworks_root, asset_id), 'graph.json'))
        except FileNotFoundError:
            graph = {'schemaVersion': 1, 'assetId': asset_id, 'revision': 0, 'nodes': [], 'edges': [], 'updatedAt': None}
    validate_graph(graph)
    return graph


def archive_info(forgeworks_root, asset_id, kind='machine'):
    kind = normalize_kind(kind)
    root = pipeline_root(forgeworks_root, asset_id, kind)
    exists = os.path.isfile(os.path.join(root, 'graph.json'))
    legacy = os.path.isfile(os.path.join(legacy_pipeline_root(forgeworks_root, asset_id), 'graph.json'))
    return {'kind': kind, 'path': os.path.relpath(root, forgeworks_root).replace(os.sep, '/'),
            'exists': exists, 'legacy': bool(legacy and not exists)}


def _migrate_legacy_outputs(forgeworks_root, asset_id, root):
    legacy_outputs = os.path.join(legacy_pipeline_root(forgeworks_root, asset_id), 'outputs')
    if not os.path.isdir(legacy_outputs):
        return
    target = os.path.join(root, 'outputs')
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(legacy_outputs):
        source = os.path.join(legacy_outputs, name)
        destination = os.path.join(target, name)
        if os.path.isfile(source) and not os.path.exists(destination):
            shutil.copy2(source, destination)


def _write_prompt(root, graph):
    text = next((str(node.get('params', {}).get('text', '')) for node in graph['nodes'] if node['type'] == 'prompt'), '')
    with open(os.path.join(root, 'prompt.txt'), 'w', encoding='utf-8') as stream:
        stream.write(text)


def _write_json_atomic(path, value):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix='.graph-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _write_graph(root, graph):
    _write_json_atomic(os.path.join(root, 'graph.json'), graph)
    _write_prompt(root, graph)


def _current_revision(path):
    try:
        with open(path, encoding='utf-8') as stream:
            return int((json.load(stream) or {}).get('revision') or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def save_graph(forgeworks_root, asset_id, graph, kind='machine'):
    by_id, order = validate_graph(graph)
    kind = normalize_kind(kind)
    root = pipeline_root(forgeworks_root, asset_id, kind)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, 'graph.json')
    with _graph_lock(root):
        _migrate_legacy_outputs(forgeworks_root, asset_id, root)
        graph = dict(graph, assetId=asset_id,
                     revision=max(_current_revision(path), int(graph.get('revision') or 0)) + 1,
                     updatedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        hashes = _graph_hashes(graph, by_id, order)
        for node_id in order:
            node = by_id[node_id]
            input_hash, param_hash, signature = hashes[node_id]
            old = node.get('result') or {}
            # 本地阶段由浏览器端推导，签名无法在 Python 侧复算，按来源标记保留
            ui_derived = old.get('source') == 'forgeworks-ui' and old.get('state') == 'done'
            preserved = ('done', 'queued', 'running', 'failed')
            matching = old.get('signature') == signature and old.get('state') in preserved
            state = 'done' if ui_derived else (old.get('state') if matching else 'dirty')
            node['result'] = dict(old, state=state, signature=signature,
                                  inputHash=input_hash, paramHash=param_hash)
        _write_graph(root, graph)
    return graph


def _merge_client_results(disk, incoming):
    """客户端只负责布局/参数/连线；Provider 与本地执行结果以服务端最新图为准。"""
    disk_nodes = {node.get('id'): node for node in disk.get('nodes') or [] if isinstance(node, dict)}
    for node in incoming.get('nodes') or []:
        if not isinstance(node, dict):
            continue
        old = disk_nodes.get(node.get('id'))
        if not old or old.get('type') != node.get('type'):
            continue
        incoming_result = node.get('result')
        if isinstance(incoming_result, dict) and incoming_result.get('source') == 'forgeworks-ui':
            continue
        old_result = old.get('result')
        if isinstance(old_result, dict):
            node['result'] = old_result


def save_client_graph(forgeworks_root, asset_id, incoming, kind='machine'):
    """整图保存不能覆盖并发写入的远程任务；在锁内与最新图合并结果后落盘。"""
    if not isinstance(incoming, dict):
        raise ValueError('graph 必须是对象')
    kind = normalize_kind(kind)
    validate_graph(incoming)
    root = pipeline_root(forgeworks_root, asset_id, kind)
    with _graph_lock(root):
        try:
            disk = load_graph(forgeworks_root, asset_id, kind)
        except (OSError, ValueError, TypeError):
            disk = None
        if disk:
            _merge_client_results(disk, incoming)
        return save_graph(forgeworks_root, asset_id, incoming, kind)


def update_graph(forgeworks_root, asset_id, kind, updater):
    """锁内读取最新图、应用更新再保存，网络/Blender 等慢操作必须在锁外完成。"""
    if not callable(updater):
        raise ValueError('updater 必须可调用')
    kind = normalize_kind(kind)
    root = pipeline_root(forgeworks_root, asset_id, kind)
    with _graph_lock(root):
        graph = load_graph(forgeworks_root, asset_id, kind)
        updated = updater(graph)
        if isinstance(updated, dict):
            graph = updated
        return save_graph(forgeworks_root, asset_id, graph, kind)


def resolve_output(forgeworks_root, asset_id, kind, filename):
    for base in (pipeline_root(forgeworks_root, asset_id, kind), legacy_pipeline_root(forgeworks_root, asset_id)):
        for folder in ('outputs', 'parts'):
            path = os.path.join(base, folder, filename)
            if os.path.isfile(path):
                return path
    return None


def _decimate_target(value):
    try:
        target = int(value)
    except (TypeError, ValueError):
        target = DECIMATE_DEFAULT_FACES
    return max(DECIMATE_MIN_FACES, min(DECIMATE_MAX_FACES, target))


def _assemble_target(value):
    """组装前每件目标面数；0 表示不减面，缺省则使用 10k。"""
    if value in (None, ''):
        return ASSEMBLE_DEFAULT_FACES
    try:
        target = int(value)
    except (TypeError, ValueError):
        return ASSEMBLE_DEFAULT_FACES
    return max(0, min(DECIMATE_MAX_FACES, target))


def _decimate_input(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    return _mesh_input(forgeworks_root, asset_id, kind, graph, by_id, node_id, '减面节点')


def _mesh_input(forgeworks_root, asset_id, kind, graph, by_id, node_id, label='节点'):
    root = os.path.realpath(pipeline_root(forgeworks_root, asset_id, kind))
    legacy = os.path.realpath(legacy_pipeline_root(forgeworks_root, asset_id))
    allowed = [root, legacy]
    candidates = []
    edge = next((edge for edge in graph['edges'] if edge.get('to') == node_id and edge.get('in') == 'mesh'), None)
    source = by_id.get(edge.get('from')) if edge else None
    result = (source or {}).get('result') or {}
    provider_output = (result.get('providerTask') or {}).get('output') or {}
    local_output = result.get('output') or {}
    for value in (provider_output.get('modelPath'), local_output.get('meshPath')):
        if value:
            name = os.path.basename(str(value))
            candidates.append(os.path.join(root, 'outputs', name))
            candidates.append(os.path.join(legacy, 'outputs', name))
    source_dir = _manifest_source_dir(forgeworks_root, asset_id)
    if source_dir:
        allowed.append(os.path.realpath(source_dir))
        record = _manifest_asset(forgeworks_root, asset_id, kind)
        files = record.get('files') if isinstance(record.get('files'), dict) else {}
        for item in files.get('mesh') or []:
            if isinstance(item, dict) and item.get('path'):
                candidates.append(os.path.join(source_dir, item['path']))
    for path in candidates:
        real = os.path.realpath(path)
        if os.path.isfile(real) and any(real == base or real.startswith(base + os.sep) for base in allowed):
            return real
    raise ValueError('%s没有可用的上游 GLB：请先生成模型或导出资产网格' % label)


def _upstream_text(graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'text'), None)
    source = by_id.get(edge.get('from')) if edge else None
    if not source:
        return ''
    text = ((source.get('result') or {}).get('output') or {}).get('text')
    if not text:
        text = (source.get('params') or {}).get('text')
    return str(text or '').strip()


def _part_display_name(graph, by_id, node_id, output):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'image'), None)
    source = by_id.get(edge.get('from')) if edge else None
    image_output = ((source or {}).get('result') or {}).get('output') or {}
    for candidate in (image_output.get('partName'), output.get('partName')):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return str((source or {}).get('id') or node_id)


def _mesh_source_node(graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'mesh'), None)
    return by_id.get(edge.get('from')) if edge else None


def _decimated_part(graph, by_id, node):
    """减面节点输出的是 GLB；名称/描述/来源仍取它上游的单件模型。"""
    result = node.get('result') or {}
    if result.get('state') != 'done':
        raise ValueError(result.get('state') or '未运行')
    output = result.get('output') or {}
    mesh_path = output.get('meshPath')
    if not mesh_path:
        raise ValueError('缺少减面结果')
    upstream = _mesh_source_node(graph, by_id, node.get('id'))
    if not upstream or upstream.get('type') != 'partModel':
        raise ValueError('上游不是单件模型')
    upstream_result = upstream.get('result') or {}
    task = upstream_result.get('providerTask') or {}
    task_output = task.get('output') if isinstance(task.get('output'), dict) else {}
    if task.get('state') != 'success':
        raise ValueError('单件模型%s' % (task.get('state') or '未运行'))
    if not task_output.get('modelPath'):
        raise ValueError('单件模型缺少模型路径')
    return {
        'id': upstream.get('id'),
        'name': _part_display_name(graph, by_id, upstream.get('id'), task_output),
        'description': str((upstream_result.get('output') or {}).get('description') or ''),
        'mesh': 'outputs/' + os.path.basename(str(mesh_path)),
    }


def _assemble_part_inputs(graph, by_id, node_id):
    edges = [edge for edge in graph['edges']
             if edge.get('to') == node_id and edge.get('in') == 'part']
    if not edges:
        raise ValueError('组装节点没有接入任何单件模型')
    parts, missing = [], []
    for edge in edges:
        source = by_id.get(edge.get('from')) or {}
        if source.get('type') == 'decimate':
            # 显式减面节点的输出才是组装输入；单件模型本身保持未减面。
            try:
                parts.append(_decimated_part(graph, by_id, source))
            except ValueError as error:
                missing.append('%s（%s）' % (source.get('id'), error))
            continue
        if source.get('type') != 'partModel':
            missing.append('%s（不支持的部件来源）' % (source.get('id') or edge.get('from')))
            continue
        result = source.get('result') or {}
        task = result.get('providerTask') or {}
        output = task.get('output') if isinstance(task.get('output'), dict) else {}
        model_path = output.get('modelPath')
        if task.get('state') != 'success':
            missing.append('%s（%s）' % (source.get('id'), task.get('state') or '未运行'))
            continue
        if not model_path:
            missing.append('%s（缺少模型路径）' % source.get('id'))
            continue
        # 上游单件图变了会把模型节点打回 dirty；旧模型不能继续装
        if result.get('state') not in ('done', None):
            missing.append('%s（上游已变更，需重新运行）' % source.get('id'))
            continue
        parts.append({
            'id': source.get('id'),
            'name': _part_display_name(graph, by_id, source.get('id'), output),
            'description': str((result.get('output') or {}).get('description') or ''),
            'mesh': str(model_path),
        })
    if not parts:
        raise ValueError('组装没有可用的单件模型：' + '、'.join(missing) + '；请先运行这些单件模型节点')
    return parts, missing


def _assemble_reference_image(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'image'), None)
    source = by_id.get(edge.get('from')) if edge else None
    if not source:
        return ''
    result = source.get('result') or {}
    task_output = (result.get('providerTask') or {}).get('output') or {}
    output = result.get('output') or {}
    image_path = task_output.get('imagePath') or output.get('imagePath')
    if not image_path:
        return ''
    return resolve_output(forgeworks_root, asset_id, kind, os.path.basename(str(image_path))) or ''


def _load_provider_config(value):
    if isinstance(value, dict):
        return value
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge_config.json')
    try:
        with open(path, encoding='utf-8') as stream:
            config = json.load(stream)
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


def spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'spec'), None)
    if not edge:
        return None
    source = by_id.get(edge.get('from'))
    if not source:
        raise ValueError('SPEC_MISSING: spec 上游节点不存在')
    result = source.get('result') or {}
    state = result.get('state')
    if result and state not in ('done', None):
        raise ValueError('SPEC_MISSING: 上游规格未就绪（%s）' % (state or '未运行'))
    output = result.get('output') or {}
    candidate = output.get('spec')
    if isinstance(candidate, dict):
        return fw_spec.validate_spec(candidate)
    spec_path = output.get('specPath') or 'spec.json'
    root = os.path.realpath(pipeline_root(forgeworks_root, asset_id, kind))
    path = os.path.realpath(os.path.join(root, str(spec_path)))
    if os.path.commonpath((root, path)) != root:
        raise ValueError('SPEC_INVALID: spec 路径必须位于管线目录内：%s' % spec_path)
    if not os.path.isfile(path):
        raise ValueError('SPEC_MISSING: 上游规格尚未生成：%s' % spec_path)
    return fw_spec.read_spec(path)


def ports_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'ports'), None)
    if edge:
        source = by_id.get(edge.get('from')) or {}
        output = (source.get('result') or {}).get('output') or {}
        ports = output.get('ports')
        if isinstance(ports, list):
            return ports
        raise ValueError('PORT_MISSING: ports 上游没有端口结果')
    spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    if not spec:
        return []
    role = part_role_for_node(graph, by_id, node_id)
    part = spec['parts'].get(role)
    return fw_spec.anchor_ports(part) if part else []


def part_role_for_node(graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'image'), None)
    source = by_id.get(edge.get('from')) if edge else None
    output = ((source or {}).get('result') or {}).get('output') or {}
    part_name = str(output.get('partName') or '')
    role = fw_spec.role_for_node(node_id, part_name)
    if not role:
        raise ValueError('PART_ROLE_MISSING: 无法从节点 %s 判断部件角色' % node_id)
    return role


def _decimate_with_blender(blender_path, source, output, target_faces):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fw_blender.py')
    with tempfile.TemporaryDirectory(prefix='forgeworks-decimate-') as temp_dir:
        report_path = os.path.join(temp_dir, 'report.json')
        try:
            completed = subprocess.run([
                blender_path, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', script, '--', '--mode', 'decimate',
                '--input', source, '--output', output, '--report', report_path,
                '--target-faces', str(target_faces),
            ], capture_output=True, text=True, timeout=BLENDER_DECIMATE_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ValueError('Blender 减面超时（%d 秒）' % BLENDER_DECIMATE_TIMEOUT)
        report = None
        try:
            with open(report_path, encoding='utf-8') as stream:
                report = json.load(stream)
        except (OSError, ValueError):
            report = None
        if not isinstance(report, dict):
            tail = (completed.stderr or completed.stdout or 'Blender 无输出')[-1000:]
            report = {'valid': False, 'errors': [tail]}
        if completed.returncode != 0:
            report['valid'] = False
        return report


FIT_TIMEOUT = 300


def _fit_with_blender(blender_path, plan):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fw_blender.py')
    with tempfile.TemporaryDirectory(prefix='forgeworks-fit-') as temp_dir:
        plan_path = os.path.join(temp_dir, 'fit.json')
        report_path = os.path.join(temp_dir, 'report.json')
        with open(plan_path, 'w', encoding='utf-8') as stream:
            json.dump(plan, stream, ensure_ascii=False)
        try:
            completed = subprocess.run([
                blender_path, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', script, '--', '--mode', 'fit', '--plan', plan_path,
                '--output', plan['output'], '--report', report_path,
            ], capture_output=True, text=True, timeout=FIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ValueError('Blender 校准超时（%d 秒）' % FIT_TIMEOUT)
        report = None
        try:
            with open(report_path, encoding='utf-8') as stream:
                report = json.load(stream)
        except (OSError, ValueError):
            report = None
        if not isinstance(report, dict):
            tail = (completed.stderr or completed.stdout or 'Blender 无输出')[-1000:]
            report = {'valid': False, 'errors': [tail]}
        if completed.returncode != 0:
            report['valid'] = False
        return report


def _attach_part_ports(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    if not spec:
        return
    node = by_id[node_id]
    result = node.setdefault('result', {})
    output = result.setdefault('output', {})
    role = fw_spec.role_for_node(node_id, output.get('partName') or '')
    part = spec['parts'].get(role)
    if not part:
        raise ValueError('PART_ROLE_MISSING: spec 中没有角色 %s' % (role or node_id))
    output['role'] = role
    output['ports'] = fw_spec.anchor_ports(part)


def _finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _finite_triplet(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    return all(_finite_number(item) for item in value)


def _valid_fit_port(port):
    if not isinstance(port, dict):
        return False
    if not all(_finite_triplet(port.get(key)) for key in ('pos', 'axis', 'normal')):
        return False
    if 'radiusM' in port and not _finite_number(port['radiusM']):
        return False
    return True


def _single_part_assembly(asset_id, node_id, role, mesh_path, ports):
    connectors = []
    for port in ports:
        connectors.append({
            'id': '%s:%s' % (role, port.get('id')),
            'owner': role,
            'frame': {'pos': list(port.get('pos') or [0, 0, 0]),
                      'axis': list(port.get('axis') or [1, 0, 0]),
                      'normal': list(port.get('normal') or [0, 0, 1])},
            'radiusM': port.get('radiusM', 0.02),
        })
    return {
        'schemaVersion': 1,
        'assemblyId': 'asm_' + node_id,
        'assetId': asset_id,
        'meshPath': mesh_path,
        'parts': [{'partId': node_id, 'role': role, 'meshPath': mesh_path}],
        'connectors': connectors,
        'mates': [],
        'warnings': [],
    }


def _fit_is_current(forgeworks_root, asset_id, kind, node, spec):
    result = node.get('result') or {}
    task = result.get('providerTask') or {}
    output = result.get('output') or {}
    params = node.get('params') or {}
    fit = output.get('fit') if isinstance(output.get('fit'), dict) else {}
    mesh_path = output.get('meshPath')
    if not mesh_path or output.get('fitSourceTaskId') != task.get('taskId'):
        return False
    if output.get('fitSpecHash') != _digest(spec):
        return False
    if fit.get('fitMode') != str(params.get('fitMode') or 'uniform'):
        return False
    if bool(fit.get('ground')) != bool(params.get('ground')):
        return False
    return bool(resolve_output(forgeworks_root, asset_id, kind,
                               os.path.basename(str(mesh_path))))


def _fit_part_model(forgeworks_root, asset_id, kind, graph, by_id, node_id, blender_path):
    node = by_id[node_id]
    result = node.setdefault('result', {})
    task = result.get('providerTask') or {}
    task_output = task.get('output') if isinstance(task.get('output'), dict) else {}
    model_path = task_output.get('modelPath')
    if not model_path:
        raise ValueError('SPEC_MISSING: 单件模型没有可校准的 GLB')
    source = resolve_output(forgeworks_root, asset_id, kind, os.path.basename(str(model_path)))
    if not source:
        raise ValueError('SPEC_MISSING: 单件模型文件不存在：%s' % model_path)
    if not blender_path:
        raise ValueError('未找到 Blender：请在 tools/bridge_config.json 配置 blender.path')
    spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    role = part_role_for_node(graph, by_id, node_id)
    part = spec['parts'].get(role)
    if not part:
        raise ValueError('PART_ROLE_MISSING: spec 中没有角色 %s' % role)
    params = node.get('params') or {}
    fit_mode = str(params.get('fitMode') or 'uniform')
    ground = bool(params.get('ground'))
    ports = ports_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    # Blender 按 anchor 解算米制坐标，端口表里存的是 anchorNorm
    plan_ports = []
    for port in ports:
        item = dict(port)
        if 'anchor' not in item and 'anchorNorm' in item:
            item['anchor'] = item['anchorNorm']
        plan_ports.append(item)
    root = pipeline_root(forgeworks_root, asset_id, kind)
    outputs_dir = os.path.join(root, 'outputs')
    os.makedirs(outputs_dir, exist_ok=True)
    filename = 'model_fit_%s.glb' % node_id
    output = os.path.join(outputs_dir, filename)
    plan = {
        'input': source,
        'output': output,
        'targetSizeM': list(part['sizeM']),
        'fitMode': fit_mode,
        'ground': ground,
        'forward': part.get('forward', '+X'),
        'ports': plan_ports,
    }
    report = _fit_with_blender(blender_path, plan)
    if not isinstance(report, dict):
        raise ValueError('FIT_ASPECT_MISMATCH: Blender 校准报告格式无效')
    if not report.get('valid'):
        errors = report.get('errors')
        message = '; '.join(str(item) for item in errors) if isinstance(errors, list) else ''
        raise ValueError('FIT_ASPECT_MISMATCH: %s' % (message or 'Blender 校准失败'))
    source_fit = report.get('fit')
    fitted_ports = report.get('ports')
    aspect_error = source_fit.get('aspectError') if isinstance(source_fit, dict) else None
    if (not _finite_number(aspect_error)
            or not isinstance(fitted_ports, list)
            or not all(_valid_fit_port(port) for port in fitted_ports)):
        raise ValueError('FIT_ASPECT_MISMATCH: Blender 校准报告格式无效')
    fit = dict(source_fit)
    if fit_mode == 'uniform' and aspect_error > 0.15:
        raise ValueError('FIT_ASPECT_MISMATCH: 均匀校准无法消除长宽高差异（%.1f%%）'
                         % (aspect_error * 100))
    warnings = []
    if aspect_error > 0.05:
        warnings.append('校准后仍有 %.1f%% 轴向偏差' % (aspect_error * 100))
    if fit.get('ambiguous'):
        warnings.append('FIT_ORIENTATION_AMBIGUOUS: 多个朝向评分接近，请检查 rotationDeg')
    fit['targetSizeM'] = list(part['sizeM'])
    fit['forward'] = part.get('forward', '+X')
    fit['fitMode'] = fit_mode
    fit['ground'] = ground
    relative = 'outputs/' + filename
    assembly = _single_part_assembly(asset_id, node_id, role, relative, fitted_ports)
    assembly['warnings'] = warnings
    output_data = result.setdefault('output', {})
    output_data.update({
        'role': role,
        'meshPath': relative,
        'fit': fit,
        'ports': fitted_ports,
        'assembly': assembly,
        'fitSourceTaskId': task.get('taskId'),
        'fitSpecHash': _digest(spec),
        'engine': 'blender',
        'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    })
    result['state'] = 'done'
    result.pop('error', None)
    return output_data


def _three_view_source(forgeworks_root, asset_id, kind, node):
    result = node.get('result') or {}
    task = result.get('providerTask') or {}
    task_output = task.get('output') if isinstance(task.get('output'), dict) else {}
    image_path = task_output.get('imagePath')
    if not image_path:
        return None
    return resolve_output(forgeworks_root, asset_id, kind, os.path.basename(str(image_path)))


def _process_three_view_node(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    node = by_id[node_id]
    result = node.setdefault('result', {})
    sheet = _three_view_source(forgeworks_root, asset_id, kind, node)
    if not sheet:
        return None
    root = os.path.realpath(pipeline_root(forgeworks_root, asset_id, kind))
    outputs_dir = os.path.join(root, 'outputs')
    params = node.get('params') or {}
    try:
        spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    except ValueError:
        spec = None
    processed = fw_views.process_three_view(
        sheet, outputs_dir, node_id, spec=spec,
        measure=(result.get('output') or {}).get('measure'),
        annotate=bool(params.get('annotate')))

    def relative(path):
        if not path:
            return ''
        return os.path.relpath(os.path.realpath(path), root).replace(os.sep, '/')

    output = result.setdefault('output', {})
    output.update({
        'sheetPath': relative(processed['sheetPath']),
        'frontPath': relative(processed['frontPath']),
        'sidePath': relative(processed['sidePath']),
        'topPath': relative(processed['topPath']),
        'annotatedPath': relative(processed['annotatedPath']),
        'warnings': processed['warnings'],
    })
    return output


def execute_local(forgeworks_root, asset_id, target_id=None, through=False, kind='machine',
                  blender_path=None, provider_config=None):
    kind = normalize_kind(kind)
    graph = load_graph(forgeworks_root, asset_id, kind)
    by_id, order = validate_graph(graph)
    snapshot_hashes = _graph_hashes(graph, by_id, order)
    if target_id and target_id not in by_id:
        raise ValueError('目标节点不存在')
    if target_id and not through:
        order = [target_id]
    elif target_id:
        order = order[:order.index(target_id) + 1]
    outputs = {}
    for node_id in order:
        node = by_id[node_id]
        if node['type'] in PROVIDER_TYPES:
            node.setdefault('result', {})
            task = node['result'].get('providerTask') or {}
            if task.get('state') == 'success':
                # 保留 dirty：上游或参数变了，旧产物不能当作现成结果
                if node['result'].get('state') != 'dirty':
                    node['result']['state'] = 'done'
                task_output = task.get('output') if isinstance(task.get('output'), dict) else {}
                if node['type'] == 'blueprint':
                    output = dict(node['result'].get('output') or {})
                    if isinstance(task_output.get('spec'), dict):
                        output.update(spec=task_output['spec'],
                                      specPath=task_output.get('specPath', 'spec.json'))
                    if isinstance(task_output.get('measure'), dict):
                        output['measure'] = task_output['measure']
                        output['scope'] = 'part'
                        output['role'] = task_output.get('role') or output.get('role', '')
                    node['result']['output'] = output
                if node['type'] == 'partImage':
                    try:
                        _attach_part_ports(forgeworks_root, asset_id, kind, graph, by_id, node_id)
                    except ValueError as error:
                        warnings = node['result'].setdefault('warnings', [])
                        if str(error) not in warnings:
                            warnings.append(str(error))
                if node['type'] == 'threeView':
                    try:
                        _process_three_view_node(forgeworks_root, asset_id, kind,
                                                 graph, by_id, node_id)
                    except (ValueError, OSError) as error:
                        warnings = node['result'].setdefault('warnings', [])
                        if str(error) not in warnings:
                            warnings.append(str(error))
                if node['type'] == 'partModel':
                    try:
                        part_spec = spec_for_node(forgeworks_root, asset_id, kind,
                                                  graph, by_id, node_id)
                    except ValueError as error:
                        node['result']['state'] = 'blocked'
                        node['result']['error'] = str(error)
                        part_spec = None
                    if part_spec and not _fit_is_current(forgeworks_root, asset_id, kind,
                                                         node, part_spec):
                        try:
                            _fit_part_model(forgeworks_root, asset_id, kind, graph,
                                            by_id, node_id, blender_path)
                        except (ValueError, OSError) as error:
                            node['result']['state'] = 'blocked'
                            node['result']['error'] = str(error)
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
        elif node['type'] in LOCAL_STAGE_TYPES:
            result = node.setdefault('result', {})
            if not (result.get('source') == 'forgeworks-ui' and result.get('state') == 'done'):
                result['state'] = 'blocked'
                result['error'] = '该阶段由 Forgeworks 浏览器端资产图层推导；请在工具里运行此节点'
        elif node['type'] == 'assemble':
            result = node.setdefault('result', {})
            try:
                if not blender_path:
                    raise ValueError('未找到 Blender：请在 tools/bridge_config.json 配置 blender.path')
                parts, missing = _assemble_part_inputs(graph, by_id, node_id)
                root = os.path.realpath(pipeline_root(forgeworks_root, asset_id, kind))
                outputs_dir = os.path.join(root, 'outputs')
                os.makedirs(outputs_dir, exist_ok=True)
                filename = 'model_assembly_%s.glb' % node_id
                params = node.get('params') or {}
                decimate_faces = _assemble_target(params.get('decimateFaces'))
                layout_mode = str(params.get('layoutMode') or 'coherent')
                assembly_prompt = _upstream_text(graph, by_id, node_id)
                reference = _assemble_reference_image(
                    forgeworks_root, asset_id, kind, graph, by_id, node_id)
                relative_reference = (os.path.relpath(os.path.realpath(reference), root).replace(os.sep, '/')
                                      if reference else '')
                has_image_edge = any(edge.get('to') == node_id and edge.get('in') == 'image'
                                     for edge in graph['edges'])
                hints, vision = {}, {'enabled': False, 'state': 'no-reference'}
                if reference and bool(params.get('visionAssist', True)):
                    try:
                        hints, vision_meta = fw_providers.analyze_layout(
                            _load_provider_config(provider_config), reference, parts,
                            prompt=assembly_prompt,
                            model=str(params.get('visionModel') or ''))
                        vision = dict({'enabled': True, 'state': 'done',
                                       'referenceImage': relative_reference}, **vision_meta)
                    except (ValueError, RuntimeError, OSError) as error:
                        vision = {'enabled': True, 'state': 'failed',
                                  'referenceImage': relative_reference,
                                  'error': str(error)[:300]}
                        warnings_note = '整体图视觉分析失败，已按默认规则组装：%s' % str(error)[:200]
                    else:
                        warnings_note = ''
                elif reference:
                    vision = {'enabled': False, 'state': 'disabled',
                              'referenceImage': relative_reference}
                    warnings_note = ''
                elif has_image_edge:
                    vision = {'enabled': True, 'state': 'blocked',
                              'error': '整体效果图未就绪，本次未做视觉分析'}
                    warnings_note = '整体效果图未就绪，本次未做视觉分析'
                else:
                    warnings_note = ''
                assembled = fw_parts.assemble_parts(
                    parts, os.path.join(outputs_dir, filename),
                    os.path.join(root, 'parts', 'layout_%s.json' % node_id), root,
                    assembly_prompt=assembly_prompt,
                    reset=bool(params.get('resetLayout')),
                    blender_path=blender_path, asset_id=asset_id, node_id=node_id,
                    preserve_absent=bool(missing), decimate_faces=decimate_faces,
                    layout_mode=layout_mode, layout_hints=hints,
                    reference_image=relative_reference)
                warnings = list(assembled['warnings'])
                if warnings_note:
                    warnings.insert(0, warnings_note)
                if missing:
                    warnings.insert(0, '结果残缺：%d 个单件未就绪，未参与组装：%s'
                                    % (len(missing), '、'.join(missing)))
                result['state'] = 'done'
                result['output'] = {
                    'meshPath': assembled['meshPath'],
                    'parts': assembled['parts'],
                    'triangles': assembled.get('triangles'),
                    'trianglesBefore': assembled.get('trianglesBefore'),
                    'decimateFaces': assembled.get('decimateFaces'),
                    'decimated': assembled.get('decimated') or [],
                    'layoutMode': assembled.get('layoutMode'),
                    'layoutHints': assembled.get('layoutHints') or {},
                    'referenceImage': relative_reference,
                    'vision': vision,
                    'layoutPath': os.path.relpath(assembled['layoutPath'], root).replace(os.sep, '/'),
                    'warnings': warnings,
                    'partial': bool(missing),
                    'missingParts': missing,
                    'engine': 'blender',
                    'updatedAt': assembled['updatedAt'],
                }
                result.pop('error', None)
            except (ValueError, OSError) as error:
                result['state'] = 'blocked'
                result['error'] = str(error)
        elif node['type'] == 'decimate':
            result = node.setdefault('result', {})
            try:
                target = _decimate_target(node.get('params', {}).get('targetFaces'))
                source_path = _decimate_input(forgeworks_root, asset_id, kind, graph, by_id, node_id)
                if not blender_path:
                    raise ValueError('未找到 Blender：请在 tools/bridge_config.json 配置 blender.path')
                outputs_dir = os.path.join(pipeline_root(forgeworks_root, asset_id, kind), 'outputs')
                os.makedirs(outputs_dir, exist_ok=True)
                filename = 'model_decimate_%s_%d.glb' % (node_id, target)
                report = _decimate_with_blender(blender_path, source_path, os.path.join(outputs_dir, filename), target)
                if not report.get('valid'):
                    raise ValueError('; '.join(report.get('errors') or []) or 'Blender 减面失败')
                result['state'] = 'done'
                result['output'] = {
                    'meshPath': filename,
                    'trianglesBefore': int(report.get('trianglesBefore') or 0),
                    'trianglesAfter': int(report.get('trianglesAfter') or 0),
                    'targetFaces': int(report.get('targetFaces') or target),
                    'ratio': report.get('ratio'),
                    'engine': 'blender',
                    'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                }
                result.pop('error', None)
            except (ValueError, OSError) as error:
                result['state'] = 'blocked'
                result['error'] = str(error)
        elif node['type'] == 'imageExport':
            edge = next((item for item in graph['edges'] if item.get('to') == node_id and item.get('in') == 'image'), None)
            source = by_id.get(edge.get('from')) if edge else None
            source_output = (((source or {}).get('result') or {}).get('providerTask') or {}).get('output') or {}
            image_path = source_output.get('imagePath')
            if image_path and os.path.isfile(os.path.join(pipeline_root(forgeworks_root, asset_id, kind), image_path)):
                node.setdefault('result', {})['state'] = 'done'
                node['result']['output'] = {'imagePath': image_path}
            else:
                node.setdefault('result', {})['state'] = 'blocked'
                node['result']['error'] = '上游图片任务尚未成功，图像输出不可用'
        elif node['type'] == 'export':
            result = node.setdefault('result', {})
            record = _manifest_asset(forgeworks_root, asset_id, kind)
            files = record.get('files') if isinstance(record.get('files'), dict) else {}
            required = ('mesh', 'icon') if kind == 'machine' else ('icon',)
            missing = [role for role in required if not files.get(role)]
            if record and not missing:
                result['state'] = 'done'
                result['output'] = {
                    'sourceDir': record.get('sourceDir'),
                    'files': {
                        role: [item.get('path') for item in files[role] if isinstance(item, dict)]
                        for role in required
                    },
                    'exportedAt': record.get('exportedAt'),
                }
            else:
                result['state'] = 'blocked'
                result['error'] = '尚未导出到项目；请先完成生成与同步导出'
        else:
            node.setdefault('result', {})['state'] = 'blocked'
            node['result']['error'] = '该处理器尚未实现；为避免产生虚假结果，此节点不标记为完成'
        outputs[node_id] = node.get('result', {}).get('output')
    root = pipeline_root(forgeworks_root, asset_id, kind)
    os.makedirs(root, exist_ok=True)
    with _graph_lock(root):
        try:
            latest = load_graph(forgeworks_root, asset_id, kind)
        except (OSError, ValueError, TypeError):
            latest = graph
        latest_by_id, latest_order = validate_graph(latest)
        latest_hashes = _graph_hashes(latest, latest_by_id, latest_order)
        changed = False
        for node_id in order:
            computed = by_id[node_id]
            current = latest_by_id.get(node_id)
            if not current or current.get('type') != computed.get('type'):
                continue
            # 执行期间参数/连线变了，这次本地结果不能覆盖最新图
            if snapshot_hashes[node_id][2] != latest_hashes[node_id][2]:
                continue
            # 远程任务由 submit/poll 维护；本地运行只合并派生产物，不覆盖任务本身
            if computed['type'] in PROVIDER_TYPES:
                current_task = (current.get('result') or {}).get('providerTask') or {}
                if current_task:
                    computed_result = computed.get('result') or {}
                    current_result = current.setdefault('result', {})
                    merged = dict(current_result)
                    merged.update({key: computed_result[key]
                                   for key in ('state', 'warnings')
                                   if key in computed_result})
                    if 'error' in computed_result:
                        merged['error'] = computed_result['error']
                    else:
                        merged.pop('error', None)
                    derived = (computed_result.get('output')
                               if isinstance(computed_result.get('output'), dict) else {})
                    if derived:
                        merged['output'] = dict(current_result.get('output') or {}, **derived)
                    # 无变化时不写盘，避免旧图仅因重跑就递增 revision
                    if merged != current_result:
                        current['result'] = merged
                        changed = True
                    continue
            current['result'] = computed.get('result')
            changed = True
        if changed:
            latest = dict(latest, revision=int(latest.get('revision') or 0) + 1,
                          updatedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            _write_graph(root, latest)
        graph = latest
    return {'graph': graph, 'ran': order}


def starter_graph(asset_id, template='machine'):
    nodes = [
        {'id': 'prompt', 'type': 'prompt', 'x': 60, 'y': 100, 'params': {'text': ''}},
        {'id': 'image', 'type': 'textToImage', 'x': 300, 'y': 100, 'params': {'provider': 'tripo'}},
        {'id': 'model', 'type': 'imageTo3D', 'x': 540, 'y': 100, 'params': {'provider': 'tripo', 'texture': False}},
        {'id': 'style', 'type': 'styleApply', 'x': 780, 'y': 100, 'params': {}},
        {'id': 'uv', 'type': 'uv', 'x': 1020, 'y': 100, 'params': {'mode': 'primitive'}},
        {'id': 'lod', 'type': 'lod', 'x': 1260, 'y': 100, 'params': {'levels': 3}},
        {'id': 'collision', 'type': 'collision', 'x': 1500, 'y': 100, 'params': {'type': 'box'}},
        {'id': 'animation', 'type': 'animation', 'x': 1740, 'y': 100, 'params': {'mode': 'ue-rebuild'}},
        {'id': 'metadata', 'type': 'metadata', 'x': 1980, 'y': 100, 'params': {'formats': ['csv', 'json']}},
        {'id': 'validate', 'type': 'validate', 'x': 2220, 'y': 100, 'params': {'maxTriangles': 20000}},
        {'id': 'export', 'type': 'export', 'x': 2460, 'y': 100, 'params': {}},
    ]
    edges = [{'from': 'prompt', 'out': 'text', 'to': 'image', 'in': 'text'},
             {'from': 'image', 'out': 'image', 'to': 'model', 'in': 'image'},
             {'from': 'model', 'out': 'mesh', 'to': 'style', 'in': 'mesh'},
             {'from': 'style', 'out': 'mesh', 'to': 'uv', 'in': 'mesh'},
             {'from': 'uv', 'out': 'mesh', 'to': 'lod', 'in': 'mesh'},
             {'from': 'lod', 'out': 'mesh', 'to': 'collision', 'in': 'mesh'},
             {'from': 'collision', 'out': 'mesh', 'to': 'animation', 'in': 'mesh'},
             {'from': 'animation', 'out': 'mesh', 'to': 'metadata', 'in': 'mesh'},
             {'from': 'metadata', 'out': 'mesh', 'to': 'validate', 'in': 'mesh'},
             {'from': 'validate', 'out': 'report', 'to': 'export', 'in': 'report'},
             {'from': 'metadata', 'out': 'mesh', 'to': 'export', 'in': 'mesh'}]
    if template == 'parts':
        nodes = [
            {'id': 'prompt_overall', 'type': 'prompt', 'x': 60, 'y': 0, 'params': {'text': ''}},
            {'id': 'overall', 'type': 'textToImage', 'x': 300, 'y': 0,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'prompt_body', 'type': 'prompt', 'x': 60, 'y': 420, 'params': {'text': ''}},
            {'id': 'partImage_body', 'type': 'partImage', 'x': 540, 'y': 420,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'partModel_body', 'type': 'partModel', 'x': 780, 'y': 420,
             'params': {'provider': 'ark', 'texture': False, 'faceLimit': 3000}},
            {'id': 'prompt_roof', 'type': 'prompt', 'x': 60, 'y': 840, 'params': {'text': ''}},
            {'id': 'partImage_roof', 'type': 'partImage', 'x': 540, 'y': 840,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'partModel_roof', 'type': 'partModel', 'x': 780, 'y': 840,
             'params': {'provider': 'ark', 'texture': False, 'faceLimit': 3000}},
            {'id': 'prompt_wheel', 'type': 'prompt', 'x': 60, 'y': 1260, 'params': {'text': ''}},
            {'id': 'partImage_wheel', 'type': 'partImage', 'x': 540, 'y': 1260,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'partModel_wheel', 'type': 'partModel', 'x': 780, 'y': 1260,
             'params': {'provider': 'ark', 'texture': False, 'faceLimit': 3000}},
            {'id': 'prompt_door', 'type': 'prompt', 'x': 60, 'y': 1680, 'params': {'text': ''}},
            {'id': 'partImage_door', 'type': 'partImage', 'x': 540, 'y': 1680,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'partModel_door', 'type': 'partModel', 'x': 780, 'y': 1680,
             'params': {'provider': 'ark', 'texture': False, 'faceLimit': 3000}},
            {'id': 'prompt_side_window', 'type': 'prompt', 'x': 60, 'y': 2100, 'params': {'text': ''}},
            {'id': 'partImage_side_window', 'type': 'partImage', 'x': 540, 'y': 2100,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'partModel_side_window', 'type': 'partModel', 'x': 780, 'y': 2100,
             'params': {'provider': 'ark', 'texture': False, 'faceLimit': 3000}},
            {'id': 'prompt_rear_window', 'type': 'prompt', 'x': 60, 'y': 2520, 'params': {'text': ''}},
            {'id': 'partImage_rear_window', 'type': 'partImage', 'x': 540, 'y': 2520,
             'params': {'provider': 'ark', 'size': '1K', 'outputFormat': 'png'}},
            {'id': 'partModel_rear_window', 'type': 'partModel', 'x': 780, 'y': 2520,
             'params': {'provider': 'ark', 'texture': False, 'faceLimit': 3000}},
            {'id': 'prompt_assemble', 'type': 'prompt', 'x': 60, 'y': 2940, 'params': {'text': ''}},
            {'id': 'assemble', 'type': 'assemble', 'x': 1260, 'y': 1470,
             'params': {'resetLayout': False, 'decimateFaces': 0, 'visionAssist': True}},
        ]
        # 每个单件模型先经过显式减面节点，再把减面结果送进组装节点。
        for index, part in enumerate(('body', 'roof', 'wheel', 'door',
                                      'side_window', 'rear_window')):
            nodes.append({'id': 'decimate_' + part, 'type': 'decimate',
                          'x': 1020, 'y': 420 + index * 420,
                          'params': {'targetFaces': ASSEMBLE_DEFAULT_FACES}})
        for index, (node_id, node_type, params) in enumerate([
                ('style', 'styleApply', {'mode': 'primitive'}),
                ('uv', 'uv', {'mode': 'primitive'}),
                ('lod', 'lod', {'levels': 3}),
                ('collision', 'collision', {'type': 'box'}),
                ('animation', 'animation', {'mode': 'ue-rebuild'}),
                ('metadata', 'metadata', {'formats': ['csv', 'json']}),
                ('validate', 'validate', {'maxTriangles': 20000}),
                ('export', 'export', {})]):
            nodes.append({'id': node_id, 'type': node_type, 'x': 1500 + index * 240, 'y': 1470,
                          'params': params})
        edges = [
            {'from': 'prompt_overall', 'out': 'text', 'to': 'overall', 'in': 'text'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_roof', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_wheel', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_door', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_side_window', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_rear_window', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'assemble', 'in': 'image'},
            {'from': 'prompt_body', 'out': 'text', 'to': 'partImage_body', 'in': 'text'},
            {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
            {'from': 'partModel_body', 'out': 'mesh', 'to': 'decimate_body', 'in': 'mesh'},
            {'from': 'decimate_body', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_roof', 'out': 'text', 'to': 'partImage_roof', 'in': 'text'},
            {'from': 'partImage_roof', 'out': 'image', 'to': 'partModel_roof', 'in': 'image'},
            {'from': 'partModel_roof', 'out': 'mesh', 'to': 'decimate_roof', 'in': 'mesh'},
            {'from': 'decimate_roof', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_wheel', 'out': 'text', 'to': 'partImage_wheel', 'in': 'text'},
            {'from': 'partImage_wheel', 'out': 'image', 'to': 'partModel_wheel', 'in': 'image'},
            {'from': 'partModel_wheel', 'out': 'mesh', 'to': 'decimate_wheel', 'in': 'mesh'},
            {'from': 'decimate_wheel', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_door', 'out': 'text', 'to': 'partImage_door', 'in': 'text'},
            {'from': 'partImage_door', 'out': 'image', 'to': 'partModel_door', 'in': 'image'},
            {'from': 'partModel_door', 'out': 'mesh', 'to': 'decimate_door', 'in': 'mesh'},
            {'from': 'decimate_door', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_side_window', 'out': 'text', 'to': 'partImage_side_window', 'in': 'text'},
            {'from': 'partImage_side_window', 'out': 'image', 'to': 'partModel_side_window', 'in': 'image'},
            {'from': 'partModel_side_window', 'out': 'mesh', 'to': 'decimate_side_window', 'in': 'mesh'},
            {'from': 'decimate_side_window', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_rear_window', 'out': 'text', 'to': 'partImage_rear_window', 'in': 'text'},
            {'from': 'partImage_rear_window', 'out': 'image', 'to': 'partModel_rear_window', 'in': 'image'},
            {'from': 'partModel_rear_window', 'out': 'mesh', 'to': 'decimate_rear_window', 'in': 'mesh'},
            {'from': 'decimate_rear_window', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_assemble', 'out': 'text', 'to': 'assemble', 'in': 'text'},
            {'from': 'assemble', 'out': 'mesh', 'to': 'style', 'in': 'mesh'},
            {'from': 'style', 'out': 'mesh', 'to': 'uv', 'in': 'mesh'},
            {'from': 'uv', 'out': 'mesh', 'to': 'lod', 'in': 'mesh'},
            {'from': 'lod', 'out': 'mesh', 'to': 'collision', 'in': 'mesh'},
            {'from': 'collision', 'out': 'mesh', 'to': 'animation', 'in': 'mesh'},
            {'from': 'animation', 'out': 'mesh', 'to': 'metadata', 'in': 'mesh'},
            {'from': 'metadata', 'out': 'mesh', 'to': 'validate', 'in': 'mesh'},
            {'from': 'validate', 'out': 'report', 'to': 'export', 'in': 'report'},
            {'from': 'metadata', 'out': 'mesh', 'to': 'export', 'in': 'mesh'},
        ]
    elif template == 'icon':
        nodes = [nodes[0], nodes[1], {'id': 'imageExport', 'type': 'imageExport', 'x': 600, 'y': 100, 'params': {}}]
        edges = [{'from': 'prompt', 'out': 'text', 'to': 'image', 'in': 'text'},
                 {'from': 'image', 'out': 'image', 'to': 'imageExport', 'in': 'image'}]
    elif template == 'item':
        nodes[2]['params'].update({'faceLimit': 10000, 'smartLowPoly': True, 'texture': False})
    else:
        template = 'machine'
    return {'schemaVersion': 1, 'assetId': asset_id, 'template': template, 'revision': 0, 'nodes': nodes, 'edges': edges}
