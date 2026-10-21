#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forgeworks Bridge · 本地桥接服务
================================================================

serve.py 只做静态文件；bridge.py 在它之上加了「与文件系统、
外部工具（Blender）、未来的大模型 API 打交道」的能力。
设计文档见 docs/sync-design.md（§2.4 架构图）。

为什么需要 Bridge（而不是浏览器直连文件系统）：
    1. 浏览器不能 spawn 子进程 → 调不了 Blender / UE
    2. API 密钥必须留在服务端（gitignore 的配置文件）
    3. 目录监听、批量校验、二进制落盘都在服务端做更可靠

职责（本期实现）：
    - 静态文件服务（no-store，继承 serve.py 的教训）
    - 项目目录绑定（验证 .uproject，创建 Forgeworks/ 目录树）
    - manifest.json 读写（同步真相来源）
    - 资产导出落盘（GLB/图标/元数据 → _Source/<类型>/<ID>/）
    - _Source 扫描与状态核对（检测外部删除/修改）
    - Blender 路径探测（移动硬盘等多候选）
    - SSE 事件推送（文件变化 → 前端刷新标记）

用法：
    python3 tools/bridge.py          # 8787 端口
    python3 tools/bridge.py 9000     # 指定端口

状态存储约定（见 sync-design §3.1 / §4.2）：
    项目内:  <项目根>/Forgeworks/{_Source,_Sync}/...
    本地态:  tools/.bridge_state.json（gitignore，存最近绑定的项目路径）
    密钥 :   tools/bridge_config.json（gitignore，本期只用 blender 段）
