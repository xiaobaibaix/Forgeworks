"""把 MC_CAR 管线重接为「整体三视图 → 尺寸 → 单件三视图/尺寸 → mate 装配」。

默认只打印结果；加 --write 才会备份 graph.json 后写盘。不触发任何付费 Provider 调用。
"""

import argparse
import copy
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw_pipeline
import fw_spec

ROLES = ('body', 'roof', 'wheel')
ROW_Y = {'body': 420, 'roof': 840, 'wheel': 1260}
# 三视图主体描述要与拆件长指令区分，长指令只用于 partImage 生成单件图。
PART_SUBJECTS = {'body': '方正车壳，不含车轮与车顶',
                 'roof': '车顶板，仅顶板与边缘倒角',
                 'wheel': '四轮轮组，前后两排左右对称'}
PART_COLUMNS = {'prompt': 60, 'partImage': 380, 'threeView': 680,
                'blueprint': 980, 'partModel': 1280, 'decimate': 1580}
MATE_X = 1880
MATE_STEP = 300
TAIL_X = MATE_X + MATE_STEP * 2
TAIL_TYPES = ('styleApply', 'uv', 'lod', 'collision', 'animation',
              'metadata', 'validate', 'export')
TAIL_STEP = 300


def _node(node_id, node_type, x, y, params):
    return {'id': node_id, 'type': node_type, 'x': x, 'y': y, 'params': params}


def _edge(source, out, target, port):
    return {'from': source, 'out': out, 'to': target, 'in': port}


def _three_view(node_id, x, y, params=None):
    return _node(node_id, 'threeView', x, y, dict(
        {'provider': 'ark', 'size': '1K', 'outputFormat': 'png',
         'annotate': False, 'prompt': ''}, **(params or {})))


def _part_blueprint(role, x, y, template):
    return _node('blueprint_' + role, 'blueprint', x, y, {
        'provider': 'ark', 'scope': 'part', 'role': role, 'template': template,
        'overallLengthM': None, 'specLocked': False, 'prompt': ''})


def _mate_node(mate_id, connection, x, y, ground=False):
    return _node(mate_id, 'mate', x, y, {
        'connection': connection, 'offsetM': -0.002,
        'alignTwist': True, 'ground': ground})


def _existing(graph, node_id):
    return next((node for node in graph['nodes'] if node.get('id') == node_id), None)


def _carry_results(node, previous):
    if previous and isinstance(previous.get('result'), dict):
        node['result'] = copy.deepcopy(previous['result'])
    return node


