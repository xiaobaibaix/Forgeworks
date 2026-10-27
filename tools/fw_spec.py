#!/usr/bin/env python3
"""Structured dimension specs, port anchors and assembly-tree planning."""

import copy
import json
import math
import os
import tempfile

SPEC_SCHEMA_VERSION = 1
UNITS = 'm'
PART_ROLES = ('body', 'track', 'wheel', 'boom', 'bucket', 'cab', 'roof', 'door', 'window')
ROLE_LABELS = {
    'body': '车身', 'track': '履带', 'wheel': '车轮', 'boom': '动臂',
    'bucket': '铲斗', 'cab': '驾驶室', 'roof': '车顶', 'door': '车门',
    'window': '车窗',
}
ROLE_ALIASES = {
    'side_window': 'window', 'rear_window': 'window', 'front_window': 'window',
    '车体': 'body', '底盘': 'track', '履带': 'track', '轮子': 'wheel',
    '大臂': 'boom', '动臂': 'boom', '铲斗': 'bucket', '驾驶室': 'cab',
    '车顶': 'roof', '车门': 'door', '车窗': 'window', '玻璃': 'window',
}
FORWARDS = {
    '+X': (1.0, 0.0, 0.0), '-X': (-1.0, 0.0, 0.0),
    '+Y': (0.0, 1.0, 0.0), '-Y': (0.0, -1.0, 0.0),
    '+Z': (0.0, 0.0, 1.0), '-Z': (0.0, 0.0, -1.0),
}
ORIENTATION_AMBIGUITY = 0.01

EXCAVATOR_TEMPLATE = {
    'schemaVersion': 1,
    'assetId': '',
    'units': 'm',
    'overall': {'lengthM': 7.2, 'widthM': 2.4, 'heightM': 3.1,
                'source': 'template', 'confidence': 0.5},
    'assembly': {'rootRole': 'body'},
    'parts': {
        'body': {
            'role': 'body', 'sizeM': [4.2, 1.6, 1.4], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'boom_base', 'type': 'pin', 'anchor': [0.62, 0.5, 0.7],
                 'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.08},
                {'id': 'cab_mount', 'type': 'fixed', 'anchor': [0.2, 0.35, 0.9],
                 'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.05},
                {'id': 'track_mount', 'type': 'fixed', 'anchor': [0.5, 0.5, 0.05],
                 'axis': [0, 0, 1], 'normal': [1, 0, 0], 'radiusM': 0.12},
            ],
        },
        'track': {
            'role': 'track', 'sizeM': [4.6, 2.4, 1.0], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'axle', 'type': 'fixed', 'anchor': [0.5, 0.5, 0.9],
                 'axis': [0, 0, 1], 'normal': [1, 0, 0], 'radiusM': 0.12},
            ],
        },
        'boom': {
            'role': 'boom', 'sizeM': [3.6, 0.5, 0.7], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'base_pin', 'type': 'pin', 'anchor': [0.02, 0.5, 0.5],
                 'axis': [-1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.08},
                {'id': 'tip_pin', 'type': 'pin', 'anchor': [0.98, 0.5, 0.35],
                 'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.06},
            ],
        },
        'bucket': {
            'role': 'bucket', 'sizeM': [1.15, 1.2, 1.05], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'ear_pin', 'type': 'pin', 'anchor': [0.02, 0.5, 0.78],
                 'axis': [-1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.06},
            ],
        },
        'cab': {
            'role': 'cab', 'sizeM': [1.4, 0.9, 1.6], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'floor', 'type': 'fixed', 'anchor': [0.5, 0.5, 0.02],
                 'axis': [0, 0, -1], 'normal': [1, 0, 0], 'radiusM': 0.05},
            ],
        },
    },
    'connections': [
        {'id': 'c_bucket_boom', 'a': 'bucket:ear_pin', 'b': 'boom:tip_pin', 'joint': 'pin'},
        {'id': 'c_boom_body', 'a': 'boom:base_pin', 'b': 'body:boom_base', 'joint': 'pin'},
        {'id': 'c_cab_body', 'a': 'cab:floor', 'b': 'body:cab_mount', 'joint': 'fixed'},
        {'id': 'c_track_body', 'a': 'track:axle', 'b': 'body:track_mount', 'joint': 'fixed'},
    ],
    'notes': [],
}


