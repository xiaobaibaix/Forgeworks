#!/usr/bin/env python3
"""Forgeworks 项目工程：独立资源库 + UE 导出目标。"""

import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
import uuid

PROJECT_MARKER = 'forgeworks.project.json'
PROJECT_CONTENT = 'project.json'
SOURCE_DIR = '_Source'
SYNC_DIR = '_Sync'
UE_DIR_NAME = 'Forgeworks'
ASSET_KIND_DIRS = {'machine': '机器', 'item': '物品/图标', 'element': '元素', 'data': '数据'}
TEXTURE_DIR = '材质'
LAYOUT_VERSION = 2
UE_EXPORT_ROLES = {'machine': ('mesh', 'icon'), 'item': ('icon',), 'element': ('icon',)}
MAX_CONTENT_BYTES = 16 * 1024 * 1024
MAX_NAME_LENGTH = 64
MAX_FOLDER_LENGTH = 64
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f#%&\'{}~]')
_WINDOWS_RESERVED = {
    'con', 'prn', 'aux', 'nul',
    *('com%d' % index for index in range(1, 10)),
    *('lpt%d' % index for index in range(1, 10)),
}


def _now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


def _folder_identity(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


def sanitize_asset_folder(name, asset_id):
    """把资产显示名转成安全的目录名；空名或非法名回退到资产 ID。"""
    normalized = unicodedata.normalize('NFC', str(name or '')).strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    normalized = _INVALID_FOLDER_CHARS.sub('-', normalized)
    normalized = normalized.strip(' .')
    if _folder_identity(normalized) in _WINDOWS_RESERVED:
        normalized = ''
    normalized = normalized[:MAX_FOLDER_LENGTH].strip(' .')
    return normalized or str(asset_id or '').strip()


def _folder_candidates(name, asset_id):
    asset_id = str(asset_id or '').strip()
    base = sanitize_asset_folder(name, asset_id)
    candidates = [base]
    if base != asset_id:
        candidates.append('%s-%s' % (base, asset_id))
    candidates.append(asset_id)
    for index in range(2, 100):
        candidates.append('%s-%d' % (asset_id, index))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def asset_folder(asset_id, meta, claimed=None):
    claimed = set(claimed or ())
    for candidate in _folder_candidates((meta or {}).get('name'), asset_id):
        if _folder_identity(candidate) not in claimed:
            return candidate
    return str(asset_id)


def move_asset_dir(root, old_rel, new_rel):
    if old_rel == new_rel:
        return new_rel
    old_abs = _safe_join(root, old_rel)
    new_abs = _safe_join(root, new_rel)
    if not os.path.isdir(old_abs):
        return new_rel
    if os.path.exists(new_abs):
        try:
            same = os.path.samefile(old_abs, new_abs)
        except OSError:
            same = False
        if not same:
            raise ValueError('目标资产目录已存在: %s' % new_rel)
        temp_abs = old_abs + '.fw-rename'
        os.rename(old_abs, temp_abs)
        os.rename(temp_abs, new_abs)
        return new_rel
    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
    os.rename(old_abs, new_abs)
    return new_rel


def asset_source_dir(root, kind, asset_id, meta, manifest):
    """计算资产的中文目录，并把旧目录/ID 草稿目录整体迁过去。"""
    kind_dir = ASSET_KIND_DIRS.get(kind)
    if not kind_dir:
        raise ValueError('不支持的资产类型: %s' % kind)
    assets = (manifest or {}).get('assets') or {}
    record = assets.get(asset_id) or {}
    old_rel = record.get('sourceDir')
    claimed = set()
    for other_id, other in assets.items():
        if other_id == asset_id or not isinstance(other, dict) or other.get('kind') != kind:
            continue
        other_rel = other.get('sourceDir')
        if other_rel:
            claimed.add(_folder_identity(other_rel.split('/')[-1]))
        other_name = (other.get('meta') or {}).get('name')
        if other_name:
            claimed.add(_folder_identity(sanitize_asset_folder(other_name, other_id)))
    chosen = None
    for candidate in _folder_candidates((meta or {}).get('name'), asset_id):
        candidate_rel = '/'.join((SOURCE_DIR, kind_dir, candidate))
        if _folder_identity(candidate) in claimed:
            continue
        if candidate_rel == old_rel or not os.path.isdir(_safe_join(root, candidate_rel)):
            chosen = candidate_rel
            break
    if not chosen:
        chosen = '/'.join((SOURCE_DIR, kind_dir, asset_id))
    draft_rel = '/'.join((SOURCE_DIR, kind_dir, asset_id))
    if old_rel and old_rel != chosen:
        return move_asset_dir(root, old_rel, chosen)
    if not old_rel and draft_rel != chosen and os.path.isdir(_safe_join(root, draft_rel)):
        return move_asset_dir(root, draft_rel, chosen)
    return chosen


def asset_dir_from_record(root, asset_id, record):
    relative = (record or {}).get('sourceDir')
    if relative:
        return _safe_join(root, _safe_relative(relative))
    kind_dir = ASSET_KIND_DIRS.get((record or {}).get('kind'))
    if not kind_dir or not asset_id:
        return None
    return _safe_join(root, SOURCE_DIR, *kind_dir.split('/'), str(asset_id))


def content_path_for(record):
    try:
        relative = _safe_relative((record or {}).get('sourceDir'))
    except ValueError:
        return None
    parts = relative.split('/')
    if parts and parts[0] == SOURCE_DIR:
        parts = parts[1:]
    return '/Game/Forgeworks/' + '/'.join(parts) if parts else None


def validate_project_name(name):
    name = str(name or '').strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValueError('项目名称不能为空，且不超过 %d 个字符' % MAX_NAME_LENGTH)
    if name in ('.', '..') or any(char in name for char in ('/', '\\', '\0')):
        raise ValueError('项目名称不能包含路径分隔符')
    if name.startswith('.'):
        raise ValueError('项目名称不能以点开头')
    return name


def marker_path(root):
    return os.path.join(root, PROJECT_MARKER)


def manifest_path(root):
    return os.path.join(root, SYNC_DIR, 'manifest.json')


def content_path(root):
    return os.path.join(root, PROJECT_CONTENT)


def is_project(root):
    return bool(root) and os.path.isfile(marker_path(root))


def read_marker(root):
    try:
        with open(marker_path(root), encoding='utf-8') as stream:
            marker = json.load(stream)
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) else None