"""

import base64
import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
_pipeline_spec = importlib.util.spec_from_file_location('fw_pipeline', os.path.join(ROOT, 'tools', 'fw_pipeline.py'))
fw_pipeline = importlib.util.module_from_spec(_pipeline_spec)
_pipeline_spec.loader.exec_module(fw_pipeline)
_provider_spec = importlib.util.spec_from_file_location('fw_providers', os.path.join(ROOT, 'tools', 'fw_providers.py'))
fw_providers = importlib.util.module_from_spec(_provider_spec)
_provider_spec.loader.exec_module(fw_providers)

BRIDGE_VERSION = '0.1.0'
STATE_FILE = os.path.join(ROOT, 'tools', '.bridge_state.json')
CONFIG_FILE = os.path.join(ROOT, 'tools', 'bridge_config.json')

# 目录结构约定（sync-design §3.1）
FW_DIR_NAME = 'Forgeworks'                 # 项目根下
SOURCE_DIR = '_Source'
SYNC_DIR = '_Sync'
SOURCE_TREE = {
    'Machines': None,
    'Items/Icons': None,
    'Data': None,
}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def now_iso():
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def sha1_bytes(data):
    return hashlib.sha1(data).hexdigest()


def sha1_str(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Bridge 状态（最近绑定的项目）
# ---------------------------------------------------------------------------

_state = read_json(STATE_FILE, {}) or {}
_events_lock = threading.Lock()
_events = []          # 最近 50 条事件，SSE 断线重连时补发用
_sse_clients = []     # 活跃的 SSE 连接（wfile 列表）


def save_state():
    write_json(STATE_FILE, _state)


def push_event(kind, data=None):
    """推一条事件给所有 SSE 客户端。"""
    ev = {'kind': kind, 'data': data, 'at': now_iso()}
    with _events_lock:
        _events.append(ev)
        del _events[:-50]
    dead = []
    for w in _sse_clients:
        try:
            w.write(('data: ' + json.dumps(ev, ensure_ascii=False) + '\n\n').encode('utf-8'))
            w.flush()
        except Exception:
            dead.append(w)
    for w in dead:
        try:
            _sse_clients.remove(w)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Blender 探测（sync-design §2.5：移动硬盘路径候选 + 缓存）
# ---------------------------------------------------------------------------

BLENDER_CANDIDATES = [
    '/Volumes/KingstonXS1000Media/app/Blender.app/Contents/MacOS/Blender',
    '/Applications/Blender.app/Contents/MacOS/Blender',
    '/usr/local/bin/blender',
    '/opt/homebrew/bin/blender',
]

_blender_cache = {'found': None, 'checked': 0}
_blender_queue = queue.Queue()
_blender_worker_lock = threading.Lock()
_blender_worker_started = False
_manifest_lock = threading.RLock()
_watch_lock = threading.Lock()
_watch_thread = None


def find_blender(force=False):
    """探测 Blender 可执行文件。结果缓存 10 分钟；未找到返回 None。"""
    if not force and _blender_cache['found'] is not None and time.time() - _blender_cache['checked'] < 600:
        return _blender_cache['found']
    candidates = list(BLENDER_CANDIDATES)
    cfg = read_json(CONFIG_FILE) or {}
    custom = ((cfg.get('blender') or {}).get('path'))
    if custom:
        candidates.insert(0, custom)
    # 通配：任何挂载卷里的 app/Blender.app（移动硬盘盘符会变）
    try:
        import glob
        candidates += glob.glob('/Volumes/*/app/Blender.app/Contents/MacOS/Blender')
    except Exception:
        pass

    found = None
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            found = c
            break
    _blender_cache['found'] = found
    _blender_cache['checked'] = time.time()
    return found


def blender_info():
    path = find_blender()
    if not path:
        return {'found': False, 'path': None, 'version': None,
                'hint': '未找到 Blender（可配 tools/bridge_config.json 的 blender.path）'}
    ver = _blender_cache.get('version')
    if not ver:
        try:
            out = subprocess.run([path, '--version'], capture_output=True, timeout=15)
            m = re.search(rb'Blender\s+([\d.]+)', out.stdout or out.stderr or b'')
            ver = m.group(1).decode() if m else 'unknown'
            _blender_cache['version'] = ver
        except Exception:
            ver = 'unknown'
    return {'found': True, 'path': path, 'version': ver}


# ---------------------------------------------------------------------------
# 项目绑定与目录约定
# ---------------------------------------------------------------------------

def project_root():
    """当前绑定的项目根目录（未绑定返回 None）。"""
    p = _state.get('projectRoot')
    return p if p and os.path.isdir(p) else None


def fw_dir():
    p = project_root()
    return os.path.join(p, FW_DIR_NAME) if p else None


def source_dir():
    p = fw_dir()
    return os.path.join(p, SOURCE_DIR) if p else None


def sync_dir():
    p = fw_dir()
    return os.path.join(p, SYNC_DIR) if p else None


def manifest_path():
    p = sync_dir()
    return os.path.join(p, 'manifest.json') if p else None


def find_uproject(root):
    """在目录里找 .uproject（只看第一层）。"""
    try:
        for name in os.listdir(root):
            if name.endswith('.uproject'):
                return name
    except Exception:
        pass
    return None


RECENT_LIMIT = 8


def project_label(path, uproject):
    if uproject:
        return uproject[:-len('.uproject')]
    return os.path.basename(path.rstrip(os.sep)) or path


def current_project():
    """当前绑定项目的描述（未绑定返回 None）。"""
    root = project_root()
    if not root:
        return None
    uproject = find_uproject(root)
    return {
        'root': root,
        'name': project_label(root, uproject),
        'uproject': uproject,
        'kind': _state.get('projectKind') or ('ue' if uproject else 'workspace'),
    }


def remember_project(project):
    saved = dict(project, boundAt=now_iso())
    recent = [item for item in (_state.get('recentProjects') or []) if item.get('root') != project['root']]
    recent.insert(0, saved)
    _state['recentProjects'] = recent[:RECENT_LIMIT]


def recent_projects():
    rows = []
    for item in (_state.get('recentProjects') or []):
        root = item.get('root')
        if root:
            rows.append(dict(item, exists=os.path.isdir(root)))
    return rows


def bind_project(path):
    """绑定目录：有 .uproject 视为 UE 项目，否则当作普通工作区。"""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return {'ok': False, 'error': '目录不存在: %s' % path}
    uproject = find_uproject(path)
    kind = 'ue' if uproject else 'workspace'
    label = project_label(path, uproject)

    fw = os.path.join(path, FW_DIR_NAME)
    made = []
    for sub in [SOURCE_DIR, SYNC_DIR] + ['%s/%s' % (SOURCE_DIR, k) for k in SOURCE_TREE]:
        d = os.path.join(path, FW_DIR_NAME, sub)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            made.append(sub)

    mf_path = os.path.join(fw, SYNC_DIR, 'manifest.json')
    if not os.path.isfile(mf_path):
        write_json(mf_path, {
            'schemaVersion': 1,
            'forgeworksVersion': 'bridge-%s' % BRIDGE_VERSION,
            'project': {
                'name': label,
                'kind': kind,
                'uproject': uproject,
                'root': path,
                'boundAt': now_iso(),
            },
            'assets': {},
        })

    _state['projectRoot'] = path
    _state['projectKind'] = kind
    _state['boundAt'] = now_iso()
    project = {'name': label, 'kind': kind, 'uproject': uproject, 'root': path}
    remember_project(project)
    save_state()
    push_event('project.bound', {'root': path, 'uproject': uproject, 'kind': kind})
    return {'ok': True, 'project': project, 'fwDir': fw, 'created': made}


def unbind_project():
    _state.pop('projectRoot', None)
    _state.pop('projectKind', None)
    save_state()
    push_event('project.unbound', None)
    return {'ok': True}


PICK_PROMPT = '选择 Forgeworks 项目目录（含 .uproject 会识别为 UE 项目）'


def pick_folder():
    """弹系统原生的目录选择框。取消时返回 cancelled，而不是错误。"""
    try:
        if sys.platform == 'darwin':
            out = subprocess.run(
                ['osascript', '-e', 'POSIX path of (choose folder with prompt "%s")' % PICK_PROMPT],
                capture_output=True, text=True, timeout=300)
        elif os.name == 'nt':
            script = ("Add-Type -AssemblyName System.Windows.Forms; "
                      "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                      "$d.Description = '%s'; "
                      "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }" % PICK_PROMPT)
            out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                                 capture_output=True, text=True, timeout=300)
        else:
            out = subprocess.run(['zenity', '--file-selection', '--directory', '--title=' + PICK_PROMPT],
                                 capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return {'ok': False, 'error': '当前系统没有可用的目录选择器，请手动输入路径'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'cancelled': True, 'error': '选择超时'}
    if out.returncode != 0:
        return {'ok': False, 'cancelled': True}
    path = (out.stdout or '').strip()
    if not path:
        return {'ok': False, 'cancelled': True}
    return {'ok': True, 'path': path}


# ---------------------------------------------------------------------------
# manifest 与状态核对（sync-design §4.3 状态机）
# ---------------------------------------------------------------------------

def load_manifest():
    with _manifest_lock:
        return read_json(manifest_path(), None)


def save_manifest(mf):
    with _manifest_lock:
        write_json(manifest_path(), mf)


def normalize_ue_report(asset_id, ue, manifest):
    if not re.fullmatch(r'[A-Za-z0-9_]+', str(asset_id or '')):
        raise ValueError('资产 ID 不合法')
    record = (manifest or {}).get('assets', {}).get(asset_id)
    if not record or record.get('kind') != 'machine':
        raise ValueError('manifest 中不存在该机器')
    base_path = '/Game/Forgeworks/Machines/%s' % asset_id
    if not isinstance(ue, dict) or ue.get('contentPath') != base_path:
        raise ValueError('UE 内容目录与资产 ID 不匹配')
    assets = ue.get('assets') or {}
    mesh_path = assets.get('mesh')
    if not isinstance(mesh_path, str) or not re.fullmatch(
            r'/Game/Forgeworks/Machines/%s/[A-Za-z0-9_.]+\.[A-Za-z0-9_]+$' % re.escape(asset_id), mesh_path):
        raise ValueError('StaticMesh 对象路径非法')
    bounds = ue.get('bounds') or {}
    clean_bounds = {}
    for axis in ('x', 'y', 'z'):
        value = bounds.get(axis)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('UE bounds 必须是有限正数')
        clean_bounds[axis] = float(value)
    triangles = ue.get('triangles')
    if isinstance(triangles, bool) or not isinstance(triangles, int) or triangles < 0:
        raise ValueError('UE triangle 数无效')
    slots = ue.get('materialSlots')
    if not isinstance(slots, list) or len(slots) > 256 or any(not isinstance(slot, str) or len(slot) > 128 for slot in slots):
        raise ValueError('UE 材质槽列表无效')
    mesh_records = ((record.get('files') or {}).get('mesh') or [])
    mesh_record = mesh_records[0] if isinstance(mesh_records, list) and mesh_records else mesh_records
    expected_sha1 = mesh_record.get('sha1') if isinstance(mesh_record, dict) else None
    if expected_sha1 and ue.get('sourceSha1') != expected_sha1:
        raise ValueError('UE 回报对应的源 GLB 已过期')
    return {
        'contentPath': base_path,
        'importedAt': str(ue.get('importedAt') or now_iso())[:64],
        'importedBy': 'fw_sync.py',
        'assets': {'mesh': mesh_path},
        'bounds': clean_bounds,
        'triangles': triangles,
        'materialSlots': slots,
        'sourceSha1': ue.get('sourceSha1'),
    }


def report_ue_import(asset_id, ue):
    with _manifest_lock:
        manifest = load_manifest()
        if not manifest:
            return {'ok': False, 'error': '未绑定项目或 manifest 不存在'}
        try:
            normalized = normalize_ue_report(asset_id, ue, manifest)
        except (TypeError, ValueError) as error:
            return {'ok': False, 'error': str(error)}
        manifest['assets'][asset_id]['ue'] = normalized
        save_manifest(manifest)
    push_event('asset.ue_imported', {'id': asset_id, 'mesh': normalized['assets']['mesh']})
    return {'ok': True, 'id': asset_id, 'ue': normalized}


def normalize_ue_snapshot_path(forgeworks_root):
    path = os.path.join(forgeworks_root, SYNC_DIR, 'ue_assets.json')
    try:
        if os.path.getsize(path) > 10 * 1024 * 1024:
            return {'schemaVersion': 1, 'assets': []}
        snapshot = read_json(path, {}) or {}
    except OSError:
        snapshot = {}
    assets = []
    rows = snapshot.get('assets', []) if isinstance(snapshot, dict) else []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            match = re.fullmatch(r'/Game/Forgeworks/Machines/([A-Za-z0-9_]+)/([A-Za-z0-9_.]+)', row.get('objectPath', ''))
            bounds = row.get('bounds') or {}
            triangles = row.get('triangles')
            if not match or row.get('class') != 'StaticMesh' or isinstance(triangles, bool) or not isinstance(triangles, int) or triangles < 0:
                continue
            clean_bounds = {axis: float(bounds[axis]) for axis in ('x', 'y', 'z')}
            if any(not math.isfinite(value) or value < 0 for value in clean_bounds.values()):
                continue
            assets.append({'id': match.group(1), 'objectPath': match.group(0), 'class': 'StaticMesh',
                           'bounds': clean_bounds, 'triangles': triangles,
                           'materialSlots': [str(slot)[:128] for slot in row.get('materialSlots', [])[:256]],
                           'dependencies': [path for path in row.get('dependencies', [])[:512]
                                            if isinstance(path, str) and path.startswith('/Game/')][:512]})
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return {'schemaVersion': 1, 'generatedAt': snapshot.get('generatedAt'), 'assets': assets}


def _safe_sync_relative(value):
    normalized = str(value or '').replace('\\', '/')
    if not normalized or normalized.startswith('/') or any(part in ('', '.', '..') for part in normalized.split('/')):
        raise ValueError('非法同步路径')
    return normalized


def _safe_join(root, *parts):
    root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath((root, target)) != root:
        raise ValueError('路径超出 Forgeworks 目录')
    return target


def _tracked_files(record):
    for role, values in (record.get('files') or {}).items():
        for item in values if isinstance(values, list) else [values]:
            if isinstance(item, dict) and item.get('path'):
                yield role, item


def _tool_baseline_path(forgeworks_root, asset_id, relative_path):
    return _safe_join(forgeworks_root, SYNC_DIR, 'tool_versions', asset_id, _safe_sync_relative(relative_path))


def save_tool_baseline(forgeworks_root, asset_id, relative_path, data):
    target = _tool_baseline_path(forgeworks_root, asset_id, relative_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'wb') as stream:
        stream.write(data)


def archive_conflict(forgeworks_root, asset_id, relative_path):
    relative_path = _safe_sync_relative(relative_path)
    stamp = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + ('%03d' % int((time.time() % 1) * 1000))
    conflict_id = stamp + '_' + str(time.monotonic_ns() % 1000000)
    conflict_root = _safe_join(forgeworks_root, SYNC_DIR, 'conflicts', asset_id, conflict_id)
    disk_source = _safe_join(forgeworks_root, SOURCE_DIR, 'Machines', asset_id, relative_path)
    baseline = _tool_baseline_path(forgeworks_root, asset_id, relative_path)
    tool_copy = _safe_join(conflict_root, 'tool', relative_path)
    disk_copy = _safe_join(conflict_root, 'disk', relative_path)
    os.makedirs(os.path.dirname(disk_copy), exist_ok=True)
    if os.path.isfile(disk_source):
        shutil.copy2(disk_source, disk_copy)
    if os.path.isfile(baseline):
        os.makedirs(os.path.dirname(tool_copy), exist_ok=True)
        shutil.copy2(baseline, tool_copy)
    disk_hash = None
    if os.path.isfile(disk_source):
        with open(disk_source, 'rb') as stream:
            disk_hash = sha1_bytes(stream.read())
    return {
        'conflictId': conflict_id,
        'path': relative_path,
        'toolCopy': os.path.relpath(tool_copy, os.path.realpath(os.path.join(forgeworks_root, SYNC_DIR))).replace('\\', '/'),
        'diskCopy': os.path.relpath(disk_copy, os.path.realpath(os.path.join(forgeworks_root, SYNC_DIR))).replace('\\', '/'),
        'diskSha1': disk_hash,
        'toolAvailable': os.path.isfile(tool_copy),
        'diskAvailable': os.path.isfile(disk_copy),
        'createdAt': now_iso(),
        'status': 'pending',
    }


def watch_source_once(forgeworks_root=None, manifest=None):
    forgeworks_root = forgeworks_root or fw_dir()
    manifest = manifest if manifest is not None else load_manifest()
    if not forgeworks_root or not isinstance(manifest, dict):
        return []
    changes = []
    for asset_id, record in (manifest.get('assets') or {}).items():
        if record.get('kind') != 'machine' or not re.fullmatch(r'[A-Za-z0-9_]+', str(asset_id)):
            continue
        previous_state = record.get('state') or 'exported'
        has_missing = False
        pending_paths = {entry.get('path') for entry in record.get('conflicts', []) if entry.get('status') == 'pending'}
        for role, tracked in _tracked_files(record):
            relative_path = _safe_sync_relative(tracked['path'])
            source = _safe_join(forgeworks_root, SOURCE_DIR, 'Machines', asset_id, relative_path)
            if not os.path.isfile(source):
                has_missing = True
                if previous_state != 'missing':
                    changes.append({'id': asset_id, 'path': relative_path, 'state': 'missing'})
                continue
            with open(source, 'rb') as stream:
                disk_data = stream.read()
            disk_hash = sha1_bytes(disk_data)
            baseline = _tool_baseline_path(forgeworks_root, asset_id, relative_path)
            if not os.path.isfile(baseline) and tracked.get('sha1') == disk_hash:
                save_tool_baseline(forgeworks_root, asset_id, relative_path, disk_data)
            if tracked.get('sha1') and disk_hash != tracked['sha1'] and relative_path not in pending_paths:
                conflict = archive_conflict(forgeworks_root, asset_id, relative_path)
                conflict.update({'role': role, 'toolSha1': tracked.get('sha1')})
                record.setdefault('conflicts', []).append(conflict)
                changes.append({'id': asset_id, 'path': relative_path, 'state': 'conflict'})
        if any(item.get('status') == 'pending' for item in record.get('conflicts', [])):
            next_state = 'conflict'
        else:
            next_state = 'missing' if has_missing else 'exported'
        record['state'] = next_state
        if next_state != previous_state and not any(
                item['id'] == asset_id and item['state'] == next_state for item in changes):
            changes.append({'id': asset_id, 'path': None, 'state': next_state})
    if changes and manifest is not None:
        save_manifest(manifest)
        for change in changes:
            push_event('asset.conflict' if change['state'] == 'conflict' else 'asset.disk_changed', change)
    return changes


def start_source_watcher():
    global _watch_thread
    if _watch_thread and _watch_thread.is_alive():
        return
    def watch_loop():
        while True:
            try:
                with _watch_lock:
                    watch_source_once()
            except Exception as error:
                if os.environ.get('FW_BRIDGE_VERBOSE'):
                    print('[Forgeworks] watcher: %s' % error)
            time.sleep(1.5)
    _watch_thread = threading.Thread(target=watch_loop, name='ForgeworksSourceWatcher', daemon=True)
    _watch_thread.start()


def resolve_file_conflict(asset_id, conflict_id, choice):
    if choice not in ('keep-tool', 'keep-disk', 'save-copy'):
        return {'ok': False, 'error': '未知冲突裁决'}
    manifest = load_manifest()
    record = (manifest or {}).get('assets', {}).get(asset_id)
    if not record or record.get('kind') != 'machine':
        return {'ok': False, 'error': 'manifest 中不存在该机器'}
    conflict = next((item for item in record.get('conflicts', [])
                     if item.get('conflictId') == conflict_id and item.get('status') == 'pending'), None)
    if not conflict:
        return {'ok': False, 'error': '冲突不存在或已处理'}
    root = fw_dir()
    target = _safe_join(root, SOURCE_DIR, 'Machines', asset_id, _safe_sync_relative(conflict['path']))
    sync_root = sync_dir()
    tool_copy = _safe_join(sync_root, _safe_sync_relative(conflict['toolCopy']))
    disk_copy = _safe_join(sync_root, _safe_sync_relative(conflict['diskCopy']))
    if choice == 'keep-tool':
        if not os.path.isfile(tool_copy):
            return {'ok': False, 'error': '工具版本副本缺失，无法恢复'}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(tool_copy, target)
    elif choice == 'save-copy':
        if not os.path.isfile(disk_copy):
            return {'ok': False, 'error': '磁盘版本副本缺失'}
        stem, extension = os.path.splitext(target)
        copy_target = stem + '.external-copy' + extension
        shutil.copy2(disk_copy, copy_target)
        conflict['savedCopy'] = os.path.relpath(copy_target, root).replace('\\', '/')
        if os.path.isfile(tool_copy):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(tool_copy, target)
        else:
            with open(target, 'rb') as stream:
                disk_hash = sha1_bytes(stream.read())
            for role, tracked in _tracked_files(record):
                if tracked['path'] == conflict['path']:
                    tracked['sha1'] = disk_hash
                    tracked['size'] = os.path.getsize(target)
                    tracked['mtime'] = now_iso()
    if choice == 'keep-disk':
        with open(target, 'rb') as stream:
            new_hash = sha1_bytes(stream.read())
        for role, tracked in _tracked_files(record):
            if tracked['path'] == conflict['path']:
                tracked['sha1'] = new_hash
                tracked['size'] = os.path.getsize(target)
                tracked['mtime'] = now_iso()
    elif choice == 'keep-tool' or (choice == 'save-copy' and os.path.isfile(tool_copy)):
        baseline = _tool_baseline_path(root, asset_id, conflict['path'])
        if os.path.isfile(target):
            os.makedirs(os.path.dirname(baseline), exist_ok=True)
            shutil.copy2(target, baseline)
    conflict['status'] = choice
    conflict['resolvedAt'] = now_iso()
    record['state'] = 'exported'
    save_manifest(manifest)
    push_event('asset.conflict_resolved', {'id': asset_id, 'choice': choice})
    return {'ok': True, 'id': asset_id, 'choice': choice}


def _blender_worker():
    while True:
        job = _blender_queue.get()
        try:
            _process_blender_job(job)
        except Exception as exception:
            _mark_blender_error(job, str(exception))
        finally:
            _blender_queue.task_done()


def _mark_blender_error(job, error):
    asset_id, _, mesh_sha1, _, bound_root = job
    manifest_file = os.path.join(bound_root, FW_DIR_NAME, SYNC_DIR, 'manifest.json')
    with _manifest_lock:
        manifest = read_json(manifest_file, None)
        rec = (manifest or {}).get('assets', {}).get(asset_id)
        if not rec:
            return
        current_mesh = (rec.get('files', {}).get('mesh') or [{}])[0]
        if current_mesh.get('sha1') != mesh_sha1:
            return
        rec.setdefault('meta', {})['blender'] = {
            'state': 'failed', 'error': error, 'checkedAt': now_iso(),
        }
        write_json(manifest_file, manifest)
    push_event('asset.blender_ready', {'id': asset_id, 'state': 'failed'})


def _queue_blender_check(asset_id, mesh_path, mesh_sha1, expected_materials, bound_root):
    global _blender_worker_started
    with _blender_worker_lock:
        if not _blender_worker_started:
            threading.Thread(target=_blender_worker, daemon=True).start()
            _blender_worker_started = True
    _blender_queue.put((asset_id, mesh_path, mesh_sha1, expected_materials, bound_root))


def _process_blender_job(job):
    asset_id, mesh_path, mesh_sha1, expected_materials, bound_root = job
    project_dir = os.path.join(bound_root, FW_DIR_NAME)
    source_path = os.path.join(project_dir, SOURCE_DIR)
    manifest_file = os.path.join(project_dir, SYNC_DIR, 'manifest.json')
    mesh_file = os.path.join(source_path, 'Machines', asset_id, mesh_path)
    target_dir = os.path.dirname(mesh_file)
    target_thumbnail = os.path.join(target_dir, asset_id + '_preview.png')
    report = None
    error = None
    thumbnail_data = None
    blender = find_blender()
    if not blender:
        error = '未找到 Blender'
    else:
        script = os.path.join(ROOT, 'tools', 'fw_blender.py')
        try:
            with tempfile.TemporaryDirectory(prefix='forgeworks-blender-') as temp_dir:
                thumbnail = os.path.join(temp_dir, 'thumbnail.png')
                report_path = os.path.join(temp_dir, 'report.json')
                result = subprocess.run([
                    blender, '--background', '--factory-startup', '--python-exit-code', '1',
                    '--python', script, '--', '--input', mesh_file,
                    '--thumbnail', thumbnail, '--report', report_path,
                    '--expected-meshes', '1', '--expected-materials', str(expected_materials),
                ], capture_output=True, text=True, timeout=120)
                report = read_json(report_path, None)
                if result.returncode != 0 or not report or not report.get('valid'):
                    errors = report.get('errors', []) if report else []
                    error = '; '.join(errors) or (result.stderr or result.stdout or 'Blender 校验失败')[-1000:]
                elif not os.path.isfile(thumbnail):
                    error = 'Blender 未生成缩略图'
                else:
                    with open(thumbnail, 'rb') as image_file:
                        thumbnail_data = image_file.read()
        except subprocess.TimeoutExpired:
            error = 'Blender 校验超时'
        except Exception as exception:
            error = str(exception)

    state = 'ready' if not error else ('unavailable' if error == '未找到 Blender' else 'failed')
    with _manifest_lock:
        manifest = read_json(manifest_file, None)
        rec = (manifest or {}).get('assets', {}).get(asset_id)
        if not rec:
            return
        current_mesh = (rec.get('files', {}).get('mesh') or [{}])[0]
        if current_mesh.get('sha1') != mesh_sha1:
            return
        if state == 'ready':
            staged_thumbnail = target_thumbnail + '.tmp'
            with open(staged_thumbnail, 'wb') as image_file:
                image_file.write(thumbnail_data)
            os.replace(staged_thumbnail, target_thumbnail)
        meta = rec.setdefault('meta', {})
        blender_meta = {'state': state, 'checkedAt': now_iso()}
        if report:
            blender_meta['report'] = report
        if error:
            blender_meta['error'] = error
        if state == 'ready':
            blender_meta['thumbnail'] = asset_id + '_preview.png'
            rec.setdefault('files', {})['thumbnail'] = [{
                'path': asset_id + '_preview.png',
                'size': len(thumbnail_data),
                'sha1': sha1_bytes(thumbnail_data),
                'mtime': now_iso(),
            }]
        meta['blender'] = blender_meta
        write_json(manifest_file, manifest)
    push_event('asset.blender_ready', {'id': asset_id, 'state': state})


def scan_source():
    """
    核对 manifest 与磁盘实际状态，返回每个资产的 state：
      exported  文件都在，hash 匹配
      missing   manifest 有记录，但磁盘上文件没了（外部删除）
      tampered  文件在但 hash 变了（外部修改）
    同时把核对结果写回 manifest 的 assets.<id>.state（供前端直接读）。
    """
    mf = load_manifest()
    if not mf:
        return {'ok': False, 'error': '未绑定项目或 manifest 不存在'}
    assets = mf.setdefault('assets', {})
    report = {}
    for aid, rec in assets.items():
        base = rec.get('sourceDir')
        if not base:
            rec['state'] = 'missing'
            report[aid] = 'missing'
            continue
        abs_base = os.path.join(fw_dir(), base)
        files = rec.get('files') or {}
        state, bad = 'exported', []
        for role, finfo in files.items():
            flist = finfo if isinstance(finfo, list) else [finfo]
            for fi in flist:
                fp = os.path.join(abs_base, fi.get('path', ''))
                if not os.path.isfile(fp):
                    bad.append('missing:' + fi.get('path', ''))
                    continue
                with open(fp, 'rb') as f:
                    actual = sha1_bytes(f.read())
                if fi.get('sha1') and actual != fi.get('sha1'):
                    bad.append('tampered:' + fi.get('path', ''))
        if any(b.startswith('missing:') for b in bad):
            state = 'missing'
        elif any(b.startswith('tampered:') for b in bad):
            state = 'tampered'
        elif any(item.get('status') == 'pending' for item in rec.get('conflicts', [])):
            state = 'conflict'
        rec['state'] = state
        report[aid] = state
    mf['scannedAt'] = now_iso()
    save_manifest(mf)
    push_event('manifest.scanned', {'report': {k: v for k, v in report.items() if v != 'exported'}})
    return {'ok': True, 'scannedAt': mf['scannedAt'], 'report': report}


# ---------------------------------------------------------------------------
# 资产导出（sync-design §5.1：前端产 GLB，Bridge 落盘 + 更新 manifest）
# ---------------------------------------------------------------------------

def export_asset(kind, asset_id, files, meta):
    """
    files: { 'mesh': {'path':'MC.glb','b64':'...'}, 'icon': {...},
              'tex': [{'path':..., 'b64':...}] }
    写入 _Source/<Kind>/<ID>/，更新 manifest（hash/mtime/state）。
    """
    bound_root = project_root()
    if not bound_root:
        return {'ok': False, 'error': '未绑定项目'}
    kind_dir = {'machine': 'Machines', 'item': 'Items/Icons', 'data': 'Data'}.get(kind)
    if not kind_dir:
        return {'ok': False, 'error': '未知资产类型: %s' % kind}
    if not re.match(r'^[A-Za-z0-9_]+$', asset_id or ''):
        return {'ok': False, 'error': '资产 ID 不合法（仅字母数字下划线）: %r' % asset_id}

    rel_dir = '%s/%s/%s' % (SOURCE_DIR, kind_dir, asset_id)
    abs_dir = os.path.join(fw_dir(), rel_dir)
    previous_manifest = load_manifest() or {}
    previous_record = (previous_manifest.get('assets') or {}).get(asset_id) or {}
    if kind == 'machine' and os.path.isdir(abs_dir):
        if any(item.get('status') == 'pending' for item in previous_record.get('conflicts', [])):
            return {'ok': False, 'error': '该机器有待裁决的外部冲突，请先处理', 'conflict': True}
        if any(name.lower().endswith(('.blend', '.edited.glb')) for name in os.listdir(abs_dir)):
            return {'ok': False, 'error': '检测到 Blender 精修文件，已保护现有资产；先处理精修回灌再导出', 'protected': True}
        previous_hashes = {item.get('path'): item.get('sha1') for _, item in _tracked_files(previous_record)}
        for role, file_info in files.items():
            entries = file_info if isinstance(file_info, list) else [file_info]
            for item in entries:
                relative = _safe_sync_relative(item.get('path'))
                existing = _safe_join(abs_dir, relative)
                expected_hash = previous_hashes.get(relative)
                if expected_hash and os.path.isfile(existing):
                    with open(existing, 'rb') as stream:
                        actual_hash = sha1_bytes(stream.read())
                    if actual_hash != expected_hash:
                        conflict = archive_conflict(fw_dir(), asset_id, relative)
                        conflict.update({'role': role, 'toolSha1': expected_hash})
                        previous_record.setdefault('conflicts', []).append(conflict)
                        previous_record['state'] = 'conflict'
                        save_manifest(previous_manifest)
                        push_event('asset.conflict', {'id': asset_id, 'path': relative, 'state': 'conflict'})
                        return {'ok': False, 'error': '磁盘文件已被外部修改，已留档并等待裁决', 'conflict': conflict}
    os.makedirs(abs_dir, exist_ok=True)

    written = {}
    for role, finfo in files.items():
        flist = finfo if isinstance(finfo, list) else [finfo]
        for fi in flist:
            rel_path = fi.get('path', '')
            if not rel_path or '..' in rel_path or rel_path.startswith('/'):
                return {'ok': False, 'error': '非法文件路径: %r' % rel_path}
            abs_path = os.path.join(abs_dir, rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            try:
                data = base64.b64decode(fi.get('b64', ''))
            except Exception as e:
                return {'ok': False, 'error': 'b64 解码失败（%s）: %s' % (rel_path, e)}
            if not data:
                return {'ok': False, 'error': '空文件内容: %s' % rel_path}
            with open(abs_path, 'wb') as f:
                f.write(data)
            if kind == 'machine':
                save_tool_baseline(fw_dir(), asset_id, rel_path, data)
            written.setdefault(role, []).append({
                'path': rel_path, 'size': len(data),
                'sha1': sha1_bytes(data), 'mtime': now_iso(),
            })

    meta_data = dict(meta or {})
    mesh_record = (written.get('mesh') or [{}])[0]
    blender_state = None
    if kind == 'machine' and mesh_record.get('path'):
        if find_blender():
            blender_state = 'queued'
            meta_data['blender'] = {'state': blender_state}
        else:
            meta_data['blender'] = {'state': 'unavailable', 'error': '未找到 Blender'}

    with _manifest_lock:
        mf = load_manifest() or {'schemaVersion': 1, 'assets': {}}
        mf.setdefault('project', {}).setdefault('root', project_root())
        rec = mf['assets'].setdefault(asset_id, {})
        rec.update({
            'kind': kind,
            'state': 'exported',
            'sourceDir': rel_dir,
            'files': written,
            'exportedAt': now_iso(),
            'exportedBy': 'bridge-%s' % BRIDGE_VERSION,
            'meta': meta_data,
        })
        save_manifest(mf)
    if blender_state == 'queued':
        _queue_blender_check(asset_id, mesh_record['path'], mesh_record['sha1'], meta_data.get('materials', 5), bound_root)
    push_event('asset.exported', {'id': asset_id, 'kind': kind, 'files': sorted(written.keys())})
    return {'ok': True, 'id': asset_id, 'dir': rel_dir,
            'files': {k: [f['path'] for f in v] for k, v in written.items()}}


# ---------------------------------------------------------------------------
# HTTP 处理
# ---------------------------------------------------------------------------

class BridgeHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    # ---- 静态文件：no-store（与 serve.py 同教训） ----
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')   # 允许 file:// 打开时调 API
        super().end_headers()

    def log_message(self, fmt, *args):
        if os.environ.get('FW_BRIDGE_VERBOSE'):
            super().log_message(fmt, *args)

    # ---- CORS preflight ----
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    # ---- GET ----
    def do_GET(self):
        if self.path.startswith('/api/'):
            self._route_get(self.path[5:].split('?')[0])
        else:
            super().do_GET()

    def _route_get(self, route):
        if route == 'status':
            self._json({'ok': True, 'bridge': BRIDGE_VERSION, 'project': current_project(),
                        'blender': blender_info()})
        elif route == 'projects':
            self._json({'ok': True, 'current': current_project(), 'recent': recent_projects()})
        elif route == 'project/info':
            mf = load_manifest()
            self._json({'ok': True, 'manifest': mf, 'root': project_root()})
        elif route == 'manifest':
            self._json({'ok': True, 'manifest': load_manifest()})
        elif route == 'ue/assets':
            bound_fw = fw_dir()
            if not bound_fw:
                self._json({'ok': False, 'error': '未绑定项目'}, 409)
            else:
                self._json({'ok': True, **normalize_ue_snapshot_path(bound_fw)})
        elif route == 'conflicts':
            manifest = load_manifest() or {}
            rows = []
            for asset_id, record in (manifest.get('assets') or {}).items():
                rows.extend(dict(item, id=asset_id) for item in record.get('conflicts', []) if item.get('status') == 'pending')
            self._json({'ok': True, 'conflicts': rows})
        elif route == 'pipeline/providers':
            cfg = read_json(CONFIG_FILE, {}) or {}
            if not isinstance(cfg, dict):
                cfg = {}
            providers = cfg.get('providers') or {}
            if not isinstance(providers, dict):
                providers = {}
            tripo_config = providers.get('tripo') if isinstance(providers.get('tripo'), dict) else {}
            self._json({'ok': True, 'providers': {
                name: {'configured': bool((value or {}).get('api_key')), 'enabled': bool((value or {}).get('api_key'))}
                for name, value in providers.items() if isinstance(value, dict)
            }, 'remoteExecutionAvailable': bool(tripo_config.get('api_key'))})
        elif route.startswith('pipeline/graph/'):
            asset_id = route.rsplit('/', 1)[-1]
            try:
                graph = fw_pipeline.load_graph(fw_dir(), asset_id)
                self._json({'ok': True, 'graph': graph})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route.startswith('pipeline/output/'):
            parts = route.split('/')
            try:
                if self.headers.get('Origin') and not self._same_loopback_origin():
                    raise ValueError('流水线输出只允许本地同源访问')
                if len(parts) != 4 or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', parts[2]) or not re.fullmatch(r'(model|image)_task_[A-Za-z0-9_-]{4,128}\.(glb|png|jpg|webp)', parts[3]):
                    raise ValueError('输出路径非法')
                path = os.path.join(fw_pipeline.pipeline_root(fw_dir(), parts[2]), 'outputs', parts[3])
                if not os.path.isfile(path) or os.path.getsize(path) > 150 * 1024 * 1024:
                    raise ValueError('输出文件不存在或过大')
                with open(path, 'rb') as stream:
                    data = stream.read()
                ext = parts[3].rsplit('.', 1)[1]
                content_type = 'model/gltf-binary' if ext == 'glb' else ('image/jpeg' if ext == 'jpg' else 'image/' + ext)
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 404)
        elif route == 'events':
            self._sse()
        elif route.startswith('thumbnail/machine/'):
            self._serve_machine_thumbnail(route.rsplit('/', 1)[-1])
        else:
            self._json({'ok': False, 'error': 'unknown route: %s' % route}, 404)

    def _serve_machine_thumbnail(self, asset_id):
        if not re.match(r'^[A-Za-z0-9_]+$', asset_id or ''):
            self._json({'ok': False, 'error': '资产 ID 不合法'}, 400)
            return
        manifest = load_manifest() or {}
        record = manifest.get('assets', {}).get(asset_id) or {}
        thumbnail = (record.get('meta') or {}).get('blender') or {}
        if thumbnail.get('state') != 'ready' or thumbnail.get('thumbnail') != asset_id + '_preview.png':
            self._json({'ok': False, 'error': '缩略图尚未生成'}, 404)
            return
        path = os.path.join(source_dir(), 'Machines', asset_id, asset_id + '_preview.png')
        try:
            with open(path, 'rb') as image_file:
                data = image_file.read()
        except OSError:
            self._json({'ok': False, 'error': '缩略图文件不存在'}, 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- POST ----
    def do_POST(self):
        if not self.path.startswith('/api/'):
            self._json({'ok': False, 'error': 'unknown route'}, 404)
            return
        body = self._read_body()
        route = self.path[5:].split('?')[0]
        if route == 'project/bind':
            self._json(bind_project((body or {}).get('path', '')))
        elif route == 'project/pick':
            if not self._same_loopback_origin():
                self._json({'ok': False, 'error': '目录选择只允许 Forgeworks 本地同源页面调用'}, 403)
            else:
                self._json(pick_folder())
        elif route == 'project/unbind':
            self._json(unbind_project())
        elif route == 'manifest/scan':
            self._json(scan_source())
        elif route == 'export/asset':
            b = body or {}
            self._json(export_asset(b.get('kind'), b.get('id'),
                                    b.get('files') or {}, b.get('meta') or {}))
        elif route == 'ue/report':
            b = body or {}
            self._json(report_ue_import(b.get('id'), b.get('ue')))
        elif route == 'conflicts/resolve':
            b = body or {}
            self._json(resolve_file_conflict(b.get('id'), b.get('conflictId'), b.get('choice')))
        elif route == 'pipeline/graph/save':
            b = body or {}
            try:
                graph = fw_pipeline.save_graph(fw_dir(), b.get('assetId'), b.get('graph'))
                push_event('pipeline.graph_saved', {'id': b.get('assetId'), 'revision': graph['revision']})
                self._json({'ok': True, 'graph': graph})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/graph/template':
            b = body or {}
            try:
                graph = fw_pipeline.starter_graph(b.get('assetId'), b.get('template', 'machine'))
                graph = fw_pipeline.save_graph(fw_dir(), b.get('assetId'), graph)
                self._json({'ok': True, 'graph': graph})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/run':
            b = body or {}
            try:
                result = fw_pipeline.execute_local(fw_dir(), b.get('assetId'), b.get('nodeId'), bool(b.get('through')))
                push_event('pipeline.progress', {'id': b.get('assetId'), 'ran': result['ran']})
                self._json({'ok': True, **result})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/provider/submit':
            b = body or {}
            try:
                if not self._same_loopback_origin():
                    raise ValueError('Provider 任务仅允许 Forgeworks 本地同源页面提交')
                if b.get('confirmRemote') is not True:
                    raise ValueError('需要用户明确确认可能产生 Provider 费用')
                asset_id, node_id = b.get('assetId'), b.get('nodeId')
                graph = fw_pipeline.load_graph(fw_dir(), asset_id)
                nodes, _ = fw_pipeline.validate_graph(graph)
                node = nodes.get(node_id)
                if not node or node.get('type') not in ('textToImage', 'imageTo3D'):
                    raise ValueError('目标节点不是受支持的远程生成节点')
                incoming = [edge for edge in graph['edges'] if edge.get('to') == node_id]
                prompt = ''
                input_task_id = None
                if node['type'] == 'textToImage':
                    prompt_edge = next((edge for edge in incoming if edge.get('in') == 'text'), None)
                    if prompt_edge:
                        upstream = nodes[prompt_edge['from']]
                        prompt = ((upstream.get('result') or {}).get('output') or {}).get('text', '')
                    prompt = prompt or node.get('params', {}).get('prompt', '')
                else:
                    image_edge = next((edge for edge in incoming if edge.get('in') == 'image'), None)
                    if image_edge:
                        upstream = nodes[image_edge['from']]
                        input_task_id = (upstream.get('result') or {}).get('providerTask', {}).get('taskId')
                    if not input_task_id:
                        input_task_id = node.get('params', {}).get('inputTaskId')
                task = fw_providers.submit(read_json(CONFIG_FILE, {}) or {}, node['type'], node.get('params'), prompt, input_task_id)
                previous_task = node.setdefault('result', {}).get('providerTask')
                if previous_task:
                    node['result'].setdefault('history', []).append(previous_task)
                node.setdefault('result', {})['providerTask'] = task
                node['result']['state'] = 'queued'
                result = fw_pipeline.save_graph(fw_dir(), asset_id, graph)
                push_event('pipeline.progress', {'id': asset_id, 'nodeId': node_id, 'state': 'queued', 'taskId': task['taskId']})
                self._json({'ok': True, 'graph': result, 'taskId': task['taskId'], 'state': 'queued'})
            except (ValueError, TypeError, RuntimeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/provider/poll':
            b = body or {}
            try:
                if not self._same_loopback_origin():
                    raise ValueError('Provider 任务仅允许 Forgeworks 本地同源页面查询')
                asset_id, node_id = b.get('assetId'), b.get('nodeId')
                graph = fw_pipeline.load_graph(fw_dir(), asset_id)
                nodes, _ = fw_pipeline.validate_graph(graph)
                node = nodes.get(node_id)
                task = (node or {}).get('result', {}).get('providerTask') or {}
                if not node or not task.get('taskId'):
                    raise ValueError('没有可轮询的 Provider 任务')
                result = fw_providers.poll(read_json(CONFIG_FILE, {}) or {}, task['taskId'])
                state = result.get('status')
                if state not in ('queued', 'running', 'success', 'failed', 'cancelled', 'banned'):
                    raise ValueError('Provider 返回了未知任务状态')
                task.update({'state': state, 'progress': max(0, min(100, int(result.get('progress') or 0))),
                             'creditsConsumed': result.get('credits_consumed'), 'error': str(result.get('error_message') or '')[:300]})
                node['result']['state'] = 'done' if state == 'success' else ('failed' if state in ('failed', 'cancelled', 'banned') else state)
                output = result.get('output') or {}
                if state == 'success' and node['type'] == 'textToImage':
                    image_data, extension = fw_providers.download_image(output.get('generated_image_url'))
                    output_dir = os.path.join(fw_pipeline.pipeline_root(fw_dir(), asset_id), 'outputs')
                    os.makedirs(output_dir, exist_ok=True)
                    filename = 'image_' + task['taskId'] + '.' + extension
                    with open(os.path.join(output_dir, filename), 'wb') as stream:
                        stream.write(image_data)
                    task['output'] = {'imagePath': 'outputs/' + filename, 'size': len(image_data)}
                if state == 'success' and node['type'] == 'imageTo3D':
                    data = fw_providers.download_model(output.get('model_url'))
                    output_dir = os.path.join(fw_pipeline.pipeline_root(fw_dir(), asset_id), 'outputs')
                    os.makedirs(output_dir, exist_ok=True)
                    filename = 'model_' + task['taskId'] + '.glb'
                    with open(os.path.join(output_dir, filename), 'wb') as stream:
                        stream.write(data)
                    task['output'] = {'modelPath': 'outputs/' + filename, 'size': len(data)}
                task['error'] = str(result.get('error_message') or '')[:300]
                result_graph = fw_pipeline.save_graph(fw_dir(), asset_id, graph)
                push_event('pipeline.progress', {'id': asset_id, 'nodeId': node_id, 'state': state,
                                                  'progress': task.get('progress')})
                self._json({'ok': True, 'graph': result_graph, 'task': task})
            except (ValueError, TypeError, RuntimeError, OSError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        else:
            self._json({'ok': False, 'error': 'unknown route: %s' % route}, 404)

    # ---- helpers ----
    def _read_body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n <= 0 or n > 64 * 1024 * 1024:
                return {}
            return json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return {}

    def _same_loopback_origin(self):
        origin = self.headers.get('Origin')
        if not origin:
            return False
        parsed = urlparse(origin)
        port = self.server.server_address[1]
        allowed_hosts = ('127.0.0.1:%d' % port, 'localhost:%d' % port)
        return (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')
                and parsed.port == port and (self.headers.get('Host') or '') in allowed_hosts)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        try:
            self.wfile.write(b': hello\n\n')
            self.wfile.flush()
        except Exception:
            return
        _sse_clients.append(self.wfile)
        # 心跳：连接挂着，事件由 push_event 异步写
        try:
            while True:
                time.sleep(15)
                self.wfile.write(b': ping\n\n')
                self.wfile.flush()
        except Exception:
            pass
        finally:
            try:
                _sse_clients.remove(self.wfile)
            except ValueError:
                pass


class Bridge(ThreadingHTTPServer):
    allow_reuse_address = True   # SSE 长连接会占住线程，必须多线程


def main():
    os.chdir(ROOT)
    start_source_watcher()
    httpd = Bridge(('127.0.0.1', PORT), BridgeHandler)
    print('Forgeworks Bridge v%s' % BRIDGE_VERSION)
    print('  http://127.0.0.1:%d/        （界面）' % PORT)
    print('  http://127.0.0.1:%d/api/status（状态）' % PORT)
    bl = blender_info()
    print('  Blender: %s' % (bl['path'] or '未找到（缩略图/校验功能降级）'))
    proj = project_root()
    print('  项目: %s' % (proj or '未绑定（在界面「同步」页绑定）'))
    print('  Ctrl+C 停止')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')


if __name__ == '__main__':
    main()