def template_spec(asset_id='', template='excavator'):
    if template != 'excavator':
        raise ValueError('SPEC_UNANCHORED: 没有机型模板 %s，请填写 overallLengthM' % template)
    spec = copy.deepcopy(EXCAVATOR_TEMPLATE)
    spec['assetId'] = str(asset_id or '')
    return validate_spec(spec)


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _number(value, label):
    if isinstance(value, bool):
        raise ValueError('SPEC_INVALID: %s 不能是布尔值' % label)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('SPEC_INVALID: %s 必须是数字' % label) from None
    if not math.isfinite(number):
        raise ValueError('SPEC_INVALID: %s 必须是有限数字' % label)
    return number


def _vec3(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('SPEC_INVALID: %s 必须是三个数字' % label)
    return [_number(item, label) for item in value]


def _unit(value, label):
    vector = _vec3(value, label)
    length = (vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2) ** 0.5
    if length < 1e-9:
        raise ValueError('SPEC_INVALID: %s 不能是零向量' % label)
    return [round(item / length, 9) for item in vector]


def validate_spec(spec, warnings=None):
    warnings = warnings if warnings is not None else []
    if not isinstance(spec, dict):
        raise ValueError('SPEC_INVALID: spec 必须是 JSON 对象')
    version = spec.get('schemaVersion')
    if version != SPEC_SCHEMA_VERSION:
        raise ValueError('SPEC_INVALID: schemaVersion 必须是 %d' % SPEC_SCHEMA_VERSION)
    if spec.get('units') != UNITS:
        raise ValueError('SPEC_INVALID: units 必须是 m')
    overall = spec.get('overall')
    if not isinstance(overall, dict):
        raise ValueError('SPEC_INVALID: 缺少 overall')
    normalized_overall = {}
    for key in ('lengthM', 'widthM', 'heightM'):
        value = _number(overall.get(key), 'overall.' + key)
        if value <= 0:
            raise ValueError('SPEC_INVALID: overall.%s 必须大于 0' % key)
        normalized_overall[key] = value
    source = str(overall.get('source') or 'template')
    if source not in ('user', 'template', 'vision'):
        raise ValueError('SPEC_INVALID: overall.source 只能是 user/template/vision')
    confidence = _number(overall.get('confidence', 0.5), 'overall.confidence')
    if not 0 <= confidence <= 1:
        raise ValueError('SPEC_INVALID: overall.confidence 必须在 0..1')
    normalized_overall.update({'source': source, 'confidence': confidence})

    raw_parts = spec.get('parts')
    if not isinstance(raw_parts, dict) or not raw_parts:
        raise ValueError('SPEC_INVALID: parts 必须是非空对象')
    parts = {}
    for role, raw_part in raw_parts.items():
        if role not in PART_ROLES:
            raise ValueError('SPEC_INVALID: 未知部件角色 %s' % role)
        if not isinstance(raw_part, dict):
            raise ValueError('SPEC_INVALID: parts.%s 必须是对象' % role)
        if raw_part.get('role') not in (None, role):
            raise ValueError('SPEC_INVALID: parts.%s.role 必须等于键名' % role)
        size = _vec3(raw_part.get('sizeM'), 'parts.%s.sizeM' % role)
        if any(value <= 0 for value in size):
            raise ValueError('SPEC_INVALID: parts.%s.sizeM 必须全部大于 0' % role)
        forward = str(raw_part.get('forward') or '+X').upper()
        if forward not in FORWARDS:
            raise ValueError('SPEC_INVALID: parts.%s.forward 非法' % role)
        part_confidence = _number(raw_part.get('confidence', 0.5), 'parts.%s.confidence' % role)
        if not 0 <= part_confidence <= 1:
            raise ValueError('SPEC_INVALID: parts.%s.confidence 必须在 0..1' % role)
        ports = []
        seen_ports = set()
        for raw_port in raw_part.get('ports') or []:
            if not isinstance(raw_port, dict):
                raise ValueError('SPEC_INVALID: parts.%s.ports 项必须是对象' % role)
            port_id = str(raw_port.get('id') or '').strip()
            if not port_id or port_id in seen_ports:
                raise ValueError('SPEC_INVALID: parts.%s 端口 id 为空或重复' % role)
            seen_ports.add(port_id)
            anchor = _vec3(raw_port.get('anchor'), 'ports.%s.anchor' % port_id)
            if any(value < -0.5 or value > 1.5 for value in anchor):
                raise ValueError('SPEC_INVALID: ports.%s.anchor 超出可用范围' % port_id)
            if any(value < 0 or value > 1 for value in anchor):
                warnings.append('端口 %s 的 anchor 超出 [0,1]，仅作为参考' % port_id)
            radius = _number(raw_port.get('radiusM', 0.02), 'ports.%s.radiusM' % port_id)
            if radius <= 0:
                raise ValueError('SPEC_INVALID: ports.%s.radiusM 必须大于 0' % port_id)
            ports.append({
                'id': port_id,
                'type': str(raw_port.get('type') or 'pin'),
                'anchor': anchor,
                'axis': _unit(raw_port.get('axis', [1, 0, 0]), 'ports.%s.axis' % port_id),
                'normal': _unit(raw_port.get('normal', [0, 0, 1]), 'ports.%s.normal' % port_id),
                'radiusM': radius,
            })
        parts[role] = {
            'role': role,
            'sizeM': size,
            'forward': forward,
            'confidence': part_confidence,
            'ports': ports,
        }
        if part_confidence < 0.4:
            warnings.append('部件 %s 的 confidence 低于 0.4' % role)

    raw_connections = spec.get('connections') or []
    if not isinstance(raw_connections, list):
        raise ValueError('SPEC_INVALID: connections 必须是数组')
    used_ports = set()
    connections = []
    for index, raw_connection in enumerate(raw_connections):
        if not isinstance(raw_connection, dict):
            raise ValueError('SPEC_INVALID: connections[%d] 必须是对象' % index)
        endpoints = []
        for side in ('a', 'b'):
            text = str(raw_connection.get(side) or '')
            if ':' not in text:
                raise ValueError('SPEC_INVALID: connections[%d].%s 必须是 role:port' % (index, side))
            role, port_id = text.split(':', 1)
            if role not in parts or port_id not in {item['id'] for item in parts[role]['ports']}:
                raise ValueError('SPEC_INVALID: connections[%d].%s 指向不存在的端口 %s'
                                 % (index, side, text))
            endpoints.append(text)
        if endpoints[0] == endpoints[1]:
            raise ValueError('SPEC_INVALID: 连接不能指向同一个端口')
        if endpoints[0] in used_ports or endpoints[1] in used_ports:
            warnings.append('端口重复连接，已跳过 connection %s'
                            % (raw_connection.get('id') or index))
            continue
        used_ports.update(endpoints)
        connections.append({
            'id': str(raw_connection.get('id') or 'c_%d_%s_%s'
                      % (index, endpoints[0].split(':')[0], endpoints[1].split(':')[0])),
            'a': endpoints[0],
            'b': endpoints[1],
            'joint': str(raw_connection.get('joint') or 'pin'),
        })

    assembly = spec.get('assembly') if isinstance(spec.get('assembly'), dict) else {}
    root_role = str(assembly.get('rootRole') or 'body')
    if root_role not in parts:
        warnings.append('assembly.rootRole=%s 不存在，改用连接度数最高的角色' % root_role)
        degrees = {role: 0 for role in parts}
        for connection in connections:
            for endpoint in (connection['a'], connection['b']):
                degrees[endpoint.split(':')[0]] += 1
        root_role = max(parts, key=lambda role: (degrees[role], role))

    return {
        'schemaVersion': SPEC_SCHEMA_VERSION,
        'assetId': str(spec.get('assetId') or ''),
        'units': UNITS,
        'overall': normalized_overall,
        'assembly': {'rootRole': root_role},
        'parts': parts,
        'connections': connections,
        'notes': [str(item) for item in (spec.get('notes') or [])],
    }


def from_vision(raw, overall_length_m=0.0, template='excavator', asset_id=''):
    if isinstance(raw, dict) and isinstance(raw.get('spec'), dict):
        raw = raw['spec']
    if not isinstance(raw, dict):
        raise ValueError('SPEC_INVALID: 视觉结果不是 JSON 对象')
    if template != 'excavator':
        raise ValueError('SPEC_UNANCHORED: 没有机型模板 %s' % template)
    spec = copy.deepcopy(EXCAVATOR_TEMPLATE)
    spec['assetId'] = str(asset_id or '')
    raw_parts = raw.get('parts') if isinstance(raw.get('parts'), dict) else {}
    model_roles = set()
    model_port_roles = set()
    for role, incoming in raw_parts.items():
        if role not in spec['parts'] or not isinstance(incoming, dict):
            continue
        target = spec['parts'][role]
        if isinstance(incoming.get('sizeM'), (list, tuple)):
            target['sizeM'] = list(incoming['sizeM'])
        if incoming.get('forward'):
            target['forward'] = str(incoming['forward']).upper()
        if isinstance(incoming.get('ports'), list) and incoming['ports']:
            target['ports'] = copy.deepcopy(incoming['ports'])
            model_port_roles.add(role)
        if incoming.get('confidence') is not None:
            target['confidence'] = incoming['confidence']
        model_roles.add(role)
    try:
        anchor = float(overall_length_m or 0)
    except (TypeError, ValueError):
        anchor = 0.0
    raw_overall = raw.get('overall') if isinstance(raw.get('overall'), dict) else {}
    reported_length = _positive(raw_overall.get('lengthM'))
    template_overall = EXCAVATOR_TEMPLATE['overall']
    template_length = float(template_overall['lengthM'])
    target_length = anchor if anchor > 0 else template_length
    # 模型按整机锚直接给米制尺寸，用它自报的整机长度做基准，避免二次缩放
    model_factor = target_length / (reported_length or template_length)
    template_factor = target_length / template_length
    if anchor > 0:
        width_base = _positive(raw_overall.get('widthM')) or float(template_overall['widthM'])
        height_base = _positive(raw_overall.get('heightM')) or float(template_overall['heightM'])
        spec['overall'] = {
            'lengthM': anchor,
            'widthM': round(width_base * model_factor, 6),
            'heightM': round(height_base * model_factor, 6),
            'source': 'user',
            'confidence': 0.9,
        }
    for role, part in spec['parts'].items():
        size_factor = model_factor if role in model_roles else template_factor
        if size_factor != 1.0:
            part['sizeM'] = [round(float(value) * size_factor, 6) for value in part['sizeM']]
        port_factor = model_factor if role in model_port_roles else template_factor
        if port_factor == 1.0:
            continue
        for port in part.get('ports') or []:
            radius = port.get('radiusM')
            if isinstance(radius, (int, float)) and not isinstance(radius, bool):
                port['radiusM'] = round(float(radius) * port_factor, 6)
    raw_connections = raw.get('connections')
    if isinstance(raw_connections, list) and raw_connections:
        spec['connections'] = copy.deepcopy(raw_connections)
    raw_assembly = raw.get('assembly') if isinstance(raw.get('assembly'), dict) else {}
    spec['assembly'] = {'rootRole': str(raw_assembly.get('rootRole') or 'body')}
    spec['notes'] = [str(item) for item in (raw.get('notes') or [])]
    return validate_spec(spec)


def read_spec(path):
    try:
        with open(path, encoding='utf-8') as stream:
            raw = json.load(stream)
    except FileNotFoundError:
        raise ValueError('SPEC_MISSING: 规格文件不存在：%s' % path)
    except OSError as error:
        raise ValueError('SPEC_MISSING: 无法读取规格文件：%s' % error)
    except ValueError as error:
        raise ValueError('SPEC_INVALID: 规格文件不是合法 JSON：%s' % error)
    return validate_spec(raw)


def write_spec(path, spec):
    validated = validate_spec(spec)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.spec-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def role_for_node(node_id, part_name=''):
    text = str(node_id or '')
    for prefix in ('partModel_', 'partImage_', 'decimate_', 'assembly_', 'mate_'):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip().lower().replace('-', '_')
    if text in PART_ROLES:
        return text
    if text in ROLE_ALIASES:
        return ROLE_ALIASES[text]
    name = str(part_name or '').strip()
    for role, label in ROLE_LABELS.items():
        if label and label in name:
            return role
    return ''


def anchor_ports(part_spec):
    result = []
    for port in (part_spec or {}).get('ports') or []:
        result.append({
            'id': port['id'],
            'type': port.get('type') or 'pin',
            'anchorNorm': list(port['anchor']),
            'axis': list(port['axis']),
            'normal': list(port['normal']),
            'radiusM': port.get('radiusM', 0.02),
        })
    return result


def _det3(matrix):
    return (matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
            - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
            + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0]))


