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
import copy
import hashlib
import json
import math
import os
import pathlib
import queue
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse, parse_qs
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
_pipeline_spec = importlib.util.spec_from_file_location('fw_pipeline', os.path.join(ROOT, 'tools', 'fw_pipeline.py'))
fw_pipeline = importlib.util.module_from_spec(_pipeline_spec)
_pipeline_spec.loader.exec_module(fw_pipeline)
_spec_spec = importlib.util.spec_from_file_location('fw_spec', os.path.join(ROOT, 'tools', 'fw_spec.py'))
fw_spec = importlib.util.module_from_spec(_spec_spec)
_spec_spec.loader.exec_module(fw_spec)
_provider_spec = importlib.util.spec_from_file_location('fw_providers', os.path.join(ROOT, 'tools', 'fw_providers.py'))
fw_providers = importlib.util.module_from_spec(_provider_spec)
_provider_spec.loader.exec_module(fw_providers)
_texture_spec = importlib.util.spec_from_file_location('fw_textures', os.path.join(ROOT, 'tools', 'fw_textures.py'))
fw_textures = importlib.util.module_from_spec(_texture_spec)
_texture_spec.loader.exec_module(fw_textures)
_project_spec = importlib.util.spec_from_file_location('fw_project', os.path.join(ROOT, 'tools', 'fw_project.py'))
fw_project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(fw_project)
_terminal_spec = importlib.util.spec_from_file_location('fw_terminal', os.path.join(ROOT, 'tools', 'fw_terminal.py'))
fw_terminal = importlib.util.module_from_spec(_terminal_spec)
_terminal_spec.loader.exec_module(fw_terminal)

_TERMINAL = fw_terminal.TerminalManager(PORT)

BRIDGE_VERSION = '0.1.0'
STATE_FILE = os.path.join(ROOT, 'tools', '.bridge_state.json')
CONFIG_FILE = os.path.join(ROOT, 'tools', 'bridge_config.json')
CCSWITCH_DB = os.path.join(os.path.expanduser('~'), '.cc-switch', 'cc-switch.db')

# 目录结构约定（sync-design §3.1）
FW_DIR_NAME = 'Forgeworks'                 # 项目根下
SOURCE_DIR = '_Source'
SYNC_DIR = '_Sync'

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


PROVIDER_MODEL_RE = re.compile(r'[A-Za-z0-9._-]{1,80}')
PROVIDER_ENDPOINT_HOSTS = ('volces.com',)


def _provider_endpoint_allowed(value):
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and bool(host) and any(
        host == suffix or host.endswith('.' + suffix) for suffix in PROVIDER_ENDPOINT_HOSTS)


def provider_settings_view(config):
    """Provider 配置的非敏感视图，密钥永不回传前端。"""
    providers = config.get('providers') if isinstance(config, dict) else None
    providers = providers if isinstance(providers, dict) else {}
    rows = {}
    for name in fw_providers.PROVIDERS:
        value = providers.get(name)
        value = value if isinstance(value, dict) else {}
        row = {'configured': bool(str(value.get('api_key') or '').strip())}
        for field in ('endpoint', 'image_model', 'model3d_model'):
            if isinstance(value.get(field), str) and value[field].strip():
                row[field] = value[field].strip()
        rows[name] = row
    return rows


def save_provider_settings(payload, path=CONFIG_FILE):
    providers = payload.get('providers') if isinstance(payload, dict) else None
    if not isinstance(providers, dict) or not providers:
        raise ValueError('缺少 Provider 配置')
    config = read_json(path, {}) or {}
    config = config if isinstance(config, dict) else {}
    current = config.get('providers')
    current = dict(current) if isinstance(current, dict) else {}
    for name, incoming in providers.items():
        if name not in fw_providers.PROVIDERS:
            raise ValueError('不支持的 Provider：%s' % (name,))
        if not isinstance(incoming, dict):
            raise ValueError('Provider 配置格式无效')
        target = dict(current.get(name)) if isinstance(current.get(name), dict) else {}
        changed = False
        key = incoming.get('api_key')
        if isinstance(key, str) and key.strip():
            if len(key.strip()) > 512:
                raise ValueError('API Key 过长')
            target['api_key'] = key.strip()
            changed = True
        if incoming.get('clearKey') is True:
            target.pop('api_key', None)
            changed = True
        endpoint = incoming.get('endpoint')
        if isinstance(endpoint, str) and endpoint.strip():
            endpoint = endpoint.strip().rstrip('/')
            if not _provider_endpoint_allowed(endpoint):
                raise ValueError('Endpoint 必须是 https 的火山域名')
            target['endpoint'] = endpoint
            changed = True
        for field in ('image_model', 'model3d_model'):
            value = incoming.get(field)
            if isinstance(value, str) and value.strip():
                if not PROVIDER_MODEL_RE.fullmatch(value.strip()):
                    raise ValueError('模型名只能包含字母、数字、点、下划线和短横线')
                target[field] = value.strip()
                changed = True
        if changed:
            if target:
                current[name] = target
            else:
                current.pop(name, None)
    config['providers'] = current
    write_json(path, config)
    _restrict_config_file(path)
    return provider_settings_view(config)


