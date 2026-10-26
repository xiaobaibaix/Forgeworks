#!/usr/bin/env python3
"""部件布局与本地装配：Blender 按布局移动、缩放、旋转各部件并合并成整机。"""

import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

LAYOUT_SCHEMA_VERSION = 1
# 摆放规则版本：改算法后旧布局自动重算，避免缓存住有问题的自动摆放。
LAYOUT_VERSION = 2
BLENDER_TIMEOUT = 600
DEFAULT_GAP = 0.02
DEFAULT_DECIMATE_FACES = 10000
# 铲斗安装耳通常比包围盒顶面低一截，按斗高比例估计；末端再压进动臂一点，
# 避免只按包围盒顶/底对齐时留下肉眼可见的悬空。
BUCKET_X_OVERLAP = 0.05
BUCKET_EAR_DROP = 0.17
BUCKET_JOINT_SINK = 0.03
BOOM_TIP_RISE = 0.006
# 整体效果图视觉分析的可用提示；越界值直接夹住，缺失值退回启发式默认。
LAYOUT_HINT_RANGES = {
    'groundLengthRatio': (0.6, 2.0),
    'boomLengthRatio': (0.5, 2.2),
    'bucketWidthRatio': (0.25, 1.0),
}
LAYOUT_CAB_SIDES = ('left', 'right')


