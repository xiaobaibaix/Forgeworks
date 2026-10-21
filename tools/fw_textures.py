"""AI-generated material detail textures, cached per project style."""

import hashlib
import json
import os
import re
import time

TEXTURE_SPECS = {
    'concrete': {
        'name': '混凝土',
        'prompt': 'weathered concrete surface, fine aggregate grain, small pores, subtle stains',
    },
    'steel': {
        'name': '钢材',
        'prompt': 'rolled steel plate, fine horizontal brushing marks, tiny scuffs',
    },
    'steelDark': {
        'name': '暗钢',
        'prompt': 'oxidized dark steel, fine pitting, faint oxide blotches',
    },
    'steelLite': {
        'name': '亮钢',
        'prompt': 'polished light steel, faint linear scratches, very subtle streaks',
    },
    'glass': {
        'name': '玻璃',
        'prompt': 'flat glass surface, faint smudges and thin streaks, low contrast',
    },
    'rust': {
        'name': '锈铁',
        'prompt': 'rusted iron, flaking oxidation patches, pitting and rough crust',
    },
    'clean': {
        'name': '洁净白',
        'prompt': 'clean painted metal panel, faint surface noise, one subtle panel seam',
    },
    'ceramic': {
        'name': '陶瓷',
        'prompt': 'glazed ceramic surface, fine crackle glaze, subtle speckles',
    },
}

PROMPT_TAIL = ('seamless tileable PBR albedo texture, neutral grey values between 70 and 90 percent, '
               'flat even lighting, no baked shadows, no highlights, no color cast, no text, no watermark, '
               'square format, top-down view')

STYLE_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')
ASSET_KEY_RE = re.compile(r'[A-Za-z0-9_]{1,64}')
MAX_TEXTURE_BYTES = 20 * 1024 * 1024
CONTENT_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}


def style_id(value):
    if not isinstance(value, str) or not STYLE_ID_RE.fullmatch(value):
        raise ValueError('风格 ID 非法')
    return value


def asset_key(value):
    if not isinstance(value, str) or value not in TEXTURE_SPECS:
        raise ValueError('不支持的材质贴图：%s' % (value,))
    return value


def texture_dir(fw_root, style):
    if not fw_root:
        raise ValueError('未绑定项目')
    return os.path.join(fw_root, '_Source', 'Materials', style_id(style))


def catalog_path(fw_root, style):
    return os.path.join(texture_dir(fw_root, style), 'textures.json')


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def load_catalog(fw_root, style):
    style = style_id(style)
    try:
        with open(catalog_path(fw_root, style), encoding='utf-8') as stream:
            catalog = json.load(stream)
    except FileNotFoundError:
        catalog = {}
    except (OSError, ValueError):
        raise ValueError('贴图目录损坏，请检查 textures.json')
    if not isinstance(catalog, dict):
        raise ValueError('贴图目录格式无效')
    items = catalog.get('items')
    items = items if isinstance(items, dict) else {}
    catalog = {
        'version': 1,
        'styleId': style,
        'items': {k: v for k, v in items.items() if k in TEXTURE_SPECS and isinstance(v, dict)},
    }
    for key, item in catalog['items'].items():
        if item.get('state') == 'ready':
            path = os.path.join(texture_dir(fw_root, style), os.path.basename(str(item.get('file') or '')))
            if not os.path.isfile(path):
                item.update(state='missing', file=None)
    return catalog