def detect_project(path):
    """识别 Forgeworks 项目；旧版 <UE>/Forgeworks 布局同时给出 UE 目标。"""
    path = os.path.abspath(os.path.expanduser(str(path or '')))
    if is_project(path):
        return {'root': path, 'kind': 'project', 'ueRoot': None}
    legacy = os.path.join(path, UE_DIR_NAME)
    if is_project(legacy) or os.path.isfile(manifest_path(legacy)):
        return {'root': legacy, 'kind': 'legacy', 'ueRoot': path}
    return None


def project_label(root):
    marker = read_marker(root) or {}
    return str(marker.get('name') or os.path.basename(os.path.abspath(root)))


def project_info(root):
    if not is_project(root):
        return None
    marker = read_marker(root) or {}
    return {
        'root': os.path.abspath(root),
        'name': str(marker.get('name') or os.path.basename(os.path.abspath(root))),
        'kind': 'forgeworks',
        'projectId': marker.get('projectId'),
        'createdAt': marker.get('createdAt'),
        'updatedAt': marker.get('updatedAt'),
    }


def _ensure_store(root):
    for relative in ([SOURCE_DIR, SYNC_DIR]
                     + [os.path.join(SOURCE_DIR, *kind.split('/')) for kind in ASSET_KIND_DIRS.values()]
                     + [os.path.join(SOURCE_DIR, TEXTURE_DIR)]):
        os.makedirs(os.path.join(root, relative), exist_ok=True)


def initialize_project(root, name=None, bridge_version='0.1.0'):
    """在已有目录补上项目标记与目录树，不覆盖已有资产。"""
    root = os.path.abspath(os.path.expanduser(str(root)))
    os.makedirs(root, exist_ok=True)
    _ensure_store(root)
    marker = read_marker(root) or {
        'schemaVersion': 1,
        'projectId': uuid.uuid4().hex,
        'name': validate_project_name(name or os.path.basename(root)),
        'createdAt': _now_iso(),
        'updatedAt': _now_iso(),
    }
    _write_json(marker_path(root), marker)
    if not os.path.isfile(manifest_path(root)):
        _write_json(manifest_path(root), {
            'schemaVersion': 1,
            'layoutVersion': LAYOUT_VERSION,
            'forgeworksVersion': 'bridge-%s' % bridge_version,
            'project': {'name': marker['name'], 'kind': 'forgeworks', 'root': root},
            'assets': {},
        })
    return {'root': root, 'project': project_info(root)}