def _mat_vec(matrix, vector):
    return [sum(matrix[row][column] * vector[column] for column in range(3))
            for row in range(3)]


def orientation_candidates():
    from itertools import permutations, product
    candidates = []
    for perm in permutations(range(3)):
        for signs in product((-1, 1), repeat=3):
            matrix = [[0, 0, 0] for _ in range(3)]
            for axis in range(3):
                matrix[axis][perm[axis]] = signs[axis]
            determinant = _det3(matrix)
            if abs(determinant - 1) > 1e-9:
                continue
            candidates.append({
                'matrix': matrix,
                'perm': list(perm),
                'signs': list(signs),
                'det': 1,
            })
    return candidates


def _euler_deg(matrix):
    sy = max(-1.0, min(1.0, -matrix[2][0]))
    if abs(sy) < 1 - 1e-9:
        ry = math.asin(sy)
        rx = math.atan2(matrix[2][1], matrix[2][2])
        rz = math.atan2(matrix[1][0], matrix[0][0])
    else:
        ry = math.copysign(math.pi / 2, sy)
        rx = math.atan2(-matrix[1][2], matrix[1][1])
        rz = 0.0
    return [round(math.degrees(value), 6) for value in (rx, ry, rz)]


def choose_orientation(measured, target, forward='+X', mode='uniform'):
    if mode not in ('uniform', 'perAxis'):
        raise ValueError('FIT_ORIENTATION_AMBIGUOUS: 未知 fitMode %s' % mode)
    measured = [float(value) for value in measured]
    target = [float(value) for value in target]
    if (len(measured) != 3 or len(target) != 3
            or not all(math.isfinite(value) and value > 0 for value in measured + target)):
        raise ValueError('SPEC_INVALID: measured/target 必须是三个正数')
    forward_vector = FORWARDS.get(str(forward or '+X').upper())
    if forward_vector is None:
        raise ValueError('SPEC_INVALID: 未知 forward %s' % forward)
    best = None
    group_scores = {}
    for candidate in orientation_candidates():
        matrix = candidate['matrix']
        rotated = [measured[candidate['perm'][axis]] for axis in range(3)]
        if mode == 'perAxis':
            scale_per_axis = [target[axis] / rotated[axis] for axis in range(3)]
            scale = (scale_per_axis[0] * scale_per_axis[1] * scale_per_axis[2]) ** (1 / 3.0)
            aspect_error = max(abs(value / scale - 1.0) for value in scale_per_axis)
        else:
            denominator = sum(value * value for value in rotated)
            scale = sum(target[axis] * rotated[axis] for axis in range(3)) / denominator
            scale_per_axis = [scale, scale, scale]
            aspect_error = max(abs(rotated[axis] * scale - target[axis]) / target[axis]
                               for axis in range(3))
        rotated_forward = _mat_vec(matrix, [1, 0, 0])
        alignment = sum(rotated_forward[axis] * forward_vector[axis] for axis in range(3))
        score = aspect_error + 0.05 * (1.0 - alignment)
        rotation_deg = _euler_deg(matrix)
        rotation_cost = sum(abs(value) for value in rotation_deg)
        item = {
            'matrix': matrix,
            'scale': scale,
            'scalePerAxis': scale_per_axis,
            'aspectError': aspect_error,
            'rotationDeg': rotation_deg,
            'score': score,
            'ambiguous': False,
        }
        # 同尺寸分配下的朝向/符号变体天然同分，只有尺寸分配不同才算歧义。
        size_key = tuple(round(value, 6) for value in rotated)
        group_scores[size_key] = min(group_scores.get(size_key, score), score)
        if best is None or score < best['score'] - 1e-12:
            best = item
        elif abs(score - best['score']) <= 1e-12:
            # 同分时取转动最小的解，否则对称朝向会稳定压过恒等朝向。
            if rotation_cost < sum(abs(value) for value in best['rotationDeg']) - 1e-12:
                best = item
    ranked = sorted(group_scores.values())
    best['ambiguous'] = (len(ranked) > 1
                         and ranked[1] - ranked[0] < ORIENTATION_AMBIGUITY)
    return best