def save_catalog(fw_root, style, catalog):
    path = catalog_path(fw_root, style)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    catalog = dict(catalog, version=1, styleId=style, updatedAt=_now())
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(catalog, stream, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return catalog


def build_prompt(key, style_hint=''):
    spec = TEXTURE_SPECS[asset_key(key)]
    hint = str(style_hint or '').strip()[:400]
    parts = ['project art direction: ' + hint] if hint else []
    parts.extend([spec['prompt'], PROMPT_TAIL])
    return ', '.join(parts)[:1200]


def submit_many(providers, config, fw_root, style, keys, style_hint='', size='1K', force=False):
    if not isinstance(keys, list) or not keys or len(keys) > len(TEXTURE_SPECS):
        raise ValueError('贴图清单非法')
    if not isinstance(size, str) or size not in ('1K', '2K', '4K'):
        raise ValueError('贴图尺寸非法')
    catalog = load_catalog(fw_root, style)
    submitted, skipped = [], []
    for raw in keys:
        key = asset_key(raw)
        current = catalog['items'].get(key) or {}
        if current.get('state') in ('queued', 'running'):
            skipped.append({'key': key, 'reason': '任务进行中'})
            continue
        if current.get('state') == 'ready' and not force:
            skipped.append({'key': key, 'reason': '已生成'})
            continue
        prompt = build_prompt(key, style_hint)
        task = providers.submit(config, 'textToImage', {'model': 'seedream_v5', 'size': size}, prompt)
        catalog['items'][key] = {
            'state': 'queued', 'taskId': task['taskId'], 'provider': task.get('provider', 'tripo'),
            'prompt': prompt, 'size': size, 'submittedAt': _now(), 'updatedAt': _now(),
        }
        submitted.append(key)
    catalog = save_catalog(fw_root, style, catalog)
    return {'catalog': catalog, 'submitted': submitted, 'skipped': skipped}


def poll_one(providers, config, fw_root, style, key):
    key = asset_key(key)
    catalog = load_catalog(fw_root, style)
    item = catalog['items'].get(key)
    if not item or not item.get('taskId'):
        raise ValueError('该材质还没有生成任务')
    if item.get('state') in ('queued', 'running'):
        result = providers.poll(config, item['taskId'])
        state = result.get('status')
        if state not in ('queued', 'running', 'success', 'failed', 'cancelled', 'banned'):
            raise ValueError('Provider 返回了未知任务状态')
        item['progress'] = max(0, min(100, int(result.get('progress') or 0)))
        item['updatedAt'] = _now()
        if state == 'success':
            output = result.get('output') or {}
            data, extension = providers.download_image(output.get('generated_image_url'))
            if len(data) > MAX_TEXTURE_BYTES:
                raise ValueError('贴图超过 20 MB 限制')
            directory = texture_dir(fw_root, style)
            os.makedirs(directory, exist_ok=True)
            filename = '%s.%s' % (key, extension)
            path = os.path.join(directory, filename)
            tmp = path + '.tmp'
            with open(tmp, 'wb') as stream:
                stream.write(data)
            os.replace(tmp, path)
            item.update(state='ready', file=filename, size=len(data),
                        sha1=hashlib.sha1(data).hexdigest(), updatedAt=_now())
            item.pop('error', None)
        elif state in ('failed', 'cancelled', 'banned'):
            item.update(state='failed', error=str(result.get('error_message') or state)[:300], updatedAt=_now())
        else:
            item['state'] = state
        catalog = save_catalog(fw_root, style, catalog)
    return catalog, item


def texture_file(fw_root, style, key):
    key = asset_key(key)
    catalog = load_catalog(fw_root, style)
    item = catalog['items'].get(key) or {}
    filename = os.path.basename(str(item.get('file') or ''))
    if item.get('state') != 'ready' or not filename:
        raise ValueError('贴图尚未生成')
    path = os.path.join(texture_dir(fw_root, style), filename)
    if not os.path.isfile(path) or os.path.getsize(path) > MAX_TEXTURE_BYTES:
        raise ValueError('贴图文件不存在或过大')
    extension = filename.rsplit('.', 1)[-1].lower()
    content_type = CONTENT_TYPES.get(extension)
    if not content_type:
        raise ValueError('贴图格式不支持')
    return path, content_type


def provider_ready(config):
    providers = config.get('providers') if isinstance(config, dict) else None
    tripo = providers.get('tripo') if isinstance(providers, dict) else None
    return bool(isinstance(tripo, dict) and str(tripo.get('api_key') or '').strip())


def specs_for_client():
    return [{'key': key, 'name': spec['name'], 'prompt': spec['prompt']}
            for key, spec in TEXTURE_SPECS.items()]
