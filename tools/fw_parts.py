#!/usr/bin/env python3
"""分件契约与装配：按三视图包围盒把部件摆回一台整机。"""

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

SCHEMA_VERSION = 1
DEFAULT_OVERLAP = 0.02
MAX_OVERLAP = 0.2
ASPECT_TOLERANCE = 0.25
HEIGHT_MISMATCH = 0.15
SCALE_RANGE = (0.05, 20.0)
BLENDER_TIMEOUT = 600
FITS = ('contain', 'height')
PART_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s 必须是数字' % label)
    return float(value)


def _box(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('%s 必须是 [x, y, w, h]' % label)
    x, y, w, h = (_number(item, label) for item in value)
    if w <= 0 or h <= 0:
        raise ValueError('%s 的宽高必须为正' % label)
    return [x, y, w, h]


def _view(value, label):
    if not isinstance(value, dict):
        raise ValueError('%s 必须是对象' % label)
    width = _number(value.get('width'), label + '.width')
    height = _number(value.get('height'), label + '.height')
    ground = _number(value.get('ground'), label + '.ground')
    ppm = _number(value.get('pxPerMeter'), label + '.pxPerMeter')
    if width <= 0 or height <= 0 or ppm <= 0:
        raise ValueError('%s 的 width/height/pxPerMeter 必须为正' % label)
    if not 0 <= ground <= height:
        raise ValueError('%s.ground 必须落在图内' % label)
    return {'width': width, 'height': height, 'ground': ground,
            'pxPerMeter': ppm, 'flipX': bool(value.get('flipX'))}


def normalize_contract(data):
    if not isinstance(data, dict):
        raise ValueError('契约必须是 JSON 对象')
    if data.get('schemaVersion') != SCHEMA_VERSION:
        raise ValueError('契约 schemaVersion 必须为 %d' % SCHEMA_VERSION)
    asset_id = str(data.get('assetId') or '').strip()
    if not PART_ID_RE.fullmatch(asset_id):
        raise ValueError('assetId 非法')
    views_in = data.get('views')
    if not isinstance(views_in, dict):
        raise ValueError('缺少 views')
    views = {'front': _view(views_in.get('front'), 'views.front'),
             'side': _view(views_in.get('side'), 'views.side')}
    parts_in = data.get('parts')
    if not isinstance(parts_in, list) or not parts_in:
        raise ValueError('parts 不能为空')
    parts = []
    seen = set()
    for index, item in enumerate(parts_in):
        label = 'parts[%d]' % index
        if not isinstance(item, dict):
            raise ValueError(label + ' 必须是对象')
        part_id = str(item.get('id') or '').strip()
        if not PART_ID_RE.fullmatch(part_id):
            raise ValueError(label + '.id 非法')
        if part_id in seen:
            raise ValueError('部件 id 重复：' + part_id)
        seen.add(part_id)
        mesh = item.get('mesh')
        if not isinstance(mesh, str) or not mesh.strip():
            raise ValueError(label + '.mesh 不能为空')
        if os.path.isabs(mesh) or '..' in mesh.replace('\\', '/').split('/'):
            raise ValueError(label + '.mesh 必须是契约目录内的相对路径')
        fit = str(item.get('fit') or 'contain').strip().lower()
        if fit not in FITS:
            raise ValueError(label + '.fit 只支持 ' + ' / '.join(FITS))
        overlap = item.get('overlap')
        overlap = DEFAULT_OVERLAP if overlap is None else _number(overlap, label + '.overlap')
        if not 0 <= overlap <= MAX_OVERLAP:
            raise ValueError('%s.overlap 必须在 0–%.2f' % (label, MAX_OVERLAP))
        rotation = item.get('rotationZ')
        rotation = 0.0 if rotation is None else _number(rotation, label + '.rotationZ')
        scale = item.get('scale')
        if scale is not None:
            scale = _number(scale, label + '.scale')
            if scale <= 0:
                raise ValueError(label + '.scale 必须为正')
        parts.append({
            'id': part_id,
            'name': str(item.get('name') or part_id),
            'mesh': mesh.strip(),
            'front': _box(item.get('front'), label + '.front'),
            'side': _box(item.get('side'), label + '.side'),
            'fit': fit,
            'overlap': overlap,
            'rotationZ': rotation,
            'scale': scale,
            'regenerate': bool(item.get('regenerate')),
        })
    return {'schemaVersion': SCHEMA_VERSION, 'assetId': asset_id,
            'views': views, 'parts': parts}


def view_world_range(view, box):
    """正视图 x→世界 X，侧视图 x→世界 Y；两图 y 都从地面往上量。"""
    x, y, width, height = box
    left = (x - view['width'] / 2) / view['pxPerMeter']
    right = (x + width - view['width'] / 2) / view['pxPerMeter']
    bottom = (view['ground'] - (y + height)) / view['pxPerMeter']
    top = (view['ground'] - y) / view['pxPerMeter']
    if view['flipX']:
        left, right = -right, -left
    return (left, right), (bottom, top)


def target_box(views, part):
    (fx0, fx1), (fz0, fz1) = view_world_range(views['front'], part['front'])
    (sy0, sy1), (sz0, sz1) = view_world_range(views['side'], part['side'])
    warnings = []
    front_height, side_height = fz1 - fz0, sz1 - sz0
    if front_height > 0 and side_height > 0:
        drift = abs(front_height - side_height) / max(front_height, side_height)
        if drift > HEIGHT_MISMATCH:
            warnings.append('正/侧视图高度差 %d%%' % round(drift * 100))
    return {'min': [fx0, sy0, fz0], 'max': [fx1, sy1, fz1]}, warnings


def plan_part(part, target, measured):
    pmin = [float(value) for value in measured['min']]
    pmax = [float(value) for value in measured['max']]
    psize = [pmax[i] - pmin[i] for i in range(3)]
    if any(size <= 1e-9 for size in psize):
        raise ValueError('部件 %s 的包围盒无效' % part['id'])
    tmin, tmax = target['min'], target['max']
    tsize = [tmax[i] - tmin[i] for i in range(3)]
    ratios = [tsize[i] / psize[i] for i in range(3)]
    scale = min(ratios) if part['fit'] == 'contain' else ratios[2]
    scale *= 1 + part['overlap']
    manual = part['scale'] is not None
    if manual:
        scale = part['scale']
    rotation = math.radians(part['rotationZ'])
    center = [(pmin[i] + pmax[i]) / 2 for i in range(3)]
    scaled_x, scaled_y = center[0] * scale, center[1] * scale
    rotated_x = scaled_x * math.cos(rotation) - scaled_y * math.sin(rotation)
    rotated_y = scaled_x * math.sin(rotation) + scaled_y * math.cos(rotation)
    target_center = [(tmin[i] + tmax[i]) / 2 for i in range(3)]
    translate = [target_center[0] - rotated_x,
                 target_center[1] - rotated_y,
                 tmin[2] - pmin[2] * scale]
    flags = []
    if manual:
        flags.append('manual_scale')
    elif any(abs(ratio / scale - 1) > ASPECT_TOLERANCE for ratio in ratios):
        flags.append('aspect_mismatch')
    if not SCALE_RANGE[0] <= scale <= SCALE_RANGE[1]:
        flags.append('scale_outlier')
    return {'scale': round(scale, 6),
            'translate': [round(value, 6) for value in translate],
            'rotationZ': part['rotationZ'],
            'flags': flags,
            'targetSize': [round(size, 6) for size in tsize],
            'sourceSize': [round(size, 6) for size in psize]}


def _view_for_axis(height_size, axis_min, axis_max, px_per_meter, margin, ground):
    half = max(abs(axis_min), abs(axis_max)) * px_per_meter + margin
    return {'width': max(int(math.ceil(half * 2)), 1),
            'height': max(int(math.ceil(height_size * px_per_meter)) + margin * 2, 1),
            'ground': ground,
            'pxPerMeter': px_per_meter,
            'flipX': False}


def _box_in_view(bbox, axis, view):
    low = bbox['min'][axis] * view['pxPerMeter'] + view['width'] / 2
    high = bbox['max'][axis] * view['pxPerMeter'] + view['width'] / 2
    top = view['ground'] - bbox['max'][2] * view['pxPerMeter']
    bottom = view['ground'] - bbox['min'][2] * view['pxPerMeter']
    return [round(low, 3), round(top, 3), round(high - low, 3), round(bottom - top, 3)]


def contract_from_bboxes(asset_id, entries, px_per_meter=400, margin=20):
    """把一批世界包围盒反推成三视图契约，供粗切产物做往返验证。"""
    if not entries:
        raise ValueError('至少需要一个部件')
    mins = [min(item['bbox']['min'][i] for item in entries) for i in range(3)]
    maxs = [max(item['bbox']['max'][i] for item in entries) for i in range(3)]
    size = [maxs[i] - mins[i] for i in range(3)]
    ground = margin + maxs[2] * px_per_meter
    views = {
        'front': _view_for_axis(size[2], mins[0], maxs[0], px_per_meter, margin, ground),
        'side': _view_for_axis(size[2], mins[1], maxs[1], px_per_meter, margin, ground),
    }
    parts = []
    for item in entries:
        parts.append({
            'id': item['id'],
            'name': item.get('name') or item['id'],
            'mesh': item['mesh'],
            'front': _box_in_view(item['bbox'], 0, views['front']),
            'side': _box_in_view(item['bbox'], 1, views['side']),
            'fit': 'contain',
            'overlap': 0,
            'rotationZ': 0,
        })
    return {'schemaVersion': SCHEMA_VERSION, 'assetId': asset_id,
            'views': views, 'parts': parts}


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


def load_contract(path):
    with open(path, encoding='utf-8') as stream:
        return normalize_contract(json.load(stream))


def _resolve_meshes(contract, base_dir):
    root = os.path.realpath(base_dir)
    resolved = []
    for part in contract['parts']:
        path = os.path.realpath(os.path.join(root, part['mesh']))
        if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
            raise ValueError('部件文件不存在或越界：' + part['mesh'])
        resolved.append(path)
    return resolved


def assemble(contract_path, output_path, blender_path=None, report_path=None,
             parts_json_path=None):
    base_dir = os.path.dirname(os.path.abspath(contract_path))
    contract = load_contract(contract_path)
    blender = blender_path or find_blender()
    if not blender:
        raise ValueError('未找到 Blender：请用 --blender 指定，或配置 tools/bridge_config.json')
    meshes = _resolve_meshes(contract, base_dir)
    measured = _run_blender(blender, ['--mode', 'measure', '--inputs'] + meshes, '部件测量')
    by_path = {os.path.realpath(item['path']): item for item in measured['files']}

    plan_parts = []
    records = []
    warnings = []
    for part, path in zip(contract['parts'], meshes):
        box, box_warnings = target_box(contract['views'], part)
        warnings.extend('%s：%s' % (part['name'], item) for item in box_warnings)
        measurement = by_path.get(path)
        if not measurement:
            raise ValueError('Blender 未测量到部件 ' + part['id'])
        computed = plan_part(part, box, measurement)
        plan_parts.append({'id': part['id'], 'name': part['name'], 'mesh': path,
                           'scale': computed['scale'],
                           'translate': computed['translate'],
                           'rotationZ': part['rotationZ']})
        records.append({'id': part['id'], 'name': part['name'], 'mesh': part['mesh'],
                        'sourceBbox': {'min': measurement['min'], 'max': measurement['max']},
                        'targetBbox': box, 'scale': computed['scale'],
                        'translate': computed['translate'],
                        'rotationZ': part['rotationZ'],
                        'flags': computed['flags'], 'warnings': box_warnings})

    absolute_output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(absolute_output), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='forgeworks-assemble-') as temp_dir:
        plan_path = os.path.join(temp_dir, 'plan.json')
        with open(plan_path, 'w', encoding='utf-8') as stream:
            json.dump({'schemaVersion': SCHEMA_VERSION, 'parts': plan_parts},
                      stream, ensure_ascii=False)
        assembled = _run_blender(blender, ['--mode', 'assemble', '--plan', plan_path,
                                           '--output', absolute_output], '部件装配')

    world = {item['id']: item for item in assembled['parts']}
    for record in records:
        final = world.get(record['id'])
        record['worldBbox'] = ({'min': final['min'], 'max': final['max']} if final else None)
        if final and final.get('triangles') == 0:
            record['flags'].append('empty_mesh')

    report = {'valid': not any('empty_mesh' in record['flags'] for record in records),
              'assetId': contract['assetId'], 'output': absolute_output,
              'blender': blender, 'parts': records, 'warnings': warnings}
    target = report_path or os.path.splitext(absolute_output)[0] + '.report.json'
    with open(target, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    payload = {'schemaVersion': SCHEMA_VERSION, 'assetId': contract['assetId'],
               'parts': [{key: record[key] for key in
                          ('id', 'name', 'mesh', 'worldBbox', 'scale', 'translate',
                           'rotationZ', 'flags')} for record in records]}
    with open(parts_json_path or os.path.join(os.path.dirname(absolute_output), 'parts.json'),
              'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return report


def bootstrap(source_path, out_dir, parts=3, axis='z', blender_path=None, asset_id=None):
    blender = blender_path or find_blender()
    if not blender:
        raise ValueError('未找到 Blender：请用 --blender 指定，或配置 tools/bridge_config.json')
    if not os.path.isfile(source_path):
        raise ValueError('源 GLB 不存在')
    os.makedirs(out_dir, exist_ok=True)
    cut = _run_blender(blender, ['--mode', 'cut', '--input', os.path.abspath(source_path),
                                 '--out-dir', os.path.abspath(out_dir),
                                 '--parts', str(parts), '--axis', axis], '部件粗切')
    entries = [{'id': 'part_%d' % item['index'],
                'name': '部件 %d' % (item['index'] + 1),
                'mesh': os.path.basename(item['file']),
                'bbox': {'min': item['min'], 'max': item['max']}}
               for item in cut['files']]
    contract = contract_from_bboxes(asset_id or 'CUT_DEMO', entries)
    contract_path = os.path.join(out_dir, 'partspec.json')
    with open(contract_path, 'w', encoding='utf-8') as stream:
        json.dump(contract, stream, ensure_ascii=False, indent=2)
    return {'contract': contract_path, 'parts': entries}


def main():
    parser = argparse.ArgumentParser(description='Forgeworks 分件契约与装配')
    sub = parser.add_subparsers(dest='command', required=True)

    assemble_cmd = sub.add_parser('assemble', help='按契约装配部件')
    assemble_cmd.add_argument('--contract', required=True)
    assemble_cmd.add_argument('--out', required=True)
    assemble_cmd.add_argument('--report')
    assemble_cmd.add_argument('--parts-json')
    assemble_cmd.add_argument('--blender')

    bootstrap_cmd = sub.add_parser('bootstrap', help='粗切一个 GLB 并生成契约')
    bootstrap_cmd.add_argument('--source', required=True)
    bootstrap_cmd.add_argument('--out-dir', required=True)
    bootstrap_cmd.add_argument('--parts', type=int, default=3)
    bootstrap_cmd.add_argument('--axis', choices=('x', 'y', 'z'), default='z')
    bootstrap_cmd.add_argument('--asset-id')
    bootstrap_cmd.add_argument('--blender')

    validate_cmd = sub.add_parser('validate', help='校验并输出规范化契约')
    validate_cmd.add_argument('--contract', required=True)

    args = parser.parse_args()
    try:
        if args.command == 'assemble':
            result = assemble(args.contract, args.out, args.blender, args.report, args.parts_json)
            print(json.dumps({'valid': result['valid'], 'output': result['output'],
                              'parts': len(result['parts']), 'warnings': result['warnings']},
                             ensure_ascii=False))
            return 0 if result['valid'] else 1
        if args.command == 'bootstrap':
            result = bootstrap(args.source, args.out_dir, args.parts, args.axis,
                               args.blender, args.asset_id)
            print(json.dumps({'contract': result['contract'], 'parts': len(result['parts'])},
                             ensure_ascii=False))
            return 0
        print(json.dumps(load_contract(args.contract), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