def resolve_ports(ports, bbox, matrix=None):
    if isinstance(bbox, dict):
        lower = [float(value) for value in bbox['min']]
        upper = [float(value) for value in bbox['max']]
    else:
        lower = [float(value) for value in bbox[0]]
        upper = [float(value) for value in bbox[1]]
    result = []
    for port in ports or []:
        anchor = [float(value) for value in port.get('anchor', [0.5, 0.5, 0.5])]
        axis = _unit(port.get('axis', [1, 0, 0]), 'port.axis')
        normal = _unit(port.get('normal', [0, 0, 1]), 'port.normal')
        if matrix is not None:
            axis = _unit(_mat_vec(matrix, axis), 'port.axis')
            normal = _unit(_mat_vec(matrix, normal), 'port.normal')
        result.append({
            'id': str(port.get('id') or ''),
            'type': str(port.get('type') or 'pin'),
            'anchorNorm': anchor,
            'pos': [round(lower[axis_index] + anchor[axis_index]
                          * (upper[axis_index] - lower[axis_index]), 6)
                    for axis_index in range(3)],
            'axis': axis,
            'normal': normal,
            'radiusM': float(port.get('radiusM') or 0.02),
        })
    return result


def _find(parent, role):
    while parent[role] != role:
        parent[role] = parent[parent[role]]
        role = parent[role]
    return role