def create_project(parent, name, bridge_version='0.1.0'):
    parent = os.path.abspath(os.path.expanduser(str(parent or '')))
    if not os.path.isdir(parent):
        raise ValueError('父目录不存在: %s' % parent)
    name = validate_project_name(name)
    root = os.path.join(parent, name)
    if os.path.exists(root):
        if not os.path.isdir(root) or os.listdir(root):
            raise ValueError('目标目录已存在且不为空: %s' % root)
    os.makedirs(root, exist_ok=True)
    return initialize_project(root, name, bridge_version)


def load_content(root):
    try:
        with open(content_path(root), encoding='utf-8') as stream:
            content = json.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None
    return content if isinstance(content, dict) else None


def content_revision(root):
    """project.json 字节指纹，供界面与 MCP 做乐观锁；文件不存在时返回空串。"""
    try:
        with open(content_path(root), 'rb') as stream:
            return hashlib.sha256(stream.read()).hexdigest()
    except OSError:
        return ''


def save_content(root, content):
    if not is_project(root):
        raise ValueError('未打开 Forgeworks 项目')
    if not isinstance(content, dict):
        raise ValueError('项目内容必须是对象')
    try:
        payload = json.dumps(content, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as error:
        raise ValueError('项目内容无法序列化: %s' % error)
    if len(payload.encode('utf-8')) > MAX_CONTENT_BYTES:
        raise ValueError('项目内容超过 16 MB 限制')
    _write_text(content_path(root), payload)
    marker = read_marker(root) or {}
    marker['updatedAt'] = _now_iso()
    _write_json(marker_path(root), marker)
    return content


def _write_json(path, obj):
    _write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as stream:
        stream.write(text)
    os.replace(tmp, path)


def _safe_relative(value):
    normalized = str(value or '').replace('\\', '/')
    if (not normalized or normalized.startswith('/')
            or any(part in ('', '.', '..') for part in normalized.split('/'))):
        raise ValueError('非法相对路径: %r' % value)
    return normalized


def _safe_join(root, *parts):
    root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, *parts))
    if target != root and os.path.commonpath((root, target)) != root:
        raise ValueError('路径超出项目目录')
    return target


def _load_manifest(root):
    try:
        with open(manifest_path(root), encoding='utf-8') as stream:
            manifest = json.load(stream)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _load_json_file(path):
    try:
        with open(path, encoding='utf-8') as stream:
            value = json.load(stream)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _remove_empty_dirs(path):
    if os.path.islink(path) or not os.path.isdir(path):
        return
    for name in os.listdir(path):
        child = os.path.join(path, name)
        if name == '.DS_Store' and os.path.isfile(child):
            try:
                os.remove(child)
            except OSError:
                pass
            continue
        _remove_empty_dirs(child)
    try:
        os.rmdir(path)
    except OSError:
        pass


LEGACY_SOURCE_DIRS = ('Machines', 'Items/Icons', 'Items', 'Data')


def _prune_legacy_dirs(root):
    for legacy in LEGACY_SOURCE_DIRS:
        _remove_empty_dirs(os.path.join(root, SOURCE_DIR, *legacy.split('/')))


def _migrate_materials(root):
    old = os.path.join(root, SOURCE_DIR, 'Materials')
    new = os.path.join(root, SOURCE_DIR, TEXTURE_DIR)
    if not os.path.isdir(old):
        return []
    os.makedirs(new, exist_ok=True)
    moved = []
    for name in os.listdir(old):
        source = os.path.join(old, name)
        target = os.path.join(new, name)
        if os.path.exists(target):
            continue
        shutil.move(source, target)
        moved.append(name)
    try:
        os.rmdir(old)
    except OSError:
        pass
    return moved


