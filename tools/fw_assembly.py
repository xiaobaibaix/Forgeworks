"""装配数据的纯函数；不依赖 fw_pipeline，避免循环导入。"""

import math

BBOX_DRIFT_LIMIT = 0.01
MATE_AXIS_WARN_DEG = 1.0
MATE_AXIS_ERROR_DEG = 5.0
MATE_OFFSET_WARN_M = 0.0005
_EPSILON = 1e-9


def assembly_for_node(graph, by_id, node_id, port='assembly'):
    """读取上游 assembly 输出；未接线返回 None，接线但未就绪则报错。"""
    edge = next((edge for edge in graph.get('edges') or []
                 if edge.get('to') == node_id and edge.get('in') == port), None)
    if not edge:
        return None
    source = (by_id or {}).get(edge.get('from'))
    if not source:
        raise ValueError('ASSEMBLY_MISSING: assembly 上游节点不存在')
    result = source.get('result') or {}
    state = result.get('state')
    if result and state not in ('done', None):
        raise ValueError('ASSEMBLY_MISSING: 上游装配未就绪（%s）' % (state or '未运行'))
    assembly = (result.get('output') or {}).get('assembly')
    if not isinstance(assembly, dict):
        raise ValueError('ASSEMBLY_MISSING: 上游节点没有 assembly 结果')
    return assembly


def retarget_assembly(assembly, mesh_path):
    """把装配里的网格路径换到新 GLB，端口与 mate 记录原样保留。"""
    mesh_path = str(mesh_path)
    parts = [dict(part, meshPath=mesh_path) for part in assembly.get('parts') or []]
    updated = dict(assembly)
    updated['meshPath'] = mesh_path
    updated['parts'] = parts
    return updated


def bbox_drift(before, after):
    """三个轴上包围盒尺寸的最大相对变化；缺数据时返回 0。"""
    if not (isinstance(before, (list, tuple)) and isinstance(after, (list, tuple))
            and len(before) == len(after) == 3):
        return 0.0
    drift = 0.0
    for old, new in zip(before, after):
        try:
            old, new = float(old or 0), float(new or 0)
        except (TypeError, ValueError):
            continue
        if old <= 0:
            continue
        drift = max(drift, abs(new - old) / old)
    return drift


def root_role(assembly):
    """装配 frame 属于第一个部件（a 侧）；合并时保持它在首位。"""
    parts = assembly.get('parts') if isinstance(assembly, dict) else None
    if not isinstance(parts, list) or not parts:
        return ''
    return str((parts[0] or {}).get('role') or '')


def connection_for(spec, connection_id='', role_a='', role_b=''):
    """按 id 取 spec 连接；id 为空时按两端角色唯一匹配。"""
    connections = (spec or {}).get('connections') or []
    if connection_id:
        match = next((item for item in connections if item.get('id') == connection_id), None)
        if not match:
            raise ValueError('MATE_CONNECTION_MISSING: spec 中没有连接 %s' % connection_id)
        return match
    candidates = []
    for item in connections:
        roles = {str(item.get('a') or '').split(':')[0],
                 str(item.get('b') or '').split(':')[0]}
        if role_a and role_b and roles == {role_a, role_b}:
            candidates.append(item)
    if len(candidates) != 1:
        raise ValueError('MATE_CONNECTION_MISSING: 无法唯一确定 %s 与 %s 之间的连接'
                         % (role_a or '?', role_b or '?'))
    return candidates[0]


def mate_ports(connection, role_a, role_b):
    """把连接两端分给父装配 a 与子装配 b，spec 的 a/b 顺序不作要求。"""
    endpoints = [str(connection.get('a') or ''), str(connection.get('b') or '')]
    picked = {}
    for endpoint in endpoints:
        role = endpoint.split(':')[0]
        if role in (role_a, role_b) and role not in picked:
            picked[role] = endpoint
    missing = [role for role in (role_a, role_b) if role not in picked]
    if missing:
        raise ValueError('MATE_CONNECTION_MISSING: 连接 %s 没有角色 %s 的端口'
                         % (connection.get('id') or '?', '、'.join(missing)))
    return picked[role_a], picked[role_b]


def connector_for(assembly, endpoint):
    for connector in assembly.get('connectors') or []:
        if isinstance(connector, dict) and connector.get('id') == endpoint:
            return connector
    raise ValueError('MATE_CONNECTOR_MISSING: 装配 %s 没有端口 %s'
                     % (assembly.get('assemblyId') or '?', endpoint))


def connector_frame(connector):
    """兼容 {pos,axis,normal} 与 {owner,frame:{...}} 两种端口形状。"""
    frame = connector.get('frame') if isinstance(connector, dict) else None
    if not isinstance(frame, dict):
        frame = connector if isinstance(connector, dict) else {}
    label = (connector or {}).get('id') if isinstance(connector, dict) else '?'
    return {'pos': _vector(frame.get('pos'), label, 'pos'),
            'axis': _unit(frame.get('axis'), label, 'axis'),
            'normal': _unit(frame.get('normal', [0, 0, 1]), label, 'normal')}


