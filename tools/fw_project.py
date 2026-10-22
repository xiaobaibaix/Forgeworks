#!/usr/bin/env python3
"""Forgeworks 项目工程：独立资源库 + UE 导出目标。"""

import hashlib
import json
import os
import re
import shutil
import time
import uuid

PROJECT_MARKER = 'forgeworks.project.json'
PROJECT_CONTENT = 'project.json'
SOURCE_DIR = '_Source'
SYNC_DIR = '_Sync'
UE_DIR_NAME = 'Forgeworks'
ASSET_KIND_DIRS = {'machine': 'Machines', 'item': 'Items/Icons', 'data': 'Data'}
UE_EXPORT_ROLES = {'machine': ('mesh',), 'item': ('icon',)}
MAX_CONTENT_BYTES = 16 * 1024 * 1024
MAX_NAME_LENGTH = 64


def _now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


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
    for relative in [SOURCE_DIR, SYNC_DIR] + [
            os.path.join(SOURCE_DIR, *kind.split('/')) for kind in ASSET_KIND_DIRS.values()]:
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
