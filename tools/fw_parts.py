#!/usr/bin/env python3
"""部件布局与本地装配：Blender 按布局移动、缩放、旋转各部件并合并成整机。"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

LAYOUT_SCHEMA_VERSION = 1
BLENDER_TIMEOUT = 600
DEFAULT_GAP = 0.02


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
    return {
        'schemaVersion': LAYOUT_SCHEMA_VERSION,
        'assetId': str(data.get('assetId') or ''),
        'nodeId': str(data.get('nodeId') or ''),
        'assemblyPrompt': str(data.get('assemblyPrompt') or ''),
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
            'description': str(entry.get('description') or ''),
            'sourceBbox': {'min': [round(value, 6) for value in low],
                           'max': [round(value, 6) for value in high]},
            'scale': 1.0,
            'translate': translate,
            'rotationZ': 0.0,
            'ground': True,
        })
    return laid_out


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
                   preserve_absent=False):
    """按布局合并部件；布局缺失或 reset 时自动生成，已有布局里的变换优先于自动布局；preserve_absent 时保留未接入部件的旧布局。"""
    if not parts:
        raise ValueError('没有可组装的部件模型')
    blender = blender_path or find_blender()
    if not blender:
        raise ValueError('未找到 Blender：请用 --blender 指定，或配置 tools/bridge_config.json')
    root = os.path.realpath(root)

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
            'absolute': resolve_layout_mesh(root, mesh),
        })

    measured = measure_parts(blender, [entry['absolute'] for entry in entries])
    for entry in entries:
        measurement = measured[entry['absolute']]
        entry['sourceBbox'] = {'min': [round(value, 6) for value in measurement['min']],
                               'max': [round(value, 6) for value in measurement['max']]}
        entry['sourceTriangles'] = measurement['triangles']

    warnings = []
    existing = None if reset else load_layout(layout_path)
    existing_by_mesh, preserved = {}, []
    if existing:
        existing_by_mesh = {entry['mesh']: entry for entry in existing['parts']}
        dropped = [mesh for mesh in existing_by_mesh if mesh not in seen]
        if dropped and preserve_absent:
            preserved = [existing_by_mesh[mesh] for mesh in dropped]
        elif dropped:
            warnings.append('布局里有 %d 个部件已不再接入，已丢弃：%s'
                            % (len(dropped), '、'.join(os.path.basename(mesh) for mesh in dropped)))
        added = [entry['mesh'] for entry in entries if entry['mesh'] not in existing_by_mesh]
        if added:
            warnings.append('%d 个新部件已自动补位，可在布局文件里调整' % len(added))
    else:
        warnings.append('已自动生成布局：沿 X 轴并排贴地，可在布局文件里调整后重跑')
    auto_by_mesh = {entry['mesh']: entry for entry in auto_layout(entries)}

    layout_parts, plan_parts, records = [], [], []
    for entry in entries:
        existing_entry = existing_by_mesh.get(entry['mesh'])
        base = existing_entry or auto_by_mesh[entry['mesh']]
        layout_entry = {
            'id': entry['id'],
            'name': (existing_entry or {}).get('name') or entry['name'] or base['name'],
            'mesh': entry['mesh'],
            'description': entry['description'] or base['description'],
            'sourceBbox': entry['sourceBbox'],
            'scale': float(base['scale']),
            'translate': [float(value) for value in base['translate']],
            'rotationZ': float(base['rotationZ']),
            'ground': bool(base['ground']),
        }
        plan_part, effective = _plan_part(layout_entry, entry['absolute'])
        plan_parts.append(plan_part)
        # 写回实际落地的 translate，AI 关掉 ground 时仍保留贴地位置
        layout_entry['translate'] = effective
        layout_parts.append(layout_entry)
        records.append({'id': entry['id'], 'name': entry['name'], 'mesh': entry['mesh'],
                        'sourceTriangles': entry['sourceTriangles']})
    if preserved:
        warnings.append('%d 个未就绪部件的旧布局已保留，重跑时可继续使用' % len(preserved))
        layout_parts.extend(preserved)

    absolute_output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(absolute_output), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='forgeworks-assemble-') as temp_dir:
        plan_path = os.path.join(temp_dir, 'plan.json')
        with open(plan_path, 'w', encoding='utf-8') as stream:
            json.dump({'schemaVersion': LAYOUT_SCHEMA_VERSION, 'parts': plan_parts},
                      stream, ensure_ascii=False)
        assembled = _run_blender(blender, ['--mode', 'assemble', '--plan', plan_path,
                                           '--output', absolute_output], '部件装配')

    world = {str(item.get('id')): item for item in assembled.get('parts') or []}
    for record in records:
        final = world.get(record['id'])
        record['worldBbox'] = ({'min': final['min'], 'max': final['max']} if final else None)
        record['triangles'] = int(final.get('triangles') or 0) if final else 0
        if final is not None and record['triangles'] == 0:
            warnings.append('部件 %s 装配后没有面' % record['name'])

    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    layout = {'schemaVersion': LAYOUT_SCHEMA_VERSION, 'assetId': asset_id,
              'nodeId': node_id or '', 'assemblyPrompt': assembly_prompt,
              'updatedAt': stamp, 'parts': layout_parts}
    save_layout(layout_path, layout)

    report = {'valid': True, 'assetId': asset_id, 'nodeId': node_id or '',
              'output': absolute_output, 'layout': os.path.abspath(layout_path),
              'blender': blender, 'assemblyPrompt': assembly_prompt,
              'parts': records, 'warnings': warnings}
    with open(os.path.splitext(absolute_output)[0] + '.report.json', 'w', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)

    return {
        'meshPath': os.path.basename(absolute_output),
        'outputPath': absolute_output,
        'layoutPath': os.path.abspath(layout_path),
        'parts': [{'id': record['id'], 'name': record['name'],
                   'triangles': record['triangles']} for record in records],
        'triangles': sum(record['triangles'] for record in records),
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
            asset_id=layout['assetId'], node_id=layout['nodeId'])
        print(json.dumps({'output': result['outputPath'], 'parts': len(result['parts']),
                          'triangles': result['triangles'], 'warnings': result['warnings']},
                         ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