def mate_plan(connection, a, b, offset_m=-0.002, align_twist=True):
    """按设计 §8.2 解算 b 的旋转与平移；结果由 Blender 应用并复核。"""
    role_a, role_b = root_role(a), root_role(b)
    if not role_a or not role_b:
        raise ValueError('MATE_ASSEMBLY_INVALID: 装配缺少部件角色')
    if role_a == role_b:
        raise ValueError('MATE_ASSEMBLY_INVALID: 连接两端角色相同（%s）' % role_a)
    offset = _finite(offset_m, 'MATE_PARAM_INVALID: offsetM 必须是有限数字')
    endpoint_a, endpoint_b = mate_ports(connection, role_a, role_b)
    frame_a = connector_frame(connector_for(a, endpoint_a))
    frame_b = connector_frame(connector_for(b, endpoint_b))
    base = _quat_between(frame_a['axis'], _scale(frame_b['axis'], -1.0))
    rotation = base
    if align_twist:
        twist = _twist_angle(frame_a['axis'], _quat_rotate(base, frame_b['normal']),
                             frame_a['normal'])
        if abs(twist) > _EPSILON:
            rotation = _quat_mul(_quat_axis_angle(frame_a['axis'], twist), base)
    translation = _sub(_add(frame_a['pos'], _scale(frame_a['axis'], offset)),
                       _quat_rotate(rotation, frame_b['pos']))
    b_pos = _add(_quat_rotate(rotation, frame_b['pos']), translation)
    b_axis = _unit(_quat_rotate(rotation, frame_b['axis']), endpoint_b, 'axis')
    target = _add(frame_a['pos'], _scale(frame_a['axis'], offset))
    gap = _dot(_sub(target, b_pos), frame_a['axis'])
    applied = _dot(_sub(frame_a['pos'], b_pos), frame_a['axis'])
    axis_error = math.degrees(math.acos(_clamp(_dot(_scale(b_axis, -1.0), frame_a['axis']))))
    return {
        'connection': str(connection.get('id') or ''),
        'portA': endpoint_a,
        'portB': endpoint_b,
        'frameA': dict(frame_a, pos=_round_vector(frame_a['pos']),
                       axis=_round_vector(frame_a['axis']),
                       normal=_round_vector(frame_a['normal'])),
        'frameB': dict(frame_b, pos=_round_vector(frame_b['pos']),
                       axis=_round_vector(frame_b['axis']),
                       normal=_round_vector(frame_b['normal'])),
        'offsetM': offset,
        'alignTwist': bool(align_twist),
        'rotation': _round_vector(rotation, 9),
        'translation': _round_vector(translation, 9),
        'gapM': round(gap, 6),
        'appliedOffsetM': round(applied, 6),
        'axisErrorDeg': round(axis_error, 4),
    }


def merge_assembly(a, b, plan, report=None, ground=False, assembly_id=''):
    """以 a 的 frame 合并 b；b 的端口乘 (q,t)，落位偏差写进 mate 记录。"""
    rotation = _unit_quat(plan.get('rotation'))
    translation = _vector(plan.get('translation'), 'mate', 'translation')
    shift = [0.0, 0.0, 0.0]
    if ground and isinstance(report, dict):
        shift = _vector(report.get('groundShift') or [0, 0, 0], 'mate', 'groundShift')
    identity = [0.0, 0.0, 0.0, 1.0]
    connectors = [_transform_connector(item, identity, [0.0, 0.0, 0.0], shift)
                  for item in a.get('connectors') or []]
    connectors.extend(_transform_connector(item, rotation, translation, shift)
                      for item in b.get('connectors') or [])
    source = report if isinstance(report, dict) else {}
    gap = _finite(source.get('gapM', plan.get('gapM')), 'mate gapM')
    applied = _finite(source.get('appliedOffsetM', plan.get('appliedOffsetM')),
                      'mate appliedOffsetM')
    axis_error = _finite(source.get('axisErrorDeg', plan.get('axisErrorDeg')),
                         'mate axisErrorDeg')
    offset = _finite(plan.get('offsetM'), 'mate offsetM')
    warnings = list(a.get('warnings') or []) + list(b.get('warnings') or [])
    warnings.extend(str(item) for item in source.get('warnings') or [])
    status = 'ok'
    if axis_error > MATE_AXIS_ERROR_DEG:
        status = 'error'
        warnings.append('MATE_AXIS_ERROR: 端口轴向偏差 %.1f°' % axis_error)
    elif axis_error > MATE_AXIS_WARN_DEG:
        status = 'warn'
        warnings.append('MATE_AXIS_ERROR: 端口轴向偏差 %.1f°' % axis_error)
    if abs(applied + offset) > MATE_OFFSET_WARN_M:
        status = 'warn' if status == 'ok' else status
        warnings.append('MATE_OFFSET_DRIFT: 落位偏差 %.1f mm' % ((applied + offset) * 1000))
    mates = list(a.get('mates') or []) + list(b.get('mates') or [])
    mates.append({
        'id': str(plan.get('connection') or ''),
        'a': str(plan.get('portA') or ''),
        'b': str(plan.get('portB') or ''),
        'offsetM': round(offset, 6),
        'gapM': round(gap, 6),
        'axisErrorDeg': round(axis_error, 4),
        'status': status,
    })
    return {
        'schemaVersion': 1,
        'assemblyId': assembly_id or ('asm_' + str(a.get('assemblyId') or 'mate')),
        'assetId': a.get('assetId') or b.get('assetId') or '',
        'meshPath': '',
        'parts': [dict(item) for item in a.get('parts') or []]
                 + [dict(item) for item in b.get('parts') or []],
        'connectors': connectors,
        'mates': mates,
        'warnings': warnings,
    }