def normalize_layout_hints(value):
    """把视觉模型返回的自由 JSON 收敛成布局能安全使用的少量数值。"""
    if not isinstance(value, dict):
        return {}
    hints = {}
    for key, (low, high) in LAYOUT_HINT_RANGES.items():
        try:
            number = float(value.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            hints[key] = round(max(low, min(high, number)), 4)
    side = str(value.get('cabSide') or '').strip().lower()
    if side in LAYOUT_CAB_SIDES:
        hints['cabSide'] = side
    return hints


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s 必须是数字' % label)
    return float(value)


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('%s 必须是三维数组' % label)
    return [_number(item, label) for item in value]


def _bbox(value, label):
    if not isinstance(value, dict):
        raise ValueError('%s 必须是对象' % label)
    low = _vector(value.get('min'), label + '.min')
    high = _vector(value.get('max'), label + '.max')
    if any(high[i] < low[i] for i in range(3)) or all(high[i] == low[i] for i in range(3)):
        raise ValueError('%s 的包围盒无效' % label)
    return {'min': low, 'max': high}


def _relative_mesh(root, mesh):
    text = str(mesh or '').strip().replace('\\', '/')
    if not text:
        raise ValueError('部件缺少模型路径')
    if not os.path.isabs(text):
        return text
    root_real = os.path.realpath(root)
    absolute = os.path.realpath(text)
    if os.path.commonpath((root_real, absolute)) != root_real:
        raise ValueError('部件模型越出管线目录：' + text)
    return os.path.relpath(absolute, root_real).replace(os.sep, '/')


def resolve_layout_mesh(root, mesh):
    text = str(mesh or '').strip().replace('\\', '/')
    if not text or os.path.isabs(text):
        raise ValueError('布局里的 mesh 必须是管线目录内的相对路径：' + (text or '(空)'))
    segments = [segment for segment in text.split('/') if segment not in ('', '.')]
    if '..' in segments:
        raise ValueError('布局里的 mesh 不能越出管线目录：' + text)
    root_real = os.path.realpath(root)
    absolute = os.path.realpath(os.path.join(root_real, *segments))
    if os.path.commonpath((root_real, absolute)) != root_real or not os.path.isfile(absolute):
        raise ValueError('部件模型不存在或越界：' + text)
    return absolute


def _layout_part(item, index):
    label = 'parts[%d]' % index
    if not isinstance(item, dict):
        raise ValueError(label + ' 必须是对象')
    part_id = str(item.get('id') or '').strip()
    if not part_id:
        raise ValueError(label + '.id 不能为空')
    mesh = str(item.get('mesh') or '').strip().replace('\\', '/')
    if not mesh or os.path.isabs(mesh) or '..' in mesh.split('/'):
        raise ValueError(label + '.mesh 必须是管线目录内的相对路径')
    source_mesh = str(item.get('sourceMesh') or '').strip().replace('\\', '/')
    if source_mesh and ('..' in source_mesh.split('/')):
        raise ValueError(label + '.sourceMesh 不能越出管线目录')
    scale = _number(item.get('scale', 1.0), label + '.scale')
    if scale <= 0:
        raise ValueError(label + '.scale 必须为正数')
    ground = item.get('ground', True)
    if not isinstance(ground, bool):
        raise ValueError(label + '.ground 必须是布尔值')
    return {
        'id': part_id,
        'name': str(item.get('name') or part_id),
        'mesh': mesh,
        'sourceMesh': source_mesh,
        'description': str(item.get('description') or ''),
        'sourceBbox': _bbox(item.get('sourceBbox'), label + '.sourceBbox'),
        'scale': scale,
        'translate': _vector(item.get('translate', [0, 0, 0]), label + '.translate'),
        'rotationZ': _number(item.get('rotationZ', 0), label + '.rotationZ'),
        'ground': ground,
    }


def normalize_layout(data):
    if not isinstance(data, dict):
        raise ValueError('布局必须是 JSON 对象')
    if data.get('schemaVersion') != LAYOUT_SCHEMA_VERSION:
        raise ValueError('布局 schemaVersion 必须为 %d' % LAYOUT_SCHEMA_VERSION)
    parts_in = data.get('parts')
    if not isinstance(parts_in, list):
        raise ValueError('布局缺少 parts')
    parts, seen = [], set()
    for index, item in enumerate(parts_in):
        part = _layout_part(item, index)
        if part['mesh'] in seen:
            raise ValueError('布局里 mesh 重复：' + part['mesh'])
        seen.add(part['mesh'])
        parts.append(part)
    decimate_faces = data.get('decimateFaces')
    if decimate_faces in (None, ''):
        decimate_faces = None
    else:
        try:
            decimate_faces = max(0, int(decimate_faces))
        except (TypeError, ValueError):
            raise ValueError('布局 decimateFaces 必须是非负整数')
    try:
        layout_version = int(data.get('layoutVersion') or 0)
    except (TypeError, ValueError):
        raise ValueError('布局 layoutVersion 必须是整数')
    return {
        'schemaVersion': LAYOUT_SCHEMA_VERSION,
        'layoutVersion': layout_version,
        'assetId': str(data.get('assetId') or ''),
        'nodeId': str(data.get('nodeId') or ''),
        'assemblyPrompt': str(data.get('assemblyPrompt') or ''),
        'layoutMode': str(data.get('layoutMode') or ''),
        'decimateFaces': decimate_faces,
        'layoutHints': normalize_layout_hints(data.get('layoutHints')),
        'referenceImage': str(data.get('referenceImage') or ''),
        'updatedAt': data.get('updatedAt') if isinstance(data.get('updatedAt'), str) else None,
        'parts': parts,
    }


def load_layout(path):
    try:
        with open(path, encoding='utf-8') as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise ValueError('布局文件不是合法 JSON：%s' % error)
    return normalize_layout(data)


def save_layout(path, layout):
    absolute = os.path.abspath(path)
    os.makedirs(os.path.dirname(absolute), exist_ok=True)
    tmp = absolute + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(layout, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, absolute)


def find_blender():
    custom = os.environ.get('FW_BLENDER')
    if custom and os.path.isfile(custom):
        return custom
    found = shutil.which('blender')
    if found:
        return found
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge_config.json')
    try:
        with open(config_path, encoding='utf-8') as stream:
            configured = (json.load(stream).get('blender') or {}).get('path')
        if isinstance(configured, str) and os.path.isfile(configured):
            return configured
    except (OSError, ValueError):
        pass
    candidates = ['/Applications/Blender.app/Contents/MacOS/Blender']
    candidates += sorted(glob.glob('/Volumes/*/app/Blender.app/Contents/MacOS/Blender'))
    return next((path for path in candidates if os.path.isfile(path)), None)


def _run_blender(blender_path, arguments, label):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fw_blender.py')
    with tempfile.TemporaryDirectory(prefix='forgeworks-parts-') as temp_dir:
        report_path = os.path.join(temp_dir, 'report.json')
        command = [blender_path, '--background', '--factory-startup', '--python-exit-code', '1',
                   '--python', script, '--', '--report', report_path] + arguments
        try:
            completed = subprocess.run(command, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace',
                                       timeout=BLENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ValueError('%s 超时（%d 秒）' % (label, BLENDER_TIMEOUT))
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
        if not report.get('valid'):
            raise ValueError('%s 失败：%s' % (label, '; '.join(report.get('errors') or ['未知错误'])))
        return report


def measure_parts(blender_path, mesh_paths):
    paths = [os.path.realpath(path) for path in mesh_paths]
    if not paths:
        raise ValueError('没有可测量的部件模型')
    report = _run_blender(blender_path, ['--mode', 'measure', '--inputs'] + paths, '部件测量')
    measured = {}
    for item in report.get('files') or []:
        path = os.path.realpath(str(item.get('path') or ''))
        measured[path] = {
            'min': [float(value) for value in item['min']],
            'max': [float(value) for value in item['max']],
            'triangles': int(item.get('triangles') or 0),
        }
    missing = [path for path in paths if path not in measured]
    if missing:
        raise ValueError('Blender 未测量到部件：' + '、'.join(os.path.basename(path) for path in missing))
    return measured


def auto_layout(entries, gap=DEFAULT_GAP):
    """把部件按接入顺序沿 X 轴并排、底面贴地；尺寸与朝向仍需人工或 AI 调整。"""
    laid_out, cursor = [], 0.0
    for index, entry in enumerate(entries):
        bbox = entry.get('sourceBbox')
        if not isinstance(bbox, dict):
            raise ValueError('自动布局需要部件的 sourceBbox')
        low = [_number(value, 'sourceBbox.min') for value in bbox.get('min') or []]
        high = [_number(value, 'sourceBbox.max') for value in bbox.get('max') or []]
        invalid = (len(low) != 3 or len(high) != 3
                   or any(high[i] < low[i] for i in range(3))
                   or all(high[i] == low[i] for i in range(3)))
        if invalid:
            raise ValueError('部件 %s 的包围盒无效' % (entry.get('id') or index))
        if index:
            cursor += gap
        translate = [round(cursor - low[0], 6),
                     round(-(low[1] + high[1]) / 2, 6),
                     round(-low[2], 6)]
        cursor += high[0] - low[0]
        laid_out.append({
            'id': str(entry.get('id') or 'part_%d' % index),
            'name': str(entry.get('name') or entry.get('id') or '部件 %d' % (index + 1)),
            'mesh': entry['mesh'],
            'sourceMesh': str(entry.get('sourceMesh') or entry['mesh']),
            'description': str(entry.get('description') or ''),
            'sourceBbox': {'min': [round(value, 6) for value in low],
                           'max': [round(value, 6) for value in high]},
            'scale': 1.0,
            'translate': translate,
            'rotationZ': 0.0,
            'ground': True,
        })
    return laid_out


# 角色按“更具体的词优先”排列，避免“斗杆”被当成“铲斗”。
PART_ROLE_WORDS = (
    ('roof', ('车顶', '顶盖', '顶棚', 'roof')),
    ('boom', ('动臂', '大臂', '斗杆', '小臂', '机械臂', 'boom', 'jib', 'arm')),
    ('bucket', ('铲斗', '挖斗', '斗齿', 'bucket', 'grapple')),
    ('cab', ('驾驶室', '驾驶舱', '操作室', 'cab', 'cockpit', 'cabin')),
    ('track', ('履带', '底盘', '行走机构', 'track', 'crawler', 'undercarriage', 'tread')),
    ('wheel', ('轮胎', '车轮', '轮子', 'wheel', 'tire', 'tyre')),
    ('door', ('车门', 'door')),
    ('window', ('车窗', '玻璃', 'window')),
    ('body', ('车身', '车体', '机身', '机体', '主体', 'chassis', 'hull', 'body')),
)


def part_role(entry):
    text = ' '.join(str(entry.get(key) or '') for key in ('id', 'name', 'description')).lower()
    for role, words in PART_ROLE_WORDS:
        if any(word in text for word in words):
            return role
    return 'other'


def _entry_bounds(entry):
    bbox = entry.get('sourceBbox')
    if not isinstance(bbox, dict):
        raise ValueError('整体布局需要部件的 sourceBbox')
    low = [_number(value, 'sourceBbox.min') for value in bbox.get('min') or []]
    high = [_number(value, 'sourceBbox.max') for value in bbox.get('max') or []]
    invalid = (len(low) != 3 or len(high) != 3
               or any(high[i] < low[i] for i in range(3))
               or all(high[i] == low[i] for i in range(3)))
    if invalid:
        raise ValueError('部件 %s 的包围盒无效' % (entry.get('id') or entry.get('name')))
    return low, high


def _bounds_after_transform(low, high, scale=1.0, rotation_z=0.0):
    """Z 轴旋转 + 均匀缩放后的局部包围盒；用于把部件边缘对齐到装配锚点。"""
    radians = math.radians(float(rotation_z))
    cos_value, sin_value = math.cos(radians), math.sin(radians)
    points = []
    for x_value in (low[0] * scale, high[0] * scale):
        for y_value in (low[1] * scale, high[1] * scale):
            for z_value in (low[2] * scale, high[2] * scale):
                points.append((x_value * cos_value - y_value * sin_value,
                               x_value * sin_value + y_value * cos_value,
                               z_value))
    return ([min(point[i] for point in points) for i in range(3)],
            [max(point[i] for point in points) for i in range(3)])


def _layout_entry(entry, scale, translate, rotation_z=0.0, ground=False):
    low, high = _entry_bounds(entry)
    return {
        'id': str(entry.get('id') or entry.get('name') or 'part'),
        'name': str(entry.get('name') or entry.get('id') or '部件'),
        'mesh': entry['mesh'],
        'sourceMesh': str(entry.get('sourceMesh') or entry['mesh']),
        'description': str(entry.get('description') or ''),
        'sourceBbox': {'min': [round(value, 6) for value in low],
                       'max': [round(value, 6) for value in high]},
        'scale': round(float(scale), 6),
        'translate': [round(float(value), 6) for value in translate],
        'rotationZ': round(float(rotation_z), 6),
        'ground': bool(ground),
    }


def coherent_layout(entries, hints=None):
    """按部件角色拼成一台整机；角色不足以判断时返回 None，交给并排布局。

    规则是粗粒度的：履带/车轮在下、车身压在上面、驾驶室在车身前上、
    动臂从车头伸出、铲斗挂在动臂末端。单件模型通常各自被归一化，
    所以这里按车身尺寸重新恢复相对比例，而不是直接等比例摆放。
    hints 可来自整体效果图的视觉分析，只覆盖少量比例和驾驶室左右侧。
    """
    hints = normalize_layout_hints(hints)
    role_entries = {}
    for entry in entries:
        role = part_role(entry)
        if role == 'other':
            return None
        role_entries.setdefault(role, []).append(entry)
    if not role_entries.get('body'):
        return None
    if len(role_entries) < 2:
        return None
    # 这些角色只能有一个；多件时无法可靠判断左右/串联关系，退回并排布局。
    for role in ('body', 'track', 'wheel', 'boom', 'bucket', 'cab', 'roof'):
        if len(role_entries.get(role) or []) > 1:
            return None
    if role_entries.get('track') and role_entries.get('wheel'):
        return None
    body_entry = role_entries['body'][0]
    body_low, body_high = _entry_bounds(body_entry)
    body_size = [body_high[i] - body_low[i] for i in range(3)]
    body_length, body_width, body_height = body_size[0], body_size[1], body_size[2]
    if body_length <= 0 or body_width <= 0 or body_height <= 0:
        return None

    laid_out = {}
    ground_entry = (role_entries.get('track') or [None])[0] or (role_entries.get('wheel') or [None])[0]
    ground_top = 0.0
    if ground_entry:
        ground_low, ground_high = _entry_bounds(ground_entry)
        ground_size = [ground_high[i] - ground_low[i] for i in range(3)]
        ground_rotation = 90.0 if ground_size[1] > ground_size[0] * 1.05 else 0.0
        rotated_low, rotated_high = _bounds_after_transform(ground_low, ground_high, 1.0, ground_rotation)
        rotated_length = rotated_high[0] - rotated_low[0]
        rotated_width = rotated_high[1] - rotated_low[1]
        ground_ratio = hints.get('groundLengthRatio')
        if ground_ratio is None:
            ground_ratio = 1.2 if 'track' in role_entries else 0.9
        target_length = body_length * ground_ratio
        ground_scale = target_length / rotated_length if rotated_length > 0 else 1.0
        if rotated_width * ground_scale > body_width * 1.35:
            ground_scale = body_width * 1.35 / rotated_width
        placed_low, placed_high = _bounds_after_transform(
            ground_low, ground_high, ground_scale, ground_rotation)
        translate = [-(placed_low[0] + placed_high[0]) / 2,
                     -(placed_low[1] + placed_high[1]) / 2,
                     -placed_low[2]]
        laid_out[ground_entry['id']] = _layout_entry(
            ground_entry, ground_scale, translate, ground_rotation, ground=False)
        ground_top = placed_high[2] - placed_low[2]

    body_translate = [-(body_low[0] + body_high[0]) / 2,
                      -(body_low[1] + body_high[1]) / 2,
                      ground_top - body_low[2]]
    laid_out[body_entry['id']] = _layout_entry(body_entry, 1.0, body_translate)
    body_front = body_translate[0] + body_high[0]
    body_center_y = body_translate[1] + (body_low[1] + body_high[1]) / 2
    body_top = ground_top + body_height
    body_half_width = body_width / 2

    cab_entry = (role_entries.get('cab') or [None])[0]
    if cab_entry:
        cab_low, cab_high = _entry_bounds(cab_entry)
        cab_size = [cab_high[i] - cab_low[i] for i in range(3)]
        cab_scale = min(body_height * 1.6 / cab_size[2],
                        body_width * 0.75 / cab_size[1],
                        body_length * 0.55 / cab_size[0])
        cab_scale = max(cab_scale, 0.01)
        cab_width = cab_size[0] * cab_scale
        cab_depth = cab_size[1] * cab_scale
        # 机头朝 +X 时，+Y 是左侧，-Y 是右侧。
        cab_side = 1.0 if hints.get('cabSide', 'left') == 'left' else -1.0
        cab_translate = [body_front - body_length * 0.05 - cab_width / 2,
                         body_center_y + cab_side * (body_half_width - cab_depth / 2 - body_width * 0.03),
                         body_top - cab_low[2] * cab_scale]
        laid_out[cab_entry['id']] = _layout_entry(cab_entry, cab_scale, cab_translate)

    boom_entry = (role_entries.get('boom') or [None])[0]
    boom_tip_x = None
    boom_low_z = None
    boom_length = 0.0
    if boom_entry:
        boom_low, boom_high = _entry_bounds(boom_entry)
        boom_size = [boom_high[i] - boom_low[i] for i in range(3)]
        boom_rotation = 90.0 if boom_size[1] > boom_size[0] * 1.05 else 0.0
        rotated_low, rotated_high = _bounds_after_transform(boom_low, boom_high, 1.0, boom_rotation)
        rotated_length = rotated_high[0] - rotated_low[0]
        boom_ratio = hints.get('boomLengthRatio', 1.15)
        boom_scale = body_length * boom_ratio / rotated_length if rotated_length > 0 else 1.0
        placed_low, placed_high = _bounds_after_transform(
            boom_low, boom_high, boom_scale, boom_rotation)
        target_low_z = body_top - body_height * 0.25
        boom_translate = [body_front - placed_low[0],
                          -(placed_low[1] + placed_high[1]) / 2,
                          target_low_z - placed_low[2]]
        laid_out[boom_entry['id']] = _layout_entry(
            boom_entry, boom_scale, boom_translate, boom_rotation)
        boom_tip_x = boom_translate[0] + placed_high[0]
        boom_low_z = boom_translate[2] + placed_low[2]
        boom_length = placed_high[0] - placed_low[0]

    bucket_entry = (role_entries.get('bucket') or [None])[0]
    if bucket_entry:
        bucket_low, bucket_high = _entry_bounds(bucket_entry)
        bucket_size = [bucket_high[i] - bucket_low[i] for i in range(3)]
        bucket_rotation = 90.0 if bucket_size[0] > bucket_size[1] * 1.05 else 0.0
        rotated_low, rotated_high = _bounds_after_transform(
            bucket_low, bucket_high, 1.0, bucket_rotation)
        rotated_width = rotated_high[1] - rotated_low[1]
        bucket_ratio = hints.get('bucketWidthRatio', 0.6)
        bucket_scale = body_width * bucket_ratio / rotated_width if rotated_width > 0 else 1.0
        placed_low, placed_high = _bounds_after_transform(
            bucket_low, bucket_high, bucket_scale, bucket_rotation)
        if boom_tip_x is not None:
            rear_x = boom_tip_x - body_length * BUCKET_X_OVERLAP
            bucket_height = placed_high[2] - placed_low[2]
            ear_top = placed_high[2] - bucket_height * BUCKET_EAR_DROP
            boom_tip_low = boom_low_z + boom_length * BOOM_TIP_RISE
            joint_z = boom_tip_low + bucket_height * BUCKET_JOINT_SINK
            bucket_translate = [rear_x - placed_low[0],
                                -(placed_low[1] + placed_high[1]) / 2,
                                joint_z - ear_top]
        else:
            rear_x = body_front + body_length * 0.05
            bucket_translate = [rear_x - placed_low[0],
                                -(placed_low[1] + placed_high[1]) / 2,
                                -placed_low[2]]
        laid_out[bucket_entry['id']] = _layout_entry(
            bucket_entry, bucket_scale, bucket_translate, bucket_rotation)

    roof_entry = (role_entries.get('roof') or [None])[0]
    if roof_entry:
        roof_low, roof_high = _entry_bounds(roof_entry)
        roof_size = [roof_high[i] - roof_low[i] for i in range(3)]
        roof_scale = min(body_width * 0.8 / roof_size[1],
                         body_length * 0.55 / roof_size[0])
        roof_scale = max(roof_scale, 0.01)
        roof_translate = [body_translate[0] - body_length * 0.1,
                          body_center_y,
                          body_top - roof_low[2] * roof_scale]
        laid_out[roof_entry['id']] = _layout_entry(roof_entry, roof_scale, roof_translate)

    side_entries = (role_entries.get('door') or []) + (role_entries.get('window') or [])
    for index, side_entry in enumerate(side_entries):
        side_low, side_high = _entry_bounds(side_entry)
        side_size = [side_high[i] - side_low[i] for i in range(3)]
        side_scale = min(body_length * 0.35 / side_size[0],
                         body_height * 0.4 / side_size[2])
        side_scale = max(side_scale, 0.01)
        placed_low, placed_high = _bounds_after_transform(side_low, side_high, side_scale)
        count = max(1, len(side_entries))
        spread = body_length * 0.28
        offset = 0.0 if count == 1 else spread * (index / (count - 1) - 0.5)
        side_translate = [offset - (placed_low[0] + placed_high[0]) / 2,
                          body_half_width - placed_low[1],
                          body_top - body_height * 0.55 - placed_low[2]]
        laid_out[side_entry['id']] = _layout_entry(
            side_entry, side_scale, side_translate)

    return [laid_out[entry['id']] for entry in entries]


def _decimated_path(root, entry, target_faces):
    safe_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(entry.get('id') or 'part'))
    stem = os.path.splitext(os.path.basename(entry['absolute']))[0]
    safe_stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', stem)
    return os.path.join(root, 'parts', 'decimated',
                        '%s_%s_%d.glb' % (safe_id, safe_stem, int(target_faces)))


def _decimate_entries(blender, root, entries, target_faces):
    """组装前逐件减面；已存在的同目标缓存直接复用。返回减面记录。"""
    records = []
    for entry in entries:
        entry['actual'] = entry['absolute']
        entry['actualMesh'] = entry['mesh']
        entry['decimated'] = False
        if target_faces and entry['sourceTriangles'] > target_faces:
            output = _decimated_path(root, entry, target_faces)
            os.makedirs(os.path.dirname(output), exist_ok=True)
            reusable = (os.path.isfile(output)
                        and os.path.getmtime(output) >= os.path.getmtime(entry['absolute']))
            if not reusable:
                try:
                    os.remove(output)
                except OSError:
                    pass
                report = _run_blender(
                    blender,
                    ['--mode', 'decimate', '--input', entry['absolute'],
                     '--output', output, '--target-faces', str(int(target_faces))],
                    '部件减面 %s' % entry['name'])
                if not report.get('valid'):
                    raise ValueError('; '.join(report.get('errors') or []) or 'Blender 减面失败')
            entry['actual'] = output
            entry['actualMesh'] = os.path.relpath(output, root).replace(os.sep, '/')
            entry['decimated'] = True
            records.append({'id': entry['id'], 'name': entry['name'],
                            'sourceTriangles': entry['sourceTriangles'],
                            'targetFaces': int(target_faces),
                            'mesh': entry['actualMesh'],
                            'cached': bool(reusable)})
    return records


def _plan_part(entry, mesh_path=None):
    scale = float(entry['scale'])
    translate = [float(value) for value in entry['translate']]
    if entry['ground']:
        translate[2] = round(-entry['sourceBbox']['min'][2] * scale, 6)
    return {
        'id': entry['id'],
        'name': entry['name'],
        'mesh': mesh_path or entry['mesh'],
        'scale': round(scale, 6),
        'translate': [round(value, 6) for value in translate],
        'rotationZ': round(float(entry['rotationZ']), 6),
    }, translate


def assemble_parts(parts, output_path, layout_path, root, assembly_prompt='',
                   reset=False, blender_path=None, asset_id='', node_id='',
                   preserve_absent=False, decimate_faces=0, layout_mode='coherent',
                   layout_hints=None, reference_image=''):
    """先按目标面数逐件减面，再按角色整体布局合并；布局缺失/reset/模式变化时重新生成。

    existing 布局里的手动变换优先；preserve_absent 时保留未接入部件的旧布局。
    layout_mode='auto' 可恢复旧的沿 X 轴并排行为。
    layout_hints 来自整体效果图的视觉分析；提示变化会自动重算布局。
    """
    if not parts:
        raise ValueError('没有可组装的部件模型')
    if layout_mode not in ('auto', 'coherent'):
        raise ValueError('layout_mode 只能是 auto 或 coherent')
    hints = normalize_layout_hints(layout_hints)
    blender = blender_path or find_blender()
    if not blender:
        raise ValueError('未找到 Blender：请用 --blender 指定，或配置 tools/bridge_config.json')
    root = os.path.realpath(root)
    target_faces = max(0, int(decimate_faces or 0))

    entries, seen = [], set()
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise ValueError('部件参数必须是对象')
        mesh = _relative_mesh(root, part.get('mesh'))
        if mesh in seen:
            raise ValueError('同一个部件模型被重复接入：' + mesh)
        seen.add(mesh)
        entries.append({
            'id': str(part.get('id') or 'part_%d' % index),
            'name': str(part.get('name') or part.get('id') or '部件 %d' % (index + 1)),
            'description': str(part.get('description') or ''),
            'mesh': mesh,
            'sourceMesh': mesh,
            'absolute': resolve_layout_mesh(root, mesh),
        })

    measured = measure_parts(blender, [entry['absolute'] for entry in entries])
    for entry in entries:
        measurement = measured[entry['absolute']]
        entry['sourceBbox'] = {'min': [round(value, 6) for value in measurement['min']],
                               'max': [round(value, 6) for value in measurement['max']]}
        entry['sourceTriangles'] = measurement['triangles']

    warnings = []
    decimated = _decimate_entries(blender, root, entries, target_faces)
    if target_faces:
        actual = measure_parts(blender, [entry['actual'] for entry in entries])
        for entry in entries:
            measurement = actual[entry['actual']]
            entry['sourceBbox'] = {'min': [round(value, 6) for value in measurement['min']],
                                   'max': [round(value, 6) for value in measurement['max']]}
            entry['actualTriangles'] = measurement['triangles']
        if decimated:
            before = sum(item['sourceTriangles'] for item in decimated)
            after = sum(entry['actualTriangles'] for entry in entries if entry['decimated'])
            warnings.append('组装前已减面：%d 个部件 %d → %d 面（每件最多 %d 面）'
                            % (len(decimated), before, after, target_faces))
    else:
        for entry in entries:
            entry['actualTriangles'] = entry['sourceTriangles']

    layout_inputs = [dict(entry, mesh=entry['actualMesh']) for entry in entries]
    auto_parts = auto_layout(layout_inputs)
    coherent_parts = (coherent_layout(layout_inputs, hints=hints)
                      if layout_mode == 'coherent' else None)
    effective_mode = 'coherent' if coherent_parts else 'auto'
    if layout_mode == 'coherent' and not coherent_parts:
        warnings.append('未识别出车身/履带/驾驶室等部件角色，退回沿 X 轴并排布局')
    base_parts = coherent_parts or auto_parts
    base_by_source = {str(item.get('sourceMesh') or item['mesh']): item for item in base_parts}

    existing = None if reset else load_layout(layout_path)
    if existing and effective_mode == 'coherent' and not existing.get('layoutMode'):
        warnings.append('旧布局不是整体布局，已按部件角色重新生成')
        existing = None
    elif existing and int(existing.get('layoutVersion') or 0) != LAYOUT_VERSION:
        warnings.append('布局由旧版摆放规则生成，已按当前规则重新计算（旧的手动调整会被覆盖）')
        existing = None
    elif existing and existing.get('layoutMode') and existing['layoutMode'] != effective_mode:
        warnings.append('布局模式由 %s 变为 %s，已重新生成'
                        % (existing['layoutMode'], effective_mode))
        existing = None
    elif (existing and hints
          and normalize_layout_hints(existing.get('layoutHints') or {}) != hints):
        # 只有拿到新的视觉提示才覆盖；视觉分析失败时保留旧布局和手动调整。
        warnings.append('整体效果图的视觉分析结果有变化，已按新参考重新布局')
        existing = None

    existing_by_source, preserved = {}, []
    if existing:
        for item in existing['parts']:
            existing_by_source[str(item.get('sourceMesh') or item['mesh'])] = item
        dropped = [key for key in existing_by_source if key not in seen]
        if dropped and preserve_absent:
            preserved = [existing_by_source[key] for key in dropped]
        elif dropped:
            warnings.append('布局里有 %d 个部件已不再接入，已丢弃：%s'
                            % (len(dropped), '、'.join(os.path.basename(key) for key in dropped)))
        added = [entry['sourceMesh'] for entry in entries if entry['sourceMesh'] not in existing_by_source]
        if added:
            warnings.append('%d 个新部件已自动补位，可在布局文件里调整' % len(added))
    else:
        if effective_mode == 'coherent':
            warnings.append('已按部件角色生成整体布局：履带在下、车身在上、驾驶室/动臂/铲斗依次归位')
        else:
            warnings.append('已自动生成布局：沿 X 轴并排贴地，可在布局文件里调整后重跑')

    layout_parts, plan_parts, records = [], [], []
    decimated_by_id = {item['id']: item for item in decimated}
    for entry in entries:
        source_key = entry['sourceMesh']
        existing_entry = existing_by_source.get(source_key)
        base = existing_entry or base_by_source[source_key]
        layout_entry = {
            'id': entry['id'],
            'name': (existing_entry or {}).get('name') or entry['name'] or base['name'],
            'mesh': entry['actualMesh'],
            'sourceMesh': source_key,
            'description': entry['description'] or base['description'],
            'sourceBbox': entry['sourceBbox'],
            'scale': float(base['scale']),
            'translate': [float(value) for value in base['translate']],
            'rotationZ': float(base['rotationZ']),
            'ground': bool(base['ground']),
        }
        plan_part, effective = _plan_part(layout_entry, entry['actual'])
        plan_parts.append(plan_part)
        # 写回实际落地的 translate，AI 关掉 ground 时仍保留贴地位置
        layout_entry['translate'] = effective
        layout_parts.append(layout_entry)
        record = {'id': entry['id'], 'name': entry['name'], 'mesh': entry['actualMesh'],
                  'sourceMesh': source_key, 'sourceTriangles': entry['sourceTriangles'],
                  'trianglesBefore': entry['sourceTriangles'],
                  'decimated': bool(entry['decimated'])}
        if entry['id'] in decimated_by_id:
            decimated_by_id[entry['id']]['triangles'] = entry['actualTriangles']
        records.append(record)
    if preserved:
        warnings.append('%d 个未就绪部件的旧布局已保留，重跑时可继续使用' % len(preserved))
        layout_parts.extend(preserved)

    snaps = []
    if effective_mode == 'coherent':
        role_ids = {part_role(item): item['id'] for item in layout_inputs}
        if role_ids.get('boom') and role_ids.get('bucket'):
            snaps = [{'part': role_ids['bucket'], 'to': role_ids['boom']}]

    absolute_output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(absolute_output), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='forgeworks-assemble-') as temp_dir:
        plan_path = os.path.join(temp_dir, 'plan.json')
        with open(plan_path, 'w', encoding='utf-8') as stream:
            json.dump({'schemaVersion': LAYOUT_SCHEMA_VERSION, 'parts': plan_parts,
                       'snaps': snaps}, stream, ensure_ascii=False)
        assembled = _run_blender(blender, ['--mode', 'assemble', '--plan', plan_path,
                                           '--output', absolute_output], '部件装配')

    world = {str(item.get('id')): item for item in assembled.get('parts') or []}
    for record in records:
        final = world.get(record['id'])
        record['worldBbox'] = ({'min': final['min'], 'max': final['max']} if final else None)
        record['triangles'] = int(final.get('triangles') or 0) if final else 0
        if final is not None and record['triangles'] == 0:
            warnings.append('部件 %s 装配后没有面' % record['name'])
        # Blender 可能按真实网格做了挂接补位，以实际落地位置为准。
        if final is not None and isinstance(final.get('location'), list):
            for layout_part in layout_parts:
                if str(layout_part.get('id')) == record['id']:
                    layout_part['translate'] = [round(float(value), 6)
                                                for value in final['location']]

    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    layout = {'schemaVersion': LAYOUT_SCHEMA_VERSION, 'layoutVersion': LAYOUT_VERSION,
              'assetId': asset_id, 'nodeId': node_id or '', 'assemblyPrompt': assembly_prompt,
              'layoutMode': effective_mode, 'decimateFaces': target_faces or None,
              'layoutHints': hints, 'referenceImage': reference_image,
              'updatedAt': stamp, 'parts': layout_parts}
    save_layout(layout_path, layout)

    report = {'valid': True, 'assetId': asset_id, 'nodeId': node_id or '',
              'output': absolute_output, 'layout': os.path.abspath(layout_path),
              'blender': blender, 'assemblyPrompt': assembly_prompt,
              'layoutMode': effective_mode, 'decimateFaces': target_faces or None,
              'layoutHints': hints, 'referenceImage': reference_image,
              'decimated': decimated, 'parts': records, 'warnings': warnings}
    with open(os.path.splitext(absolute_output)[0] + '.report.json', 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)

    return {
        'meshPath': os.path.basename(absolute_output),
        'outputPath': absolute_output,
        'layoutPath': os.path.abspath(layout_path),
        'layoutMode': effective_mode,
        'decimateFaces': target_faces or None,
        'layoutHints': hints,
        'referenceImage': reference_image,
        'decimated': decimated,
        'parts': [{'id': record['id'], 'name': record['name'],
                   'triangles': record['triangles']} for record in records],
        'triangles': sum(record['triangles'] for record in records),
        'trianglesBefore': sum(record['trianglesBefore'] for record in records),
        'warnings': warnings,
        'engine': 'blender',
        'updatedAt': stamp,
    }