def migrate_layout(root):
    """把旧英文/ID 目录迁移为中文目录；幂等，可中断后重跑。"""
    root = os.path.abspath(str(root or ''))
    manifest = _load_manifest(root)
    if not manifest:
        return {'ok': False, 'error': '项目 manifest 不存在'}
    _prune_legacy_dirs(root)
    if int(manifest.get('layoutVersion') or 0) >= LAYOUT_VERSION:
        return {'ok': True, 'moved': [], 'version': LAYOUT_VERSION}
    assets = manifest.setdefault('assets', {})
    moved = []
    for asset_id in sorted(assets):
        record = assets[asset_id]
        if not isinstance(record, dict) or record.get('kind') not in ASSET_KIND_DIRS:
            continue
        old_rel = record.get('sourceDir')
        try:
            new_rel = asset_source_dir(root, record['kind'], asset_id, record.get('meta') or {}, manifest)
        except (OSError, ValueError) as error:
            return {'ok': False, 'error': '迁移失败（%s）: %s' % (asset_id, error),
                    'moved': moved, 'version': manifest.get('layoutVersion')}
        if old_rel != new_rel:
            record['sourceDir'] = new_rel
            moved.append({'id': asset_id, 'from': old_rel, 'to': new_rel})
            _write_json(manifest_path(root), manifest)
    materials = _migrate_materials(root)
    _prune_legacy_dirs(root)
    manifest['layoutVersion'] = LAYOUT_VERSION
    _write_json(manifest_path(root), manifest)
    return {'ok': True, 'moved': moved, 'materials': materials, 'version': LAYOUT_VERSION}


def migrate_ue_export(fw_root, ue_root):
    """把 UE 导出目录里的旧分类/ID 目录跟随项目 sourceDir 迁移。"""
    fw_root = os.path.abspath(str(fw_root or ''))
    if not ue_root:
        return {'ok': False, 'error': '未设置 UE 导出目标'}
    fw_manifest = _load_manifest(fw_root) or {}
    fw_assets = fw_manifest.get('assets') or {}
    export_root = os.path.join(os.path.abspath(ue_root), UE_DIR_NAME)
    ue_manifest_file = os.path.join(export_root, SYNC_DIR, 'manifest.json')
    ue_manifest = _load_json_file(ue_manifest_file)
    if not ue_manifest:
        return {'ok': True, 'moved': [], 'skipped': []}
    moved, skipped = [], []
    for asset_id, record in (ue_manifest.get('assets') or {}).items():
        if not isinstance(record, dict):
            continue
        target_rel = ((fw_assets.get(asset_id) or {}).get('sourceDir'))
        old_rel = record.get('sourceDir')
        if not target_rel or not old_rel or old_rel == target_rel:
            continue
        old_abs = _safe_join(export_root, _safe_relative(old_rel))
        new_abs = _safe_join(export_root, _safe_relative(target_rel))
        if os.path.isdir(old_abs) and not os.path.exists(new_abs):
            os.makedirs(os.path.dirname(new_abs), exist_ok=True)
            os.rename(old_abs, new_abs)
            record['sourceDir'] = target_rel
            moved.append({'id': asset_id, 'from': old_rel, 'to': target_rel})
        elif os.path.isdir(old_abs):
            skipped.append({'id': asset_id, 'reason': '目标目录已存在'})
    for legacy in (*LEGACY_SOURCE_DIRS, 'Materials'):
        _remove_empty_dirs(os.path.join(export_root, SOURCE_DIR, *legacy.split('/')))
    if moved:
        _write_json(ue_manifest_file, ue_manifest)
    return {'ok': True, 'moved': moved, 'skipped': skipped}


def _uproject_name(root):
    try:
        for name in sorted(os.listdir(root)):
            if name.endswith('.uproject') and os.path.isfile(os.path.join(root, name)):
                return name
    except OSError:
        pass
    return None


def ue_target_info(ue_root):
    uproject = _uproject_name(ue_root)
    return {
        'root': os.path.abspath(ue_root),
        'name': uproject[:-len('.uproject')] if uproject else os.path.basename(os.path.abspath(ue_root)),
        'uproject': uproject,
        'kind': 'ue' if uproject else 'workspace',
        'forgeworksRoot': os.path.join(os.path.abspath(ue_root), UE_DIR_NAME),
    }


def prepare_ue_target(ue_root):
    ue_root = os.path.abspath(os.path.expanduser(str(ue_root or '')))
    if not os.path.isdir(ue_root):
        raise ValueError('UE 导出目标目录不存在: %s' % ue_root)
    export_root = os.path.join(ue_root, UE_DIR_NAME)
    _ensure_store(export_root)
    return ue_target_info(ue_root)