def _restrict_config_file(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _ccswitch_entries(path=CCSWITCH_DB):
    """只读 cc-switch 中可直接用于 Seedream / Seed3D 的 Ark 配置。"""
    if not os.path.isfile(path):
        return []
    try:
        connection = sqlite3.connect(pathlib.Path(path).as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            rows = connection.execute(
                'SELECT id, name, settings_config FROM providers WHERE app_type = ?',
                ('claude',)).fetchall()
        finally:
            connection.close()
    except (sqlite3.Error, ValueError):
        return []
    entries = []
    for provider_id, name, raw in rows:
        try:
            settings = json.loads(raw or '{}')
        except (TypeError, ValueError):
            continue
        env = settings.get('env') if isinstance(settings, dict) else None
        env = env if isinstance(env, dict) else {}
        key = str(env.get('ANTHROPIC_API_KEY') or '').strip()
        base = str(env.get('ANTHROPIC_BASE_URL') or '').strip().rstrip('/')
        model = str(env.get('ANTHROPIC_MODEL') or env.get('ANTHROPIC_DEFAULT_SONNET_MODEL') or '').strip()
        if not key or not model or not _provider_endpoint_allowed(base):
            continue
        lowered = model.lower()
        if 'seedream' in lowered:
            field = 'image_model'
        elif 'seed3d' in lowered:
            field = 'model3d_model'
        else:
            continue
        entries.append({'id': str(provider_id), 'name': str(name or ''),
                        'base': base, 'model': model, 'field': field, 'api_key': key})
    return entries


def ccswitch_candidates(path=CCSWITCH_DB):
    candidates = []
    for entry in _ccswitch_entries(path):
        key = entry['api_key']
        candidates.append({
            'id': entry['id'], 'name': entry['name'], 'base': entry['base'],
            'model': entry['model'], 'field': entry['field'],
            'keyHint': '…' + key[-4:] if len(key) > 8 else '已配置',
        })
    return candidates


def import_ccswitch_provider(provider_id, path=CCSWITCH_DB, config_path=CONFIG_FILE):
    wanted = str(provider_id or '').strip()
    entry = next((item for item in _ccswitch_entries(path) if item['id'] == wanted), None)
    if entry is None:
        raise ValueError('未找到匹配的 cc-switch 火山图像/3D 生成配置')
    config = read_json(config_path, {}) or {}
    config = config if isinstance(config, dict) else {}
    providers = config.get('providers')
    providers = dict(providers) if isinstance(providers, dict) else {}
    ark = dict(providers.get('ark')) if isinstance(providers.get('ark'), dict) else {}
    ark['api_key'] = entry['api_key']
    ark['endpoint'] = entry['base']
    ark[entry['field']] = entry['model']
    providers['ark'] = ark
    config['providers'] = providers
    write_json(config_path, config)
    _restrict_config_file(config_path)
    return provider_settings_view(config)


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
# 项目内容写入（界面自动保存与 MCP 共用，revision 乐观锁 + 变更广播）
# ---------------------------------------------------------------------------

CONTENT_COLLECTIONS = ('elements', 'items', 'machines', 'recipes', 'techs')
_content_lock = threading.Lock()


def _content_source(body):
    source = body.get('source')
    source = source if isinstance(source, str) and source else 'api'
    client_id = body.get('clientId')
    if not isinstance(client_id, str) or len(client_id) > 64:
        client_id = None
    return source[:32], client_id


def _content_conflict(current_revision, base_revision):
    return (base_revision is not None
            and str(base_revision) != current_revision)


def save_content_checked(root, content, base_revision=None, source='api', client_id=None):
    """整包写入；baseRevision 不匹配时返回 conflict，不覆盖磁盘内容。"""
    if not root:
        raise ValueError('未打开 Forgeworks 项目')
    with _content_lock:
        current_revision = fw_project.content_revision(root)
        if _content_conflict(current_revision, base_revision):
            return {'ok': False, 'conflict': True, 'revision': current_revision,
                    'error': '项目内容已被其他写入修改，请读取最新内容后重试'}
        fw_project.save_content(root, content)
        revision = fw_project.content_revision(root)
    push_event('content.changed', {'root': root, 'revision': revision,
                                   'source': source, 'clientId': client_id, 'entity': None})
    return {'ok': True, 'revision': revision}


def upsert_entity(root, coll, entity, base_revision=None, source='api', client_id=None):
    if not root:
        raise ValueError('未打开 Forgeworks 项目')
    if coll not in CONTENT_COLLECTIONS:
        raise ValueError('不支持的内容集合: %s' % coll)
    if not isinstance(entity, dict):
        raise ValueError('entity 必须是对象')
    entity_id = entity.get('id')
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError('entity.id 必须是非空字符串')
    if len(entity_id) > 64:
        raise ValueError('entity.id 不能超过 64 个字符')
    with _content_lock:
        current_revision = fw_project.content_revision(root)
        if _content_conflict(current_revision, base_revision):
            return {'ok': False, 'conflict': True, 'revision': current_revision,
                    'error': '项目内容已被其他写入修改，请读取最新内容后重试'}
        content = fw_project.load_content(root) or {}
        for name in CONTENT_COLLECTIONS:
            if not isinstance(content.get(name), list):
                content[name] = []
        collection = content[coll]
        created = True
        for index, row in enumerate(collection):
            if isinstance(row, dict) and row.get('id') == entity_id:
                collection[index] = entity
                created = False
                break
        if created:
            collection.append(entity)
        content[coll] = collection
        fw_project.save_content(root, content)
        revision = fw_project.content_revision(root)
    push_event('content.changed', {'root': root, 'revision': revision,
                                   'source': source, 'clientId': client_id,
                                   'entity': {'coll': coll, 'id': entity_id, 'op': 'upsert'}})
    return {'ok': True, 'revision': revision, 'created': created, 'entity': entity}


def delete_entity(root, coll, entity_id, base_revision=None, source='api', client_id=None):
    if not root:
        raise ValueError('未打开 Forgeworks 项目')
    if coll not in CONTENT_COLLECTIONS:
        raise ValueError('不支持的内容集合: %s' % coll)
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError('id 必须是非空字符串')
    with _content_lock:
        current_revision = fw_project.content_revision(root)
        if _content_conflict(current_revision, base_revision):
            return {'ok': False, 'conflict': True, 'revision': current_revision,
                    'error': '项目内容已被其他写入修改，请读取最新内容后重试'}
        content = fw_project.load_content(root) or {}
        collection = content.get(coll)
        if not isinstance(collection, list):
            return {'ok': False, 'notFound': True, 'revision': current_revision,
                    'error': '实体不存在: %s/%s' % (coll, entity_id)}
        kept = [row for row in collection
                if not (isinstance(row, dict) and row.get('id') == entity_id)]
        if len(kept) == len(collection):
            return {'ok': False, 'notFound': True, 'revision': current_revision,
                    'error': '实体不存在: %s/%s' % (coll, entity_id)}
        content[coll] = kept
        fw_project.save_content(root, content)
        revision = fw_project.content_revision(root)
    push_event('content.changed', {'root': root, 'revision': revision,
                                   'source': source, 'clientId': client_id,
                                   'entity': {'coll': coll, 'id': entity_id, 'op': 'delete'}})
    return {'ok': True, 'revision': revision}


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
    """当前 Forgeworks 项目根目录（未打开返回 None）。"""
    p = _state.get('projectRoot')
    if not p or not os.path.isdir(p):
        return None
    if fw_project.is_project(p):
        return p
    found = fw_project.detect_project(p)
    return found['root'] if found else None


def fw_dir():
    return project_root()


PIPELINE_HISTORY_LIMIT = 50
PROVIDER_NODE_TYPES = ('textToImage', 'imageTo3D', 'partImage', 'partModel',
                       'blueprint', 'threeView')


def write_bytes_atomic(path, data):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix='.output-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def store_task_output(root, asset_id, kind, node_type, task):
    """同步成功的图片立即落盘，节点无需再等一次轮询才显示结果。"""
    if node_type not in ('textToImage', 'partImage', 'threeView') or task.get('state') != 'success':
        return task
    output = task.get('output') if isinstance(task.get('output'), dict) else {}
    url = output.get('generated_image_url')
    if not isinstance(url, str) or not url:
        return task
    try:
        data, extension = fw_providers.download_image(url)
    except (ValueError, RuntimeError, OSError):
        return task
    directory = os.path.join(fw_pipeline.pipeline_root(root, asset_id, kind), 'outputs')
    os.makedirs(directory, exist_ok=True)
    filename = 'image_' + task['taskId'] + '.' + extension
    write_bytes_atomic(os.path.join(directory, filename), data)
    task['output'] = {'imagePath': 'outputs/' + filename, 'size': len(data)}
    return task


PART_IMAGE_SUFFIX = '【拆件】以参考图为准，只输出按说明拆分出的这一个部件；保持参考图中的造型、比例、配色与朝向；纯色背景、单个部件居中、无其他部件、无地面投影。'

THREE_VIEW_SUFFIX = ('【三视图】同一模型的正面、侧面、顶面三个正交视图，横向三等分排列；'
                     '每格都是正交投影、无透视、同一比例尺；纯白背景；无阴影、无地面、'
                     '无文字、无标注、无边框；三格之间留出清晰空白，每格完整不裁切。')


def _three_view_prompt(subject=''):
    text = str(subject or '').strip()
    return ((text + '\n\n') if text else '') + THREE_VIEW_SUFFIX


def _part_image_prompt(text, part=None):
    base = str(text or '').strip()
    extra = ''
    if isinstance(part, dict) and part.get('sizeM'):
        size = part['sizeM']
        extra = ('目标包围盒尺寸：X %.2f m，Y %.2f m，Z %.2f m；'
                 '端口只作为装配锚点，不需要在图中画出文字。'
                 % (float(size[0]), float(size[1]), float(size[2])))
    body = ((base + '\n\n') if base else '') + ((extra + '\n') if extra else '')
    return body + PART_IMAGE_SUFFIX


def _part_name_from_prompt(text):
    first = next((line.strip() for line in str(text or '').splitlines() if line.strip()), '')
    return first.replace('【', '').replace('】', '').strip()[:32]


def _image_data_url(root, asset_id, kind, image_path):
    try:
        absolute = fw_pipeline.resolve_output(root, asset_id, kind, os.path.basename(str(image_path)))
        if not absolute or os.path.getsize(absolute) > 8 * 1024 * 1024:
            return None
        with open(absolute, 'rb') as stream:
            raw = stream.read()
        extension = os.path.splitext(absolute)[1].lower().lstrip('.')
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'webp': 'image/webp'}.get(extension, 'image/png')
        return 'data:%s;base64,%s' % (mime, base64.b64encode(raw).decode())
    except (OSError, ValueError, TypeError):
        return None


def _part_reference_image(root, asset_id, kind, nodes, incoming):
    image_edge = next((edge for edge in incoming if edge.get('in') == 'image'), None)
    if not image_edge:
        raise ValueError('单件效果图需要整体效果图：请把整体效果图节点连到 image 口')
    upstream_result = (nodes[image_edge['from']].get('result') or {})
    # 上游图被改动后会打回 dirty，旧图不能再当拆件参考
    if upstream_result.get('state') not in ('done', None):
        raise ValueError('整体效果图尚未生成或已变更：请先运行上游整体效果图节点')
    upstream_task = upstream_result.get('providerTask') or {}
    data = _image_data_url(root, asset_id, kind, (upstream_task.get('output') or {}).get('imagePath'))
    if not data:
        raise ValueError('整体效果图文件不可用或超过 8 MB，无法作为拆件参考图')
    return data


def _upstream_image_path(root, asset_id, kind, incoming, nodes, label='整机效果图'):
    edge = next((edge for edge in incoming if edge.get('in') == 'image'), None)
    if not edge:
        raise ValueError('%s需要参考图：请把%s节点连到 image 口' % (label, label))
    source = nodes.get(edge.get('from')) or {}
    result = source.get('result') or {}
    # 上游图被改动后会打回 dirty，旧图不能再当尺寸参考
    if result.get('state') not in ('done', None):
        raise ValueError('%s尚未生成或已变更：请先运行上游%s节点' % (label, label))
    provider = result.get('providerTask') if isinstance(result.get('providerTask'), dict) else {}
    task_output = provider.get('output') if isinstance(provider.get('output'), dict) else {}
    output = result.get('output') or {}
    image_path = (task_output.get('imagePath') or output.get('sheetPath')
                  or output.get('imagePath'))
    absolute = fw_pipeline.resolve_output(
        root, asset_id, kind, os.path.basename(str(image_path or '')))
    if not absolute:
        raise ValueError('%s文件不可用，无法分析尺寸' % label)
    return absolute


def _spec_from_incoming(root, asset_id, kind, nodes, incoming):
    edge = next((edge for edge in incoming if edge.get('in') == 'spec'), None)
    if not edge:
        return None
    result = (nodes.get(edge.get('from')) or {}).get('result') or {}
    # 上游规格被改动后会打回 dirty，旧规格不能再喂给拆件
    if result.get('state') not in ('done', None):
        raise ValueError('尺寸规格尚未生成或已变更：请先运行尺寸规格节点')
    output = result.get('output') or {}
    candidate = output.get('spec')
    if isinstance(candidate, dict):
        return fw_spec.validate_spec(candidate)
    path = output.get('specPath')
    if not path:
        return None
    root_path = os.path.realpath(fw_pipeline.pipeline_root(root, asset_id, kind))
    absolute = os.path.realpath(os.path.join(root_path, str(path)))
    if os.path.commonpath((root_path, absolute)) != root_path:
        raise ValueError('SPEC_INVALID: 尺寸规格路径越界')
    try:
        return fw_spec.read_spec(absolute)
    except (OSError, ValueError):
        raise ValueError('尺寸规格文件不可用：%s' % path)


def ue_project_root():
    p = _state.get('ueProjectRoot')
    return p if p and os.path.isdir(p) else None


def ue_export_root():
    p = ue_project_root()
    return os.path.join(p, FW_DIR_NAME) if p else None


def current_ue_target():
    p = ue_project_root()
    if not p:
        return None
    return fw_project.ue_target_info(p)


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
    """当前 Forgeworks 项目的描述（未打开返回 None）。"""
    root = project_root()
    return fw_project.project_info(root) if root else None


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


def _remember_current(project, ue_target=None):
    _state['projectRoot'] = project['root']
    _state.pop('projectKind', None)
    if ue_target:
        _state['ueProjectRoot'] = ue_target['root']
    else:
        _state.pop('ueProjectRoot', None)
    _state['boundAt'] = now_iso()
    remember_project(project)
    save_state()


def open_project(path):
    """打开 Forgeworks 项目；旧版 <UE>/Forgeworks 布局自动迁移识别。"""
    path = os.path.abspath(os.path.expanduser(str(path or '')))
    if not os.path.isdir(path):
        return {'ok': False, 'error': '目录不存在: %s' % path}
    found = fw_project.detect_project(path)
    if not found and find_uproject(path):
        root = os.path.join(path, FW_DIR_NAME)
        fw_project.initialize_project(root, project_label(path, find_uproject(path)), BRIDGE_VERSION)
        found = {'root': root, 'kind': 'legacy', 'ueRoot': path}
    if not found:
        return {'ok': False, 'error': '不是 Forgeworks 项目（缺少 %s）' % fw_project.PROJECT_MARKER}
    root = found['root']
    if not fw_project.is_project(root):
        label = project_label(found['ueRoot'], find_uproject(found['ueRoot'])) if found.get('ueRoot') else None
        fw_project.initialize_project(root, label, BRIDGE_VERSION)
    project = fw_project.project_info(root)
    ue_target = None
    ue_root = found.get('ueRoot')
    if ue_root:
        try:
            candidate = fw_project.prepare_ue_target(ue_root)
            # 旧版 <UE>/Forgeworks 布局里项目目录就是导出目录，不能再当作导出目标
            if os.path.realpath(candidate['forgeworksRoot']) != os.path.realpath(root):
                ue_target = candidate
        except ValueError:
            ue_target = None
    _remember_current(project, ue_target)
    with _watch_lock:
        migration = fw_project.migrate_layout(root)
        ue_migration = fw_project.migrate_ue_export(root, ue_target['root']) if ue_target else None
    push_event('project.opened', {'root': root, 'name': project['name']})
    return {'ok': True, 'project': project, 'fwDir': root, 'ueTarget': ue_target, 'created': [],
            'migrated': migration, 'ueMigrated': ue_migration}


def create_project(parent, name):
    try:
        result = fw_project.create_project(parent, name, BRIDGE_VERSION)
    except (OSError, ValueError) as error:
        return {'ok': False, 'error': str(error)}
    project = result['project']
    _state['projectRoot'] = result['root']
    _state.pop('projectKind', None)
    _state.pop('ueProjectRoot', None)
    _state['boundAt'] = now_iso()
    remember_project(project)
    save_state()
    push_event('project.created', {'root': result['root'], 'name': project['name']})
    return {'ok': True, 'project': project, 'fwDir': result['root'], 'ueTarget': None, 'created': []}


def _same_as_project(export_root):
    root = fw_dir()
    return bool(root and export_root) and os.path.realpath(export_root) == os.path.realpath(root)


def set_ue_target(path):
    try:
        target = fw_project.prepare_ue_target(path)
    except ValueError as error:
        return {'ok': False, 'error': str(error)}
    if _same_as_project(os.path.join(target['root'], FW_DIR_NAME)):
        return {'ok': False, 'error': '该目录就是当前 Forgeworks 项目，请选择另一个 UE 导出目标'}
    _state['ueProjectRoot'] = target['root']
    save_state()
    with _watch_lock:
        migrated = fw_project.migrate_ue_export(fw_dir(), target['root']) if fw_dir() else None
    push_event('project.ue_target', {'root': target['root'], 'uproject': target['uproject']})
    return {'ok': True, 'ueTarget': target, 'ueMigrated': migrated}


def publish_to_ue(asset_ids=None):
    root, target = fw_dir(), ue_export_root()
    if not root:
        return {'ok': False, 'error': '未打开 Forgeworks 项目'}
    if not target:
        return {'ok': False, 'error': '尚未设置 UE 导出目标'}
    if _same_as_project(target):
        return {'ok': False, 'error': 'UE 导出目标与当前 Forgeworks 项目相同，请重新设置'}
    with _watch_lock:
        result = fw_project.publish_to_ue(root, ue_project_root(), asset_ids, BRIDGE_VERSION)
    if result.get('published'):
        push_event('asset.published', {'assets': result['published'], 'target': ue_project_root()})
    return result


def unbind_project():
    _state.pop('projectRoot', None)
    _state.pop('projectKind', None)
    _state.pop('ueProjectRoot', None)
    save_state()
    push_event('project.unbound', None)
    return {'ok': True}


def normalize_bound_project():
    """把旧版「状态指向 UE 项目根」迁移为「Forgeworks 项目根」，并升级目录布局。"""
    root = _state.get('projectRoot')
    if not root:
        return
    if fw_project.is_project(root):
        fw_root = root
    else:
        found = fw_project.detect_project(root)
        if not found:
            return
        fw_root = found['root']
        if not fw_project.is_project(fw_root):
            ue_root = found.get('ueRoot')
            label = project_label(ue_root, find_uproject(ue_root)) if ue_root else None
            fw_project.initialize_project(fw_root, label, BRIDGE_VERSION)
        _state['projectRoot'] = fw_root
        ue_root = found.get('ueRoot')
        # 旧布局的 Forgeworks 目录同时是导出目录，迁移后不自动绑定 UE 目标
        if ue_root and os.path.realpath(os.path.join(ue_root, FW_DIR_NAME)) != os.path.realpath(fw_root):
            _state['ueProjectRoot'] = ue_root
        else:
            _state.pop('ueProjectRoot', None)
        save_state()
    with _watch_lock:
        fw_project.migrate_layout(fw_root)
        if _state.get('ueProjectRoot'):
            fw_project.migrate_ue_export(fw_root, _state['ueProjectRoot'])


PICK_PROMPT = '选择 Forgeworks 项目文件夹或 UE 导出目标'


def pick_folder():
    """弹系统原生的目录选择框。取消时返回 cancelled，而不是错误。"""
    try:
        if sys.platform == 'darwin':
            out = subprocess.run(
                ['osascript', '-e', 'POSIX path of (choose folder with prompt "%s")' % PICK_PROMPT],
                capture_output=True, text=True, timeout=300)
        elif os.name == 'nt':
            # Bridge 是后台进程，Windows 前台锁不允许它抢焦点；没有 owner 的
            # 对话框会被压在浏览器/编辑器后面，用户以为按钮没反应。用一个透明
            # 置顶 Form 当 owner，模态框才会浮到最前面。
            script = ("$ErrorActionPreference = 'Stop'; "
                      "Add-Type -AssemblyName System.Windows.Forms; "
                      "$owner = New-Object System.Windows.Forms.Form; "
                      "$owner.FormBorderStyle = 'None'; $owner.ShowInTaskbar = $false; "
                      "$owner.StartPosition = 'CenterScreen'; "
                      "$owner.Size = New-Object System.Drawing.Size(1,1); "
                      "$owner.TopMost = $true; $owner.Opacity = 0; "
                      "$owner.Show(); [System.Windows.Forms.Application]::DoEvents(); "
                      "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                      "$d.Description = '%s'; "
                      "if ($d.ShowDialog($owner) -eq 'OK') { $d.SelectedPath }; "
                      "$owner.Close()" % PICK_PROMPT)
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
        # Windows 上用户取消返回 0；非 0 说明 PowerShell 本身出错，不能再
        # 当作用户取消静默吞掉，否则界面上就是"点了没反应"。
        if os.name == 'nt':
            detail = (out.stderr or '').strip()
            return {'ok': False, 'error': detail or '目录选择器异常退出（%d）' % out.returncode}
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


UE_MESH_PATH = re.compile(r'^(/Game/Forgeworks/(?:[^/<>:"\\|?*\x00]+/)+)(SM_([A-Za-z0-9_]{1,64}))\.\2$')


def parse_ue_mesh_path(value):
    match = UE_MESH_PATH.fullmatch(str(value or ''))
    if not match:
        return None
    return {'id': match.group(3), 'contentPath': match.group(1).rstrip('/'), 'objectPath': match.group(0)}


def normalize_ue_report(asset_id, ue, manifest):
    if not re.fullmatch(r'[A-Za-z0-9_]+', str(asset_id or '')):
        raise ValueError('资产 ID 不合法')
    record = (manifest or {}).get('assets', {}).get(asset_id)
    if not record or record.get('kind') != 'machine':
        raise ValueError('manifest 中不存在该机器')
    expected_path = fw_project.content_path_for(record)
    legacy_path = '/Game/Forgeworks/Machines/%s' % asset_id
    if not isinstance(ue, dict) or ue.get('contentPath') not in (expected_path, legacy_path):
        raise ValueError('UE 内容目录与资产目录不匹配')
    assets = ue.get('assets') or {}
    mesh_path = assets.get('mesh')
    parsed = parse_ue_mesh_path(mesh_path)
    if (not parsed or parsed['id'] != asset_id
            or parsed['contentPath'] not in (expected_path, legacy_path)):
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
        'contentPath': parsed['contentPath'],
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
    manifest = load_manifest() or {}
    best = {}
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            parsed = parse_ue_mesh_path(row.get('objectPath'))
            bounds = row.get('bounds') or {}
            triangles = row.get('triangles')
            if not parsed or row.get('class') != 'StaticMesh' or isinstance(triangles, bool) or not isinstance(triangles, int) or triangles < 0:
                continue
            clean_bounds = {axis: float(bounds[axis]) for axis in ('x', 'y', 'z')}
            if any(not math.isfinite(value) or value < 0 for value in clean_bounds.values()):
                continue
            asset = {'id': parsed['id'], 'objectPath': parsed['objectPath'], 'class': 'StaticMesh',
                     'bounds': clean_bounds, 'triangles': triangles,
                     'materialSlots': [str(slot)[:128] for slot in row.get('materialSlots', [])[:256]],
                     'dependencies': [path for path in row.get('dependencies', [])[:512]
                                      if isinstance(path, str) and path.startswith('/Game/')][:512]}
            expected = fw_project.content_path_for((manifest.get('assets') or {}).get(parsed['id']) or {})
            legacy = parsed['contentPath'].startswith('/Game/Forgeworks/Machines/')
            score = 2 if expected and parsed['contentPath'] == expected else (0 if legacy else 1)
            if parsed['id'] not in best or score > best[parsed['id']][0]:
                best[parsed['id']] = (score, asset)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    assets = [asset for _, asset in sorted(best.values(), key=lambda item: item[1]['objectPath'])]
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


def archive_conflict(forgeworks_root, asset_id, source_dir, relative_path):
    relative_path = _safe_sync_relative(relative_path)
    stamp = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + ('%03d' % int((time.time() % 1) * 1000))
    conflict_id = stamp + '_' + str(time.monotonic_ns() % 1000000)
    conflict_root = _safe_join(forgeworks_root, SYNC_DIR, 'conflicts', asset_id, conflict_id)
    disk_source = _safe_join(forgeworks_root, source_dir, relative_path)
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
        source_dir = record.get('sourceDir')
        pending_paths = {entry.get('path') for entry in record.get('conflicts', []) if entry.get('status') == 'pending'}
        for role, tracked in _tracked_files(record):
            relative_path = _safe_sync_relative(tracked['path'])
            source = _safe_join(forgeworks_root, source_dir, relative_path) if source_dir else None
            if not source or not os.path.isfile(source):
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
                conflict = archive_conflict(forgeworks_root, asset_id, source_dir, relative_path)
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
    source_dir = record.get('sourceDir')
    if not source_dir:
        return {'ok': False, 'error': '资产目录记录缺失'}
    target = _safe_join(root, source_dir, _safe_sync_relative(conflict['path']))
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
    manifest_file = os.path.join(bound_root, SYNC_DIR, 'manifest.json')
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
    project_dir = bound_root
    manifest_file = os.path.join(project_dir, SYNC_DIR, 'manifest.json')
    with _manifest_lock:
        snapshot = read_json(manifest_file, None) or {}
    source_dir = (((snapshot.get('assets') or {}).get(asset_id)) or {}).get('sourceDir')
    if not source_dir:
        _mark_blender_error(job, '资产目录记录缺失')
        return
    try:
        target_dir = _safe_join(project_dir, source_dir)
        mesh_file = _safe_join(target_dir, mesh_path)
    except ValueError as error:
        _mark_blender_error(job, str(error))
        return
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
        try:
            abs_base = _safe_join(fw_dir(), base)
        except ValueError:
            rec['state'] = 'missing'
            report[aid] = 'missing'
            continue
        files = rec.get('files') or {}
        state, bad = 'exported', []
        for role, finfo in files.items():
            flist = finfo if isinstance(finfo, list) else [finfo]
            for fi in flist:
                try:
                    fp = _safe_join(abs_base, fi.get('path', ''))
                except ValueError:
                    bad.append('missing:' + fi.get('path', ''))
                    continue
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
    写入 _Source/<中文分类>/<中文名>/（manifest.sourceDir），更新 manifest。
    """
    bound_root = project_root()
    if not bound_root:
        return {'ok': False, 'error': '未绑定项目'}
    if kind not in fw_project.ASSET_KIND_DIRS:
        return {'ok': False, 'error': '未知资产类型: %s' % kind}
    if not re.match(r'^[A-Za-z0-9_]+$', asset_id or ''):
        return {'ok': False, 'error': '资产 ID 不合法（仅字母数字下划线）: %r' % asset_id}

    previous_manifest = load_manifest() or {}
    previous_record = (previous_manifest.get('assets') or {}).get(asset_id) or {}
    previous_kind = previous_record.get('kind')
    if previous_kind and previous_kind != kind:
        return {'ok': False,
                'error': '资产 ID 已被其他类型占用（%s → %s）: %s' % (previous_kind, kind, asset_id)}
    if kind == 'machine' and any(item.get('status') == 'pending' for item in previous_record.get('conflicts', [])):
        return {'ok': False, 'error': '该机器有待裁决的外部冲突，请先处理', 'conflict': True}
    try:
        rel_dir = fw_project.asset_source_dir(bound_root, kind, asset_id, meta or {}, previous_manifest)
        abs_dir = _safe_join(bound_root, rel_dir)
    except (OSError, ValueError) as error:
        return {'ok': False, 'error': str(error)}
    if kind == 'machine' and os.path.isdir(abs_dir):
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
                        conflict = archive_conflict(fw_dir(), asset_id, rel_dir, relative)
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
        previous_files = rec.get('files') if isinstance(rec.get('files'), dict) else {}
        merged_files = dict(previous_files)
        merged_files.update(written)
        previous_meta = rec.get('meta') if isinstance(rec.get('meta'), dict) else {}
        merged_meta = dict(previous_meta)
        merged_meta.update(meta_data)
        rec.update({
            'kind': kind,
            'state': 'exported',
            'sourceDir': rel_dir,
            'files': merged_files,
            'exportedAt': now_iso(),
            'exportedBy': 'bridge-%s' % BRIDGE_VERSION,
            'meta': merged_meta,
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
    _suppress_cors = False   # 终端路由按请求关闭 ACAO:*

    # ---- 静态文件：no-store（与 serve.py 同教训） ----
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        if not self._suppress_cors:
            self.send_header('Access-Control-Allow-Origin', '*')   # 允许 file:// 打开时调 API
        super().end_headers()

    def log_message(self, fmt, *args):
        if not os.environ.get('FW_BRIDGE_VERBOSE'):
            return
        text = (fmt % args) if args else fmt
        super().log_message('%s', re.sub(r'(token=)[^&\s]+', r'\1***', text))

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
                        'ueTarget': current_ue_target(), 'blender': blender_info()})
        elif route == 'projects':
            self._json({'ok': True, 'current': current_project(), 'ueTarget': current_ue_target(),
                        'recent': recent_projects()})
        elif route == 'project/info':
            mf = load_manifest()
            self._json({'ok': True, 'manifest': mf, 'root': project_root(),
                        'ueTarget': current_ue_target()})
        elif route == 'project/content':
            root = fw_dir()
            if not root:
                self._json({'ok': False, 'error': '未打开 Forgeworks 项目'}, 409)
            else:
                self._json({'ok': True, 'content': fw_project.load_content(root),
                            'revision': fw_project.content_revision(root), 'root': root})
        elif route == 'ue/manifest':
            target = ue_export_root()
            if not target:
                self._json({'ok': False, 'error': '尚未设置 UE 导出目标'}, 409)
            else:
                self._json({'ok': True, 'manifest': read_json(os.path.join(target, SYNC_DIR, 'manifest.json'), None)})
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
        elif route == 'materials/textures':
            query = self._query()
            try:
                style = fw_textures.style_id((query.get('style') or [''])[0])
                bound = fw_dir()
                catalog = fw_textures.load_catalog(bound, style)
                self._json({
                    'ok': True, 'styleId': style, 'items': catalog['items'],
                    'specs': fw_textures.specs_for_client(),
                    'providerReady': fw_textures.provider_ready(read_json(CONFIG_FILE, {}) or {}),
                    'dir': fw_textures.texture_dir(bound, style),
                })
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 409 if not fw_dir() else 400)
        elif route == 'materials/texture/file':
            query = self._query()
            try:
                path, content_type = fw_textures.texture_file(
                    fw_dir(), (query.get('style') or [''])[0], (query.get('key') or [''])[0])
                with open(path, 'rb') as stream:
                    data = stream.read()
            except (ValueError, TypeError, OSError) as error:
                self._json({'ok': False, 'error': str(error)}, 404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif route == 'providers':
            providers = provider_settings_view(read_json(CONFIG_FILE, {}) or {})
            self._json({'ok': True, 'providers': providers, 'configPath': CONFIG_FILE,
                        'remoteExecutionAvailable': any(row['configured'] for row in providers.values()),
                        'ccswitchAvailable': os.path.isfile(CCSWITCH_DB),
                        'ccswitch': ccswitch_candidates()})
        elif route.startswith('pipeline/graph/'):
            asset_id = route.rsplit('/', 1)[-1]
            kind = (self._query().get('kind') or ['machine'])[0]
            try:
                graph = fw_pipeline.load_graph(fw_dir(), asset_id, kind)
                self._json({'ok': True, 'graph': graph,
                            'archive': fw_pipeline.archive_info(fw_dir(), asset_id, kind)})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route.startswith('pipeline/output/'):
            parts = route.split('/')
            try:
                if self.headers.get('Origin') and not self._same_loopback_origin():
                    raise ValueError('流水线输出只允许本地同源访问')
                if len(parts) != 4 or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', parts[2]) or not re.fullmatch(r'(model|image)_[A-Za-z0-9_-]{4,140}\.(glb|png|jpg|webp)', parts[3]):
                    raise ValueError('输出路径非法')
                kind = (self._query().get('kind') or ['machine'])[0]
                path = fw_pipeline.resolve_output(fw_dir(), parts[2], kind, parts[3])
                if not path or os.path.getsize(path) > 150 * 1024 * 1024:
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
        elif route == 'terminal/status':
            self._suppress_cors = True
            if not self._loopback_host():
                self._json({'ok': False, 'error': '终端只允许本机访问'}, 403)
            else:
                self._json({'ok': True, **fw_terminal.terminal_availability(),
                            'sessions': _TERMINAL.status(), 'project': fw_dir(),
                            'claude': fw_terminal.claude_command(PORT)})
        elif route.startswith('terminal/stream/'):
            self._suppress_cors = True
            if not self._loopback_host():
                self._json({'ok': False, 'error': '终端只允许本机访问'}, 403)
                return
            token = (self._query().get('token') or [''])[0]
            session = _TERMINAL.get(route.rsplit('/', 1)[-1], token) if token else None
            if session is None:
                self._json({'ok': False, 'error': '终端会话不存在或令牌无效'}, 403)
            else:
                self._terminal_sse(session)
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
        try:
            path = _safe_join(fw_dir(), record.get('sourceDir'), asset_id + '_preview.png')
            with open(path, 'rb') as image_file:
                data = image_file.read()
        except (OSError, TypeError, ValueError):
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
            self._json(open_project((body or {}).get('path', '')))
        elif route == 'project/create':
            b = body or {}
            self._json(create_project(b.get('parent'), b.get('name')))
        elif route == 'project/ue-target':
            self._json(set_ue_target((body or {}).get('path', '')))
        elif route == 'project/publish':
            b = body or {}
            ids = b.get('ids')
            if ids is not None and not isinstance(ids, list):
                self._json({'ok': False, 'error': 'ids 必须是数组'}, 400)
            else:
                self._json(publish_to_ue(ids))
        elif route == 'project/content':
            root = fw_dir()
            if not root:
                self._json({'ok': False, 'error': '未打开 Forgeworks 项目'}, 409)
            else:
                b = body or {}
                source, client_id = _content_source(b)
                try:
                    result = save_content_checked(root, b.get('content'), b.get('baseRevision'),
                                                  source, client_id)
                    self._json(result, 409 if result.get('conflict') else 200)
                except ValueError as error:
                    self._json({'ok': False, 'error': str(error)}, 400)
        elif route in ('content/entity', 'content/entity/delete'):
            root = fw_dir()
            if not root:
                self._json({'ok': False, 'error': '未打开 Forgeworks 项目'}, 409)
            else:
                b = body or {}
                source, client_id = _content_source(b)
                try:
                    if route == 'content/entity':
                        result = upsert_entity(root, b.get('coll'), b.get('entity'),
                                               b.get('baseRevision'), source, client_id)
                    else:
                        result = delete_entity(root, b.get('coll'), b.get('id'),
                                               b.get('baseRevision'), source, client_id)
                    code = 409 if result.get('conflict') else (404 if result.get('notFound') else 200)
                    self._json(result, code)
                except ValueError as error:
                    self._json({'ok': False, 'error': str(error)}, 400)
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
                kind = b.get('kind') or 'machine'
                graph = fw_pipeline.save_client_graph(fw_dir(), b.get('assetId'), b.get('graph'), kind)
                push_event('pipeline.graph_saved', {'id': b.get('assetId'), 'revision': graph['revision']})
                self._json({'ok': True, 'graph': graph,
                            'archive': fw_pipeline.archive_info(fw_dir(), b.get('assetId'), kind)})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/graph/template':
            b = body or {}
            try:
                kind = b.get('kind') or 'machine'
                graph = fw_pipeline.starter_graph(b.get('assetId'), b.get('template', 'machine'))
                graph = fw_pipeline.save_graph(fw_dir(), b.get('assetId'), graph, kind)
                self._json({'ok': True, 'graph': graph,
                            'archive': fw_pipeline.archive_info(fw_dir(), b.get('assetId'), kind)})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/run':
            b = body or {}
            try:
                result = fw_pipeline.execute_local(fw_dir(), b.get('assetId'), b.get('nodeId'), bool(b.get('through')),
                                                   b.get('kind') or 'machine', find_blender(),
                                                   provider_config=read_json(CONFIG_FILE, {}) or {})
                push_event('pipeline.progress', {'id': b.get('assetId'), 'ran': result['ran']})
                self._json({'ok': True, **result})
            except (ValueError, TypeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'providers/save':
            if not self._same_loopback_origin():
                self._json({'ok': False, 'error': 'Provider 配置只允许 Forgeworks 本地同源页面修改'}, 403)
            else:
                try:
                    providers = save_provider_settings(body or {})
                    self._json({'ok': True, 'providers': providers, 'configPath': CONFIG_FILE,
                                'remoteExecutionAvailable': any(row['configured'] for row in providers.values()),
                                'ccswitchAvailable': os.path.isfile(CCSWITCH_DB),
                                'ccswitch': ccswitch_candidates()})
                except (ValueError, TypeError) as error:
                    self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'providers/ccswitch/import':
            if not self._same_loopback_origin():
                self._json({'ok': False, 'error': 'cc-switch 导入只允许 Forgeworks 本地同源页面操作'}, 403)
            else:
                try:
                    providers = import_ccswitch_provider((body or {}).get('id'))
                    self._json({'ok': True, 'providers': providers, 'configPath': CONFIG_FILE,
                                'remoteExecutionAvailable': any(row['configured'] for row in providers.values()),
                                'ccswitchAvailable': os.path.isfile(CCSWITCH_DB),
                                'ccswitch': ccswitch_candidates()})
                except (ValueError, TypeError) as error:
                    self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'providers/test':
            if not self._same_loopback_origin():
                self._json({'ok': False, 'error': '连通性测试只允许 Forgeworks 本地同源页面触发'}, 403)
            else:
                try:
                    result = fw_providers.test_connection(
                        read_json(CONFIG_FILE, {}) or {}, (body or {}).get('provider'))
                    self._json({'ok': True, 'result': result})
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
                kind = b.get('kind') or 'machine'
                graph = fw_pipeline.load_graph(fw_dir(), asset_id, kind)
                nodes, _ = fw_pipeline.validate_graph(graph)
                node = nodes.get(node_id)
                if not node or node.get('type') not in PROVIDER_NODE_TYPES:
                    raise ValueError('目标节点不是受支持的远程生成节点')
                incoming = [edge for edge in graph['edges'] if edge.get('to') == node_id]
                params = node.get('params') or {}
                if node['type'] == 'blueprint':
                    root = fw_pipeline.pipeline_root(fw_dir(), asset_id, kind)
                    spec_path = os.path.join(root, 'spec.json')
                    params_snapshot = copy.deepcopy(params)
                    scope = str(params.get('scope') or 'overall')
                    if scope not in ('overall', 'part'):
                        raise ValueError('SPEC_INVALID: scope 只能是 overall/part')
                    measure = None
                    role = ''
                    if scope == 'part':
                        if bool(params.get('specLocked')):
                            raise ValueError('SPEC_INVALID: specLocked 只适用于整体尺寸分析')
                        incoming_spec = _spec_from_incoming(fw_dir(), asset_id, kind,
                                                            nodes, incoming)
                        if not incoming_spec:
                            raise ValueError('SPEC_MISSING: 单件尺寸分析需要先连整体规格 spec 口')
                        role = str(params.get('role') or '').strip() or fw_spec.role_for_node(node_id)
                        if not role:
                            raise ValueError('SPEC_INVALID: 单件尺寸分析缺少部件角色')
                        if role not in incoming_spec['parts']:
                            raise ValueError('SPEC_INVALID: 规格中没有部件角色 %s' % role)
                        image_path = _upstream_image_path(fw_dir(), asset_id, kind,
                                                          incoming, nodes, label='单件三视图')
                        template = str(params.get('template') or 'excavator')
                        prompt_edge = next((edge for edge in incoming
                                            if edge.get('in') == 'text'), None)
                        prompt_text = ''
                        if prompt_edge:
                            source = nodes.get(prompt_edge['from']) or {}
                            prompt_text = str((((source.get('result') or {}).get('output') or {})
                                               .get('text')) or '')
                        raw, _meta = fw_providers.analyze_dimensions(
                            read_json(CONFIG_FILE, {}) or {}, image_path, [],
                            scope='part', role=role,
                            label=fw_spec.ROLE_LABELS.get(role, role),
                            overall_length=incoming_spec['overall']['lengthM'],
                            template=template,
                            prompt=prompt_text or str(params.get('prompt') or ''))
                        measure = fw_spec.measure_from_vision(raw, role, incoming_spec,
                                                              part_id=node_id, template=template)
                        digest = hashlib.sha1(json.dumps(
                            measure, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
                        task = {'taskId': 'measure_' + digest, 'provider': 'ark',
                                'state': 'success', 'requestType': 'measure',
                                'output': {'measure': measure, 'role': role}}
                    else:
                        if bool(params.get('specLocked')) and not os.path.isfile(spec_path):
                            raise ValueError('SPEC_MISSING: 已锁定规格但 spec.json 不存在')
                        if bool(params.get('specLocked')):
                            spec = fw_spec.read_spec(spec_path)
                            task = {'taskId': 'spec_locked', 'provider': 'ark',
                                    'state': 'success', 'requestType': 'blueprint',
                                    'output': {'spec': spec, 'specPath': 'spec.json'}}
                        else:
                            image_path = _upstream_image_path(fw_dir(), asset_id, kind,
                                                              incoming, nodes)
                            overall = params.get('overallLengthM')
                            template = str(params.get('template') or 'excavator')
                            prompt_edge = next((edge for edge in incoming
                                                if edge.get('in') == 'text'), None)
                            prompt_text = ''
                            if prompt_edge:
                                source = nodes.get(prompt_edge['from']) or {}
                                prompt_text = str((((source.get('result') or {}).get('output') or {})
                                                   .get('text')) or '')
                            raw, _meta = fw_providers.analyze_spec(
                                read_json(CONFIG_FILE, {}) or {}, image_path,
                                [{'name': part_role,
                                  'description': fw_spec.ROLE_LABELS.get(part_role, '')}
                                 for part_role in fw_spec.PART_ROLES],
                                prompt=prompt_text or str(params.get('prompt') or ''),
                                overall_length=overall, template=template)
                            spec = fw_spec.from_vision(raw, overall_length_m=overall,
                                                       template=template, asset_id=asset_id)
                            digest = hashlib.sha1(json.dumps(
                                spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
                            task = {'taskId': 'spec_' + digest, 'provider': 'ark',
                                    'state': 'success', 'requestType': 'blueprint',
                                    'output': {'spec': spec, 'specPath': 'spec.json'}}
                    duplicate_writers = [] if scope == 'part' else [
                        other['id'] for other in graph['nodes']
                        if other.get('type') == 'blueprint' and other['id'] != node_id
                        and str((other.get('params') or {}).get('scope') or 'overall') != 'part']

                    def apply_blueprint(latest):
                        latest_nodes, _ = fw_pipeline.validate_graph(latest)
                        latest_node = latest_nodes.get(node_id)
                        if not latest_node or latest_node.get('type') != 'blueprint':
                            raise ValueError('提交期间节点已被删除或修改')
                        if (latest_node.get('params') or {}) != params_snapshot:
                            raise ValueError('提交期间尺寸规格参数已修改，本次结果未写入，请重新提交')
                        state = latest_node.setdefault('result', {})
                        previous = state.get('providerTask')
                        if previous:
                            history = (state.get('history') or [])[-(PIPELINE_HISTORY_LIMIT - 1):]
                            state['history'] = history + [previous]
                        state['providerTask'] = task
                        if scope == 'part':
                            state['output'] = {'measure': measure, 'role': role, 'scope': 'part'}
                        else:
                            fw_spec.write_spec(spec_path, spec)
                            state['output'] = {'spec': spec, 'specPath': 'spec.json'}
                            if duplicate_writers:
                                warnings = list(state.get('warnings') or [])
                                warning = ('SPEC_WRITER_DUPLICATE: %s 也在写 spec.json，'
                                           '同一资产只应保留一个整体尺寸节点'
                                           % ', '.join(duplicate_writers))
                                if warning not in warnings:
                                    warnings.append(warning)
                                state['warnings'] = warnings
                        state['state'] = 'done'
                        state.pop('error', None)
                        return latest

                    result = fw_pipeline.update_graph(fw_dir(), asset_id, kind, apply_blueprint)
                    result_nodes, _ = fw_pipeline.validate_graph(result)
                    state = ((result_nodes.get(node_id) or {}).get('result') or {}).get('state')
                    push_event('pipeline.progress', {'id': asset_id, 'nodeId': node_id,
                                                     'state': state, 'taskId': task['taskId']})
                    self._json({'ok': True, 'graph': result, 'task': task,
                                'taskId': task['taskId'], 'state': state})
                    return
                prompt = ''
                input_task_id = None
                image_data = None
                part_name = ''
                spec_input = None
                role = ''
                ports = []
                if node['type'] in ('textToImage', 'partImage'):
                    prompt_edge = next((edge for edge in incoming if edge.get('in') == 'text'), None)
                    if prompt_edge:
                        source = nodes[prompt_edge['from']]
                        prompt = ((source.get('result') or {}).get('output') or {}).get('text') or ''
                        prompt = prompt or str((source.get('params') or {}).get('text') or '').strip()
                    if node['type'] == 'textToImage':
                        prompt = prompt or params.get('prompt', '')
                    else:
                        if not prompt:
                            raise ValueError('单件效果图缺少拆件说明：请先填写上游描述词节点')
                        part_name = _part_name_from_prompt(prompt) or str(node_id)
                        spec_input = _spec_from_incoming(fw_dir(), asset_id, kind,
                                                         nodes, incoming)
                        role = fw_spec.role_for_node(node_id, part_name)
                        part_spec = ((spec_input or {}).get('parts') or {}).get(role) or {}
                        if spec_input and not part_spec:
                            raise ValueError('PART_ROLE_MISSING: spec 中没有角色 %s'
                                             % (role or node_id))
                        ports = fw_spec.anchor_ports(part_spec) if part_spec else []
                        prompt = _part_image_prompt(prompt, part_spec)
                        image_data = _part_reference_image(fw_dir(), asset_id, kind, nodes, incoming)
                else:
                    prompt = str(params.get('prompt') or '')
                    image_edge = next((edge for edge in incoming if edge.get('in') == 'image'), None)
                    upstream_result = (nodes[image_edge['from']].get('result') or {}) if image_edge else {}
                    upstream_task = upstream_result.get('providerTask') or {}
                    input_task_id = upstream_task.get('taskId')
                    if not input_task_id:
                        input_task_id = params.get('inputTaskId')
                    image_data = _image_data_url(fw_dir(), asset_id, kind,
                                                 (upstream_task.get('output') or {}).get('imagePath'))
                    if node['type'] == 'partModel':
                        part_name = str((upstream_result.get('output') or {}).get('partName') or '')
                    if node['type'] == 'threeView':
                        prompt_edge = next((edge for edge in incoming
                                            if edge.get('in') == 'text'), None)
                        subject = ''
                        if prompt_edge:
                            source = nodes.get(prompt_edge['from']) or {}
                            subject = str((((source.get('result') or {}).get('output') or {})
                                           .get('text')) or '')
                        subject = subject or str(params.get('prompt') or '')
                        if not subject:
                            subject = fw_spec.ROLE_LABELS.get(
                                fw_spec.role_for_node(node_id), '')
                        prompt = _three_view_prompt(subject)
                        if not image_data:
                            raise ValueError('三视图需要参考图：请把概念图或单件图连到 image 口')
                node_type = node['type']
                provider_kind = {'partImage': 'textToImage', 'partModel': 'imageTo3D',
                                 'threeView': 'textToImage'}.get(node_type, node_type)
                # 慢速 Provider 调用必须在锁外完成，避免串行化整个资产的提交
                task = fw_providers.submit(read_json(CONFIG_FILE, {}) or {}, provider_kind, params,
                                           prompt, input_task_id, image_data, fallback=True)
                store_task_output(fw_dir(), asset_id, kind, node_type, task)
                applied = {}

                def apply_latest(latest):
                    latest_nodes, _ = fw_pipeline.validate_graph(latest)
                    latest_node = latest_nodes.get(node_id)
                    if not latest_node or latest_node.get('type') != node_type:
                        raise ValueError('提交期间节点已被删除或修改，任务未写入流水线：%s' % task['taskId'])
                    state = latest_node.setdefault('result', {})
                    previous_task = state.get('providerTask')
                    if previous_task:
                        history = (state.get('history') or [])[-(PIPELINE_HISTORY_LIMIT - 1):]
                        state['history'] = history + [previous_task]
                    if part_name:
                        extra = {'partName': part_name}
                        if spec_input:
                            extra.update(role=role, ports=ports)
                        state['output'] = dict(state.get('output') or {}, **extra)
                    state['providerTask'] = task
                    state['state'] = 'done' if task.get('state') == 'success' else 'queued'
                    state.pop('error', None)
                    applied['state'] = state['state']
                    return latest

                result = fw_pipeline.update_graph(fw_dir(), asset_id, kind, apply_latest)
                push_event('pipeline.progress', {'id': asset_id, 'nodeId': node_id,
                                                 'state': applied.get('state'), 'taskId': task['taskId']})
                self._json({'ok': True, 'graph': result, 'task': task, 'taskId': task['taskId'],
                            'state': applied.get('state')})
            except (ValueError, TypeError, RuntimeError, OSError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'pipeline/provider/poll':
            b = body or {}
            try:
                if not self._same_loopback_origin():
                    raise ValueError('Provider 任务仅允许 Forgeworks 本地同源页面查询')
                asset_id, node_id = b.get('assetId'), b.get('nodeId')
                kind = b.get('kind') or 'machine'
                graph = fw_pipeline.load_graph(fw_dir(), asset_id, kind)
                nodes, _ = fw_pipeline.validate_graph(graph)
                node = nodes.get(node_id)
                if not node or node.get('type') not in PROVIDER_NODE_TYPES:
                    raise ValueError('目标节点不是受支持的远程生成节点')
                task = dict((node.get('result') or {}).get('providerTask') or {})
                node_type = node['type']
                # 蓝图提交是同步的，没有远程任务可轮询
                if node_type == 'blueprint':
                    self._json({'ok': True, 'graph': graph, 'task': task})
                    return
                task_id = task.get('taskId')
                if not task_id:
                    raise ValueError('没有可轮询的 Provider 任务')
                # 慢速轮询/模型下载也放在锁外，只有最终写图时再读取最新图
                result = fw_providers.poll(read_json(CONFIG_FILE, {}) or {}, task)
                state = result.get('status')
                if state not in ('queued', 'running', 'success', 'failed', 'cancelled', 'banned'):
                    raise ValueError('Provider 返回了未知任务状态')
                task.update({'state': state, 'progress': max(0, min(100, int(result.get('progress') or 0))),
                             'creditsConsumed': result.get('credits_consumed'),
                             'error': str(result.get('error_message') or '')[:300]})
                output = result.get('output') or {}
                node_state = 'done' if state == 'success' else ('failed' if state in ('failed', 'cancelled', 'banned') else state)
                if state == 'success' and node_type in ('textToImage', 'partImage', 'threeView'):
                    task['output'] = {'generated_image_url': output.get('generated_image_url')}
                    store_task_output(fw_dir(), asset_id, kind, node_type, task)
                if state == 'success' and node_type in ('imageTo3D', 'partModel') and output.get('model_url'):
                    data = fw_providers.download_model(output.get('model_url'))
                    output_dir = os.path.join(fw_pipeline.pipeline_root(fw_dir(), asset_id, kind), 'outputs')
                    os.makedirs(output_dir, exist_ok=True)
                    filename = 'model_' + task_id + '.glb'
                    write_bytes_atomic(os.path.join(output_dir, filename), data)
                    task['output'] = {'modelPath': 'outputs/' + filename, 'size': len(data)}
                applied = {}

                def apply_latest(latest):
                    latest_nodes, _ = fw_pipeline.validate_graph(latest)
                    latest_node = latest_nodes.get(node_id)
                    if not latest_node or latest_node.get('type') != node_type:
                        raise ValueError('轮询期间节点已被删除或修改')
                    current_task = (latest_node.get('result') or {}).get('providerTask') or {}
                    if current_task.get('taskId') != task_id:
                        applied['stale'] = current_task
                        return latest
                    latest_node.setdefault('result', {})['state'] = node_state
                    if state == 'success':
                        latest_node['result'].pop('error', None)
                    latest_node['result']['providerTask'] = task
                    applied['task'] = task
                    return latest

                result_graph = fw_pipeline.update_graph(fw_dir(), asset_id, kind, apply_latest)
                if 'stale' in applied:
                    self._json({'ok': True, 'graph': result_graph, 'task': applied.get('stale') or {},
                                'stale': True})
                else:
                    push_event('pipeline.progress', {'id': asset_id, 'nodeId': node_id, 'state': state,
                                                     'progress': task.get('progress')})
                    self._json({'ok': True, 'graph': result_graph, 'task': task})
            except (ValueError, TypeError, RuntimeError, OSError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'materials/texture/submit':
            b = body or {}
            try:
                if not self._same_loopback_origin():
                    raise ValueError('贴图生成仅允许 Forgeworks 本地同源页面发起')
                if b.get('confirmRemote') is not True:
                    raise ValueError('需要用户明确确认可能产生 Provider 费用')
                result = fw_textures.submit_many(
                    fw_providers, read_json(CONFIG_FILE, {}) or {}, fw_dir(),
                    b.get('styleId'), b.get('keys'), b.get('styleHint') or '',
                    b.get('size') or '1K', bool(b.get('force')))
                push_event('texture.progress', {'styleId': b.get('styleId'), 'submitted': result['submitted']})
                self._json({'ok': True, **result})
            except (ValueError, TypeError, RuntimeError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route == 'materials/texture/poll':
            b = body or {}
            try:
                if not self._same_loopback_origin():
                    raise ValueError('贴图任务仅允许 Forgeworks 本地同源页面查询')
                catalog, item = fw_textures.poll_one(
                    fw_providers, read_json(CONFIG_FILE, {}) or {}, fw_dir(),
                    b.get('styleId'), b.get('key'))
                push_event('texture.progress', {'styleId': b.get('styleId'), 'key': b.get('key'),
                                                'state': item.get('state'), 'progress': item.get('progress')})
                self._json({'ok': True, 'catalog': catalog, 'item': item})
            except (ValueError, TypeError, RuntimeError, OSError) as error:
                self._json({'ok': False, 'error': str(error)}, 400)
        elif route.startswith('terminal/'):
            self._suppress_cors = True
            self._route_terminal(route, body or {})
        else:
            self._json({'ok': False, 'error': 'unknown route: %s' % route}, 404)

    # ---- terminal ----
    def _route_terminal(self, route, body):
        if not self._same_loopback_origin():
            self._json({'ok': False, 'error': '终端只允许本机同源页面调用'}, 403)
            return
        if route == 'terminal/start':
            try:
                session = _TERMINAL.start(fw_dir(), body.get('cols'), body.get('rows'))
            except fw_terminal.TerminalLimit as error:
                self._json({'ok': False, 'error': str(error)}, 429)
            except fw_terminal.TerminalUnavailable as error:
                self._json({'ok': False, 'error': str(error)}, 501)
            except fw_terminal.TerminalError as error:
                self._json({'ok': False, 'error': str(error)}, 409)
            except OSError as error:
                self._json({'ok': False, 'error': '无法启动终端：%s' % error}, 500)
            else:
                self._json({'ok': True, 'id': session.id, 'token': session.token,
                            'pid': session.pid, 'cwd': session.cwd,
                            'cols': session.cols, 'rows': session.rows})
            return
        session = _TERMINAL.get(body.get('sessionId'), body.get('token'))
        if session is None:
            self._json({'ok': False, 'error': '终端会话不存在或令牌无效'}, 403)
            return
        if route == 'terminal/input':
            try:
                data = base64.b64decode(str(body.get('data') or ''), validate=True)
            except (ValueError, TypeError):
                self._json({'ok': False, 'error': '输入数据不是合法 base64'}, 400)
                return
            if len(data) > fw_terminal.MAX_INPUT_BYTES:
                self._json({'ok': False, 'error': '单次输入过大'}, 413)
                return
            session.write(data)
            self._json({'ok': True})
        elif route == 'terminal/resize':
            session.resize(body.get('cols'), body.get('rows'))
            self._json({'ok': True, 'cols': session.cols, 'rows': session.rows})
        elif route == 'terminal/stop':
            _TERMINAL.stop(session.id)
            self._json({'ok': True})
        else:
            self._json({'ok': False, 'error': 'unknown route: %s' % route}, 404)

    def _terminal_sse(self, session):
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
        except OSError:
            return
        client = session.add_client()
        try:
            self._sse_event('ready', {'reset': True, 'id': session.id,
                                      'cols': session.cols, 'rows': session.rows})
            while True:
                try:
                    chunk = client.get(timeout=15)
                except queue.Empty:
                    if not session.has_client(client):
                        break
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                    continue
                if chunk is None:
                    self._sse_event('exit', {'code': session.exit_code})
                    break
                self._sse_event('output', {'b64': base64.b64encode(chunk).decode('ascii')})
        except OSError:
            pass
        finally:
            session.drop_client(client)

    def _sse_event(self, name, obj):
        payload = json.dumps(obj, ensure_ascii=False)
        self.wfile.write(('event: %s\ndata: %s\n\n' % (name, payload)).encode('utf-8'))
        self.wfile.flush()

    # ---- helpers ----
    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _read_body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n <= 0 or n > 64 * 1024 * 1024:
                return {}
            return json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return {}

    def _loopback_host(self):
        port = self.server.server_address[1]
        host = (self.headers.get('Host') or '').lower()
        return host in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

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
    normalize_bound_project()
    start_source_watcher()
    httpd = Bridge(('127.0.0.1', PORT), BridgeHandler)
    print('Forgeworks Bridge v%s' % BRIDGE_VERSION)
    print('  http://127.0.0.1:%d/        （界面）' % PORT)
    print('  http://127.0.0.1:%d/api/status（状态）' % PORT)
    bl = blender_info()
    print('  Blender: %s' % (bl['path'] or '未找到（缩略图/校验功能降级）'))
    proj = project_root()
    print('  项目: %s' % (proj or '未打开（在界面「同步」页新建/打开项目）'))
    ue_target = ue_project_root()
    print('  UE 导出目标: %s' % (ue_target or '未设置'))
    print('  Ctrl+C 停止')

    def terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
    finally:
        _TERMINAL.shutdown_all()
        httpd.server_close()


if __name__ == '__main__':
    main()