def _transform_connector(connector, rotation, translation, shift):
    if not isinstance(connector, dict):
        raise ValueError('MATE_CONNECTOR_MISSING: 装配端口必须是对象')
    frame = connector_frame(connector)
    pos = _add(_add(_quat_rotate(rotation, frame['pos']), translation), shift)
    axis = _unit(_quat_rotate(rotation, frame['axis']), connector.get('id') or '?', 'axis')
    normal = _unit(_quat_rotate(rotation, frame['normal']), connector.get('id') or '?', 'normal')
    updated = dict(connector)
    if isinstance(connector.get('frame'), dict):
        updated['frame'] = dict(connector['frame'], pos=_round_vector(pos),
                                axis=_round_vector(axis), normal=_round_vector(normal))
    else:
        updated.update(pos=_round_vector(pos), axis=_round_vector(axis),
                       normal=_round_vector(normal))
    return updated


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s 必须是有限数字' % label)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('%s 必须是有限数字' % label)
    return number


def _vector(value, label, key='向量'):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('MATE_CONNECTOR_MISSING: 端口 %s 的 %s 必须是三个数字'
                         % (label, key))
    return [_finite(item, '端口 %s.%s' % (label, key)) for item in value]


def _unit(value, label, key='向量'):
    vector = _vector(value, label, key)
    length = math.sqrt(_dot(vector, vector))
    if length < _EPSILON:
        raise ValueError('MATE_CONNECTOR_MISSING: 端口 %s 的 %s 不能是零向量'
                         % (label, key))
    return _scale(vector, 1.0 / length)


def _unit_quat(value):
    quat = value if isinstance(value, (list, tuple)) and len(value) == 4 else None
    if quat is None or any(isinstance(item, bool) or not isinstance(item, (int, float))
                           for item in quat):
        raise ValueError('MATE_CONNECTOR_MISSING: rotation 必须是四元数')
    numbers = [float(item) for item in quat]
    length = math.sqrt(sum(item * item for item in numbers))
    if length < _EPSILON:
        raise ValueError('MATE_CONNECTOR_MISSING: rotation 不能是零四元数')
    return [item / length for item in numbers]


def _round_vector(vector, digits=6):
    return [round(float(item), digits) for item in vector]


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return [left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0]]


def _add(left, right):
    return [a + b for a, b in zip(left, right)]


def _sub(left, right):
    return [a - b for a, b in zip(left, right)]


def _scale(vector, factor):
    return [item * factor for item in vector]


def _clamp(value):
    return max(-1.0, min(1.0, value))


def _quat_mul(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return [lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz]


def _quat_rotate(quat, vector):
    axis, scalar = quat[:3], quat[3]
    cross = _cross(axis, vector)
    return _add(_add(vector, _scale(cross, 2.0 * scalar)),
                _cross(axis, _scale(cross, 2.0)))


def _quat_between(source, target):
    cosine = _clamp(_dot(source, target))
    if cosine > 1.0 - 1e-12:
        return [0.0, 0.0, 0.0, 1.0]
    if cosine < -1.0 + 1e-12:
        axis = _cross(source, [1.0, 0.0, 0.0])
        if math.sqrt(_dot(axis, axis)) < 1e-6:
            axis = _cross(source, [0.0, 1.0, 0.0])
        axis = _unit(axis, 'mate', 'axis')
        return [axis[0], axis[1], axis[2], 0.0]
    axis = _cross(source, target)
    quat = [axis[0], axis[1], axis[2], 1.0 + cosine]
    length = math.sqrt(_dot(quat, quat))
    return [item / length for item in quat]


def _quat_axis_angle(axis, angle):
    half = angle / 2.0
    sine = math.sin(half)
    return [axis[0] * sine, axis[1] * sine, axis[2] * sine, math.cos(half)]


def _twist_angle(axis, source, target):
    source = _reject(axis, source)
    target = _reject(axis, target)
    if math.sqrt(_dot(source, source)) < 1e-6 or math.sqrt(_dot(target, target)) < 1e-6:
        return 0.0
    source = _unit(source, 'mate', 'normal')
    target = _unit(target, 'mate', 'normal')
    return math.atan2(_dot(_cross(source, target), axis), _dot(source, target))


def _reject(axis, vector):
    return _sub(vector, _scale(axis, _dot(vector, axis)))
