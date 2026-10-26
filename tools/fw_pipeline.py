#!/usr/bin/env python3
"""Persistent, local-first asset pipeline graph services."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

import fw_parts

ASSET_KIND_DIRS = {'machine': '机器', 'item': '物品/图标', 'element': '元素', 'data': '数据'}

DECIMATE_DEFAULT_FACES = 900
DECIMATE_MIN_FACES = 50
DECIMATE_MAX_FACES = 2000000
BLENDER_DECIMATE_TIMEOUT = 300

NODE_TYPES = {
    'prompt': {'in': {}, 'out': {'text': 'text'}},
    'textToImage': {'in': {'text': 'text'}, 'out': {'image': 'image'}},
    'imageTo3D': {'in': {'image': 'image'}, 'out': {'mesh': 'mesh'}},
    'partImage': {'in': {'text': 'text', 'image': 'image'}, 'out': {'image': 'image'}},
    'partModel': {'in': {'image': 'image'}, 'out': {'part': 'part'}},
    'assemble': {'in': {'text': 'text', 'part': 'part'}, 'out': {'mesh': 'mesh'}},
    'decimate': {'in': {'mesh': 'mesh'}, 'out': {'mesh': 'mesh'}},
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
PROVIDER_TYPES = ('textToImage', 'imageTo3D', 'partImage', 'partModel')
# 组装要接多件单件模型；其余输入口仍只允许一条连线
MULTI_INPUTS = {('assemble', 'part')}


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
        return os.path.join(source_dir, 'pipeline')
    return os.path.join(forgeworks_root, '_Source', *ASSET_KIND_DIRS[kind].split('/'), asset_id, 'pipeline')


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


def save_graph(forgeworks_root, asset_id, graph, kind='machine'):
    by_id, order = validate_graph(graph)
    kind = normalize_kind(kind)
    graph = dict(graph, assetId=asset_id, revision=int(graph.get('revision') or 0) + 1,
                 updatedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    root = pipeline_root(forgeworks_root, asset_id, kind)
    os.makedirs(root, exist_ok=True)
    _migrate_legacy_outputs(forgeworks_root, asset_id, root)
    path = os.path.join(root, 'graph.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(graph, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    _write_prompt(root, graph)
    previous = {}
    for node_id in order:
        node = by_id[node_id]
        upstream = [edge for edge in graph['edges'] if edge['to'] == node_id]
        input_hash = _digest([(edge, previous.get(edge['from'])) for edge in upstream])
        param_hash = _digest({'type': node['type'], 'params': node.get('params', {})})
        signature = _digest([input_hash, param_hash])
        old = node.get('result') or {}
        # 本地阶段由浏览器端推导，签名无法在 Python 侧复算，按来源标记保留
        ui_derived = old.get('source') == 'forgeworks-ui' and old.get('state') == 'done'
        preserved = ('done', 'queued', 'running', 'failed')
        matching = old.get('signature') == signature and old.get('state') in preserved
        state = 'done' if ui_derived else (old.get('state') if matching else 'dirty')
        node['result'] = dict(old, state=state, signature=signature, inputHash=input_hash, paramHash=param_hash)
        previous[node_id] = signature
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(graph, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return graph


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


def _assemble_part_inputs(graph, by_id, node_id):
    edges = [edge for edge in graph['edges']
             if edge.get('to') == node_id and edge.get('in') == 'part']
    if not edges:
        raise ValueError('组装节点没有接入任何单件模型')
    parts, missing = [], []
    for edge in edges:
        source = by_id.get(edge.get('from')) or {}
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
    if missing:
        raise ValueError('组装缺少单件模型：' + '、'.join(missing) + '；请先运行这些单件模型节点')
    return parts


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


def execute_local(forgeworks_root, asset_id, target_id=None, through=False, kind='machine', blender_path=None):
    kind = normalize_kind(kind)
    graph = load_graph(forgeworks_root, asset_id, kind)
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
        if node['type'] in PROVIDER_TYPES:
            node.setdefault('result', {})
            task = node['result'].get('providerTask') or {}
            if task.get('state') == 'success':
                # 保留 dirty：上游或参数变了，旧产物不能当作现成结果
                if node['result'].get('state') != 'dirty':
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
                parts = _assemble_part_inputs(graph, by_id, node_id)
                root = os.path.realpath(pipeline_root(forgeworks_root, asset_id, kind))
                outputs_dir = os.path.join(root, 'outputs')
                os.makedirs(outputs_dir, exist_ok=True)
                filename = 'model_assembly_%s.glb' % node_id
                assembled = fw_parts.assemble_parts(
                    parts, os.path.join(outputs_dir, filename),
                    os.path.join(root, 'parts', 'layout_%s.json' % node_id), root,
                    assembly_prompt=_upstream_text(graph, by_id, node_id),
                    reset=bool((node.get('params') or {}).get('resetLayout')),
                    blender_path=blender_path, asset_id=asset_id, node_id=node_id)
                result['state'] = 'done'
                result['output'] = {
                    'meshPath': assembled['meshPath'],
                    'parts': assembled['parts'],
                    'triangles': assembled['triangles'],
                    'layoutPath': os.path.relpath(assembled['layoutPath'], root).replace(os.sep, '/'),
                    'warnings': assembled['warnings'],
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
    graph['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    root = pipeline_root(forgeworks_root, asset_id, kind)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, 'graph.json'), 'w', encoding='utf-8') as stream:
        json.dump(graph, stream, ensure_ascii=False, indent=2)
    _write_prompt(root, graph)
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
            {'id': 'prompt_assemble', 'type': 'prompt', 'x': 60, 'y': 1260, 'params': {'text': ''}},
            {'id': 'assemble', 'type': 'assemble', 'x': 1020, 'y': 840,
             'params': {'resetLayout': False}},
        ]
        for index, (node_id, node_type, params) in enumerate([
                ('style', 'styleApply', {'mode': 'primitive'}),
                ('uv', 'uv', {'mode': 'primitive'}),
                ('lod', 'lod', {'levels': 3}),
                ('collision', 'collision', {'type': 'box'}),
                ('animation', 'animation', {'mode': 'ue-rebuild'}),
                ('metadata', 'metadata', {'formats': ['csv', 'json']}),
                ('validate', 'validate', {'maxTriangles': 20000}),
                ('export', 'export', {})]):
            nodes.append({'id': node_id, 'type': node_type, 'x': 1260 + index * 240, 'y': 840,
                          'params': params})
        edges = [
            {'from': 'prompt_overall', 'out': 'text', 'to': 'overall', 'in': 'text'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
            {'from': 'overall', 'out': 'image', 'to': 'partImage_roof', 'in': 'image'},
            {'from': 'prompt_body', 'out': 'text', 'to': 'partImage_body', 'in': 'text'},
            {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
            {'from': 'partModel_body', 'out': 'part', 'to': 'assemble', 'in': 'part'},
            {'from': 'prompt_roof', 'out': 'text', 'to': 'partImage_roof', 'in': 'text'},
            {'from': 'partImage_roof', 'out': 'image', 'to': 'partModel_roof', 'in': 'image'},
            {'from': 'partModel_roof', 'out': 'part', 'to': 'assemble', 'in': 'part'},
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