def main():
    parser = argparse.ArgumentParser(description='Forgeworks 部件布局与本地装配')
    sub = parser.add_subparsers(dest='command', required=True)
    assemble_cmd = sub.add_parser('assemble', help='按已有布局文件重新装配')
    assemble_cmd.add_argument('--layout', required=True)
    assemble_cmd.add_argument('--root', required=True)
    assemble_cmd.add_argument('--out', required=True)
    assemble_cmd.add_argument('--blender')
    args = parser.parse_args()
    try:
        if not os.path.isfile(args.layout):
            raise ValueError('布局文件不存在：' + args.layout)
        layout = load_layout(args.layout)
        result = assemble_parts(
            [{'id': part['id'], 'name': part['name'], 'mesh': part['mesh'],
              'description': part['description']} for part in layout['parts']],
            args.out, args.layout, args.root,
            assembly_prompt=layout['assemblyPrompt'],
            blender_path=args.blender,
            asset_id=layout['assetId'], node_id=layout['nodeId'],
            decimate_faces=layout.get('decimateFaces') or 0,
            layout_mode=layout.get('layoutMode') or 'coherent',
            layout_hints=layout.get('layoutHints'),
            reference_image=layout.get('referenceImage') or '')
        print(json.dumps({'output': result['outputPath'], 'parts': len(result['parts']),
                          'triangles': result['triangles'], 'warnings': result['warnings']},
                         ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