def rewire(graph, spec):
    """返回重接后的图；保留原有结果以便脏检查，而不是删除。"""
    previous = {node['id']: node for node in graph.get('nodes') or []}
    overall = _existing(graph, 'blueprint') or _existing(graph, 'blueprint_overall')
    if not overall:
        raise ValueError('CAR_GRAPH_BUILD: 图中没有 blueprint 节点')
    overall_params = dict(overall.get('params') or {})
    overall_params.update({'scope': 'overall', 'template': overall_params.get('template') or 'car',
                           'specLocked': False})
    overall_params.pop('role', None)
    overall_node = _carry_results(
        _node('blueprint_overall', 'blueprint', -150, -200, overall_params), overall)

    nodes = [
        _carry_results(_node('prompt_overall', 'prompt', -1200, 50,
                             (previous.get('prompt_overall') or {}).get('params') or {}),
                       previous.get('prompt_overall')),
        _carry_results(_node('overall', 'textToImage', -900, 440,
                             (previous.get('overall') or {}).get('params') or {}),
                       previous.get('overall')),
        _carry_results(_three_view('threeView_overall', -520, 440), previous.get('threeView_overall')),
        overall_node,
    ]
    edges = [
        _edge('prompt_overall', 'text', 'overall', 'text'),
        _edge('overall', 'image', 'threeView_overall', 'image'),
        _edge('prompt_overall', 'text', 'threeView_overall', 'text'),
        _edge('threeView_overall', 'sheet', 'blueprint_overall', 'image'),
        _edge('prompt_overall', 'text', 'blueprint_overall', 'text'),
    ]

    for role in ROLES:
        row = ROW_Y[role]
        prompt = previous.get('prompt_' + role) or {}
        part_image = previous.get('partImage_' + role) or {}
        part_model = previous.get('partModel_' + role) or {}
        decimate = previous.get('decimate_' + role) or {}
        nodes.extend([
            _carry_results(_node('prompt_' + role, 'prompt', PART_COLUMNS['prompt'], row,
                                 dict(prompt.get('params') or {})), prompt),
            _carry_results(_node('partImage_' + role, 'partImage',
                                 PART_COLUMNS['partImage'], row,
                                 dict(part_image.get('params') or {})), part_image),
            _carry_results(_three_view('threeView_' + role, PART_COLUMNS['threeView'], row,
                                       {'prompt': PART_SUBJECTS[role]}),
                           previous.get('threeView_' + role)),
            _carry_results(_part_blueprint(role, PART_COLUMNS['blueprint'], row,
                                           overall_params.get('template') or 'car'),
                           previous.get('blueprint_' + role)),
            _carry_results(_node('partModel_' + role, 'partModel',
                                 PART_COLUMNS['partModel'], row,
                                 dict(part_model.get('params') or {})), part_model),
            _carry_results(_node('decimate_' + role, 'decimate',
                                 PART_COLUMNS['decimate'], row,
                                 dict(decimate.get('params') or {})), decimate),
        ])
        edges.extend([
            _edge('overall', 'image', 'partImage_' + role, 'image'),
            _edge('prompt_' + role, 'text', 'partImage_' + role, 'text'),
            _edge('blueprint_overall', 'spec', 'partImage_' + role, 'spec'),
            _edge('partImage_' + role, 'image', 'threeView_' + role, 'image'),
            _edge('threeView_' + role, 'sheet', 'blueprint_' + role, 'image'),
            _edge('blueprint_overall', 'spec', 'blueprint_' + role, 'spec'),
            _edge('prompt_' + role, 'text', 'blueprint_' + role, 'text'),
            _edge('partImage_' + role, 'image', 'partModel_' + role, 'image'),
            _edge('blueprint_overall', 'spec', 'partModel_' + role, 'spec'),
            _edge('partImage_' + role, 'ports', 'partModel_' + role, 'ports'),
            _edge('blueprint_' + role, 'measure', 'partModel_' + role, 'measure'),
            _edge('partModel_' + role, 'assembly', 'decimate_' + role, 'assembly'),
        ])

    tree = fw_spec.build_mate_tree(spec)
    mate_ids = {}
    last_index = len(tree['nodes']) - 1
    for index, item in enumerate(tree['nodes']):
        mate_id = item['id']
        mate_ids[item['b']] = mate_id
        node = _carry_results(
            _mate_node(mate_id, item['connection'], MATE_X + MATE_STEP * index, ROW_Y['body'],
                       ground=index == last_index),
            previous.get(mate_id))
        nodes.append(node)
        edges.append(_edge(_assembly_source(item['a'], mate_ids),
                           'assembly', mate_id, 'a'))
        edges.append(_edge('decimate_' + item['bRole'], 'assembly', mate_id, 'b'))
        edges.append(_edge('blueprint_overall', 'spec', mate_id, 'spec'))

    final_mate = tree['nodes'][-1]['id'] if tree['nodes'] else ''
    if final_mate:
        edges.append(_edge(final_mate, 'mesh', 'styleApply_1', 'mesh'))

    metadata_id = ''
    for index, tail_type in enumerate(TAIL_TYPES):
        source = next((node for node in graph.get('nodes') or []
                       if node.get('type') == tail_type and node['id'] != 'assemble_1'), None)
        if not source:
            continue
        node_id = source['id']
        if tail_type == 'styleApply':
            node_id = 'styleApply_1'
        node = _carry_results(_node(node_id, tail_type, TAIL_X + TAIL_STEP * index,
                                    ROW_Y['body'], dict(source.get('params') or {})), source)
        nodes.append(node)
        if index and tail_type != 'export':
            previous_id = nodes[-2]['id']
            edges.append(_edge(previous_id, 'mesh', node_id, 'mesh'))
        if tail_type == 'metadata':
            metadata_id = node_id
        if tail_type == 'export' and metadata_id:
            validate_id = next((item['id'] for item in nodes if item.get('type') == 'validate'), '')
            edges.append(_edge(metadata_id, 'mesh', node_id, 'mesh'))
            if validate_id:
                edges.append(_edge(validate_id, 'report', node_id, 'report'))

    rewired = {'schemaVersion': graph.get('schemaVersion', 1),
               'assetId': graph.get('assetId', ''),
               'template': graph.get('template', 'parts'),
               'nodes': nodes,
               'edges': edges,
               'revision': graph.get('revision', 0),
               'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    return rewired, tree.get('warnings') or []


def _assembly_source(node_id, mate_ids):
    if node_id in mate_ids:
        return mate_ids[node_id]
    if node_id.startswith('partModel_'):
        return 'decimate_' + node_id.split('_', 1)[1]
    return node_id


def _project_path(value):
    if value:
        return os.path.abspath(value)
    return os.path.abspath(os.environ.get('FORGEWORKS_PROJECT') or
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        '..', '..', 'ResWs', 'Forgeworks'))


def build(project, asset_id):
    root = fw_pipeline.pipeline_root(project, asset_id, 'machine')
    path = os.path.join(root, 'graph.json')
    if not os.path.isfile(path):
        raise ValueError('CAR_GRAPH_BUILD: 找不到 %s' % path)
    with open(path, 'r', encoding='utf-8') as stream:
        graph = json.load(stream)
    spec = fw_spec.template_spec(asset_id, template='car')
    rewired, warnings = rewire(graph, spec)
    fw_pipeline.validate_graph(rewired)
    return path, graph, rewired, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', help='Forgeworks 项目根目录')
    parser.add_argument('--asset', default='MC_CAR', help='资产 ID')
    parser.add_argument('--write', action='store_true', help='备份并写入 graph.json')
    args = parser.parse_args(argv)

    project = _project_path(args.project)
    path, graph, rewired, warnings = build(project, args.asset)
    print('图：%s' % path)
    print('节点 %d -> %d，边 %d -> %d'
          % (len(graph.get('nodes') or []), len(rewired['nodes']),
             len(graph.get('edges') or []), len(rewired['edges'])))
    for warning in warnings:
        print('警告：%s' % warning)
    if not args.write:
        print('未写入。加 --write 备份后写入。')
        return 0
    backup = path + '.bak-mate-' + time.strftime('%Y%m%d-%H%M%S')
    shutil.copy2(path, backup)
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(rewired, stream, ensure_ascii=False, indent=2)
    print('已备份到 %s' % backup)
    print('已写入 %s' % path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