def publish_to_ue(fw_root, ue_root, asset_ids=None, bridge_version='0.1.0'):
    """只把 UE 消费的文件（机器 GLB、物品图标 PNG）与 manifest 复制到导出目标。"""
    fw_root = os.path.abspath(str(fw_root or ''))
    if not is_project(fw_root):
        return {'ok': False, 'error': '未打开 Forgeworks 项目'}
    try:
        target = prepare_ue_target(ue_root)
    except ValueError as error:
        return {'ok': False, 'error': str(error)}
    migrate_ue_export(fw_root, ue_root)
    manifest = _load_manifest(fw_root)
    if not manifest:
        return {'ok': False, 'error': '项目 manifest 不存在，请先生成资产'}
    assets = manifest.get('assets') or {}
    if asset_ids is None:
        selected = [asset_id for asset_id, record in assets.items()
                    if record.get('kind') in UE_EXPORT_ROLES]
    else:
        selected = list(dict.fromkeys(str(asset_id) for asset_id in asset_ids))
    export_source = os.path.join(target['forgeworksRoot'], SOURCE_DIR)
    published, skipped, errors, exported_assets = [], [], [], {}
    for asset_id in selected:
        record = assets.get(asset_id)
        if not record or record.get('kind') not in UE_EXPORT_ROLES:
            skipped.append(asset_id)
            continue
        try:
            exported_assets[asset_id] = _publish_asset(
                fw_root, export_source, asset_id, record, bridge_version)
            published.append(asset_id)
        except (OSError, ValueError) as error:
            errors.append({'id': asset_id, 'error': str(error)})
    if published:
        ue_manifest_path = os.path.join(target['forgeworksRoot'], SYNC_DIR, 'manifest.json')
        try:
            with open(ue_manifest_path, encoding='utf-8') as stream:
                previous_exported = json.load(stream)
        except (OSError, ValueError):
            previous_exported = None
        merged_assets = {}
        if isinstance(previous_exported, dict) and isinstance(previous_exported.get('assets'), dict):
            merged_assets.update(previous_exported['assets'])
        merged_assets.update(exported_assets)
        exported_manifest = {
            'schemaVersion': 1,
            'forgeworksVersion': 'bridge-%s' % bridge_version,
            'project': {
                'name': target['name'],
                'kind': target['kind'],
                'uproject': target['uproject'],
                'root': target['root'],
                'forgeworksRoot': target['forgeworksRoot'],
            },
            'publishedAt': _now_iso(),
            'assets': merged_assets,
        }
        _write_json(ue_manifest_path, exported_manifest)
    return {
        'ok': bool(published) and not errors,
        'target': target,
        'published': published,
        'skipped': skipped,
        'errors': errors,
    }


def _publish_asset(fw_root, export_source, asset_id, record, bridge_version):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', str(asset_id)):
        raise ValueError('资产 ID 非法')
    kind = record.get('kind')
    roles = UE_EXPORT_ROLES.get(kind)
    if not roles:
        raise ValueError('不支持导出到 UE 的资产类型: %s' % kind)
    source_dir = _safe_relative(record.get('sourceDir'))
    files = record.get('files') or {}
    copied = {}
    for role in roles:
        entries = files.get(role) or []
        entries = entries if isinstance(entries, list) else [entries]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            relative = _safe_relative(entry.get('path'))
            source = _safe_join(fw_root, source_dir, relative)
            if not os.path.isfile(source):
                raise ValueError('源文件缺失: %s' % relative)
            destination = _safe_join(export_source, *os.path.join(source_dir, relative).split('/')[1:])
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            with open(destination, 'rb') as stream:
                data = stream.read()
            copied.setdefault(role, []).append({
                'path': relative,
                'size': len(data),
                'sha1': _sha1(data),
                'mtime': _now_iso(),
            })
    required = roles[0]
    if not copied.get(required):
        raise ValueError('manifest 中没有 %s 文件记录' % required)
    return {
        'kind': kind,
        'state': 'exported',
        'sourceDir': source_dir,
        'files': copied,
        'exportedAt': _now_iso(),
        'exportedBy': 'bridge-%s' % bridge_version,
        'meta': record.get('meta') or {},
    }