def _union(parent, left, right):
    left_root, right_root = _find(parent, left), _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def build_mate_tree(spec):
    warnings = []
    validated = validate_spec(spec, warnings)
    parent = {role: role for role in validated['parts']}
    edges = []
    for connection in validated['connections']:
        left_role = connection['a'].split(':')[0]
        right_role = connection['b'].split(':')[0]
        if _find(parent, left_role) == _find(parent, right_role):
            warnings.append('连接图有环，已跳过 connection %s' % connection['id'])
            continue
        _union(parent, left_role, right_role)
        edges.append(connection)

    adjacency = {role: [] for role in validated['parts']}
    for connection in edges:
        left_role = connection['a'].split(':')[0]
        right_role = connection['b'].split(':')[0]
        adjacency[left_role].append((right_role, connection))
        adjacency[right_role].append((left_role, connection))

    root_role = validated['assembly']['rootRole']
    visited = set()
    nodes = []
    plan_edges = []

    def visit(role, parent_role=None):
        visited.add(role)
        current = 'partModel_' + role
        for child_role, connection in adjacency[role]:
            if child_role == parent_role:
                continue
            child_result = visit(child_role, role)
            mate_id = 'mate_%s_%s' % (role, child_role)
            nodes.append({
                'id': mate_id,
                'connection': connection['id'],
                'aRole': role,
                'bRole': child_role,
                'a': current,
                'b': child_result,
            })
            plan_edges.append({'from': current, 'out': 'assembly', 'to': mate_id, 'in': 'a'})
            plan_edges.append({'from': child_result, 'out': 'assembly', 'to': mate_id, 'in': 'b'})
            current = mate_id
        return current

    visit(root_role)
    for role in validated['parts']:
        if role not in visited:
            warnings.append('连接图不连通，角色 %s 单独作为一棵装配树' % role)
            visit(role)
    return {'nodes': nodes, 'edges': plan_edges, 'warnings': warnings}
