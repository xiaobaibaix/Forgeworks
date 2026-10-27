"""Server-side provider adapters; no provider request runs without an explicit run action."""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from io import BytesIO
from urllib.parse import urlparse

TRIPO_BASE = 'https://openapi.tripo3d.ai/v3'
TRIPO_DOWNLOAD_HOSTS = {'cdn.tripo3d.ai'}
ARK_BASE = 'https://ark.cn-beijing.volces.com/api/v3'
ARK_DOWNLOAD_SUFFIX = '.volces.com'
ARK_IMAGE_MODEL = 'doubao-seedream-5-0-pro-260628'
ARK_3D_MODEL = 'doubao-seed3d-2-0-260328'
# 组装前的整体效果图分析；可在 bridge_config.json 的 providers.ark.vision_model 覆盖。
ARK_VISION_MODEL = 'doubao-seed-1-6-vision-250815'
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MODEL_BYTES = 150 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
VISION_MAX_IMAGE_BYTES = 8 * 1024 * 1024
PROVIDERS = ('tripo', 'ark')


def _request(url, api_key, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={
        'Authorization': 'Bearer ' + api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as error:
        raw = error.read(MAX_JSON_BYTES)
        try:
            parsed = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            parsed = {}
        if not isinstance(parsed, dict) or not parsed.get('message'):
            raise RuntimeError('Provider HTTP %s' % error.code) from None
        detail = 'Tripo %s（HTTP %s）：%s' % (parsed.get('code') or '', error.code, parsed['message'])
        if parsed.get('suggestion'):
            detail += '。%s' % parsed['suggestion']
        raise RuntimeError(detail[:400]) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError('Provider 请求失败：%s' % type(error).__name__) from None
    if len(body) > MAX_JSON_BYTES:
        raise RuntimeError('Provider 响应超过大小限制')
    try:
        result = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise RuntimeError('Provider 返回了无效 JSON') from None
    if not isinstance(result, dict) or result.get('code') != 0 or not isinstance(result.get('data'), dict):
        raise RuntimeError('Provider 返回了失败或格式无效的响应')
    return result['data']


def _providers(config):
    return config.get('providers') if isinstance(config, dict) and isinstance(config.get('providers'), dict) else {}


def _provider_config(config, name):
    value = _providers(config).get(name)
    return value if isinstance(value, dict) else {}


def _provider_key(config, name):
    value = _provider_config(config, name).get('api_key')
    return value.strip() if isinstance(value, str) and value.strip() else ''


def _key(config, name='tripo'):
    value = _provider_key(config, name)
    if not value:
        raise ValueError(('Tripo' if name == 'tripo' else 'Ark') + ' API key 未配置')
    return value


def test_connection(config, name):
    """用只读接口做鉴权探测，不产生计费任务。"""
    provider = str(name or '').strip().lower()
    if provider not in PROVIDERS:
        raise ValueError('不支持的 Provider：%s' % (name,))
    key = _provider_key(config, provider)
    if not key:
        return {'provider': provider, 'configured': False, 'ok': False, 'error': '未配置 API Key'}
    url = (_ark_base(config) + '/models' if provider == 'ark'
           else TRIPO_BASE + '/tasks/00000000-0000-0000-0000-000000000000')
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read(64)
            status = response.status
    except urllib.error.HTTPError as error:
        latency = int((time.time() - started) * 1000)
        if provider == 'tripo' and error.code == 404:
            # Tripo v3 没有只读账户接口；探测一个不存在的任务，404 说明鉴权已通过。
            return {'provider': provider, 'configured': True, 'ok': True,
                    'status': error.code, 'latencyMs': latency}
        message = ('API Key 无效或无权限' if error.code in (401, 403)
                   else 'Provider HTTP %s' % error.code)
        return {'provider': provider, 'configured': True, 'ok': False,
                'status': error.code, 'latencyMs': latency, 'error': message}
    except (urllib.error.URLError, TimeoutError) as error:
        return {'provider': provider, 'configured': True, 'ok': False,
                'error': '连接失败：%s' % type(error).__name__}
    return {'provider': provider, 'configured': True, 'ok': True,
            'status': status, 'latencyMs': int((time.time() - started) * 1000)}


def _pick_provider(config, params, fallback=False):
    wanted = str(params.get('provider') or '').strip().lower()
    configured = [name for name in PROVIDERS if _provider_key(config, name)]
    if wanted in configured:
        return wanted
    if fallback:
        return configured[0] if configured else (wanted if wanted in PROVIDERS else 'tripo')
    return wanted if wanted else 'tripo'


def _bool_param(params, key, default=False):
    value = params.get(key)
    return value if isinstance(value, bool) else default


def _int_param(params, key, low=None, high=None):
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def _choice_param(params, key, allowed, default):
    value = str(params.get(key) or '').strip().lower()
    return value if value in allowed else default


def _ark_base(config):
    base = str(_provider_config(config, 'ark').get('endpoint') or ARK_BASE).strip().rstrip('/')
    if base.endswith('/api/compatible'):
        base = base[:-len('/api/compatible')] + '/api/v3'
    elif not base.endswith('/api/v3'):
        base = base + '/api/v3'
    return base


def _ark_error(body, status):
    error = body.get('error') if isinstance(body, dict) else None
    if isinstance(error, dict):
        code = str(error.get('code') or 'ArkError')
        message = str(error.get('message') or '')[:300]
        return 'Ark %s（HTTP %s）：%s' % (code, status, message)
    return 'Ark HTTP %s' % status


def _ark_request(config, path, payload=None, timeout=60):
    key = _key(config, 'ark')
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(_ark_base(config) + path, data=data, headers={
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as error:
        raw = error.read(MAX_JSON_BYTES)
        try:
            parsed = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            parsed = {}
        raise RuntimeError(_ark_error(parsed, error.code)) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError('Ark 请求失败：%s' % type(error).__name__) from None
    if len(body) > MAX_JSON_BYTES:
        raise RuntimeError('Ark 响应超过大小限制')
    try:
        result = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise RuntimeError('Ark 返回了无效 JSON') from None
    if not isinstance(result, dict):
        raise RuntimeError('Ark 返回了格式无效的响应')
    if result.get('error'):
        raise RuntimeError(_ark_error(result, 200))
    return result


def _allowed_download_host(host):
    return bool(host) and (host in TRIPO_DOWNLOAD_HOSTS or host == ARK_DOWNLOAD_SUFFIX[1:]
                           or host.endswith(ARK_DOWNLOAD_SUFFIX))


def _check_remote_url(url, label):
    parsed = urlparse(url or '')
    if parsed.scheme != 'https' or not _allowed_download_host(parsed.hostname) or parsed.username or parsed.password:
        raise ValueError('%s域名不在允许列表' % label)
    return url


def _vision_image_uri(path):
    extension = os.path.splitext(path)[1].lower()
    mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.webp': 'image/webp'}.get(extension)
    if not mime:
        raise ValueError('整体效果图只支持 PNG/JPEG/WebP')
    try:
        size = os.path.getsize(path)
    except OSError:
        raise ValueError('整体效果图文件不存在') from None
    if size > VISION_MAX_IMAGE_BYTES:
        raise ValueError('整体效果图超过 8 MB，无法用于视觉分析')
    try:
        with open(path, 'rb') as stream:
            data = stream.read()
    except OSError as error:
        raise ValueError('整体效果图读取失败：%s' % error) from None
    return 'data:%s;base64,%s' % (mime, base64.b64encode(data).decode('ascii'))


def _message_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(str(item.get('text') or '') for item in value if isinstance(item, dict))
    return ''


def _json_object(text):
    text = str(text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```[A-Za-z0-9_-]*\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        value = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        raise RuntimeError('视觉分析没有返回有效 JSON') from None
    if not isinstance(value, dict):
        raise RuntimeError('视觉分析返回的不是 JSON 对象')
    return value


def analyze_layout(config, image_path, parts, prompt='', model=''):
    """让 Ark 视觉模型看整体效果图，返回可指导本地布局的少量提示。

    只在用户主动运行组装节点时调用；未配置密钥或模型不支持图片时会抛错，
    由调用方退回启发式布局。
    """
    name = str(model or _provider_config(config, 'ark').get('vision_model') or ARK_VISION_MODEL).strip()
    if not name:
        raise ValueError('未配置 Ark 视觉模型')
    image_uri = _vision_image_uri(image_path)
    part_lines = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        title = str(part.get('name') or part.get('id') or '部件').strip()
        description = str(part.get('description') or '').strip()
        part_lines.append('- %s%s' % (title, ('：' + description[:160]) if description else ''))
    if not part_lines:
        raise ValueError('没有可用于视觉分析的部件')
    instruction = str(prompt or '').strip()[:1200]
    user_text = (
        '参考图是一台机械的整体效果图。已经拆出的部件：\n%s\n'
        '组装说明：%s\n'
        '请只依据参考图判断这些已有部件的相对比例与驾驶室位置：\n'
        '1. 接地件（履带或车轮）长度 ÷ 车身长度；\n'
        '2. 动臂长度 ÷ 车身长度；\n'
        '3. 铲斗宽度 ÷ 车身宽度；\n'
        '4. 驾驶室在整机左侧还是右侧（机头朝 +X 时 +Y 为左侧）。\n'
        '只输出 JSON，不要解释，字段：'
        '{"groundLengthRatio":1.2,"boomLengthRatio":1.15,'
        '"bucketWidthRatio":0.6,"cabSide":"left","notes":"一句话"}。\n'
        '比例是倍数，保留两位小数；图中看不出的项给合理估计。'
        % ('\n'.join(part_lines[:30]), instruction or '（无）'))
    body = {
        'model': name,
        'messages': [
            {'role': 'system',
             'content': '你是机械装配分析师。只能依据参考图判断已有部件的相对比例和位置，'
                        '不要新增部件，不要改变结构，只输出严格 JSON。'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': user_text},
                {'type': 'image_url', 'image_url': {'url': image_uri}},
            ]},
        ],
        'temperature': 0.2,
        'max_tokens': 600,
    }
    result = _ark_request(config, '/chat/completions', body, timeout=120)
    choices = result.get('choices')
    message = ((choices or [{}])[0] or {}).get('message') if isinstance(choices, list) else None
    content = _message_text((message or {}).get('content'))
    raw = _json_object(content)
    hints = {key: raw.get(key) for key in
             ('groundLengthRatio', 'boomLengthRatio', 'bucketWidthRatio', 'cabSide')
             if raw.get(key) is not None}
    if not hints:
        raise RuntimeError('视觉分析没有给出可用字段')
    return hints, {'model': name, 'notes': str(raw.get('notes') or '').strip()[:500]}


def analyze_dimensions(config, image_path, parts, scope='overall', role='', label='',
                       overall_length=0.0, template='excavator', prompt='', model=''):
    """让 Ark 视觉模型把三视图/效果图整理成整机 spec 或单件 measure 候选 JSON。"""
    scope = str(scope or 'overall')
    if scope not in ('overall', 'part'):
        raise ValueError('SPEC_INVALID: scope 只能是 overall/part')
    name = str(model or _provider_config(config, 'ark').get('vision_model')
               or ARK_VISION_MODEL).strip()
    if not name:
        raise ValueError('未配置 Ark 视觉模型')
    _key(config, 'ark')
    image_uri = _vision_image_uri(image_path)
    try:
        anchor = float(overall_length or 0)
    except (TypeError, ValueError):
        anchor = 0.0
    instruction = str(prompt or '').strip()[:1200]
    max_tokens = 1800
    if scope == 'part':
        role = str(role or '').strip()
        if not role:
            raise ValueError('SPEC_INVALID: 单件尺寸分析缺少部件角色')
        if anchor <= 0:
            raise ValueError('SPEC_UNANCHORED: 单件尺寸分析需要整机长度锚')
        label = str(label or '').strip() or role
        user_text = (
            '参考图是「%s」（角色 %s）的正交三视图（前|侧|顶），三格同比例。\n'
            '整机长度锚：%.3f 米；机型模板：%s。\n'
            '额外说明：%s\n'
            '请只输出 JSON，不要解释。字段：\n'
            '{"parts":{"%s":{"sizeM":[4.0,1.7,0.7],"forward":"+X","confidence":0.7}},'
            '"notes":["一句话"]}\n'
            'sizeM 是 [X,Y,Z] 米；forward 只能是 +X/-X/+Y/-Y/+Z/-Z；'
            '只输出这一个部件，不要输出端口、连接或其它部件。看不出的尺寸给合理估计。'
            % (label, role, anchor, template, instruction or '（无）', role))
        max_tokens = 600
    else:
        part_lines = []
        for part in parts or []:
            if not isinstance(part, dict):
                continue
            title = str(part.get('name') or part.get('id') or '部件').strip()
            description = str(part.get('description') or '').strip()
            part_lines.append('- %s%s' % (title, ('：' + description[:160]) if description else ''))
        if not part_lines:
            raise ValueError('没有可用于尺寸规格的部件')
        anchor_text = ('整机长度锚：%.3f 米' % anchor) if anchor > 0 else '整机长度锚：未提供'
        user_text = (
            '参考图是一台机械的整体效果图（优先按正交三视图理解比例）。已经拆出的部件：\n%s\n'
            '机型模板：%s；%s。\n'
            '额外说明：%s\n'
            '请只输出 JSON，不要解释。字段：\n'
            '{"overall":{"lengthM":7.2,"widthM":2.4,"heightM":3.1},'
            '"assembly":{"rootRole":"body"},'
            '"parts":{"bucket":{"sizeM":[1.15,1.2,1.05],"forward":"+X","confidence":0.7,'
            '"ports":[{"id":"ear_pin","type":"pin","anchor":[0.02,0.5,0.78],'
            '"axis":[-1,0,0],"normal":[0,0,1],"radiusM":0.06}]}},'
            '"connections":[{"id":"c_bucket_boom","a":"bucket:ear_pin",'
            '"b":"boom:tip_pin","joint":"pin"}],"notes":["一句话"]}\n'
            '角色只能用 body/track/wheel/boom/bucket/cab/roof/door/window；'
            'sizeM 是 [X,Y,Z] 米；anchor 是 [0,1] 包围盒归一化坐标；'
            'forward 只能是 +X/-X/+Y/-Y/+Z/-Z。看不出的尺寸给合理估计。'
            % ('\n'.join(part_lines[:30]), template, anchor_text, instruction or '（无）'))
    body = {
        'model': name,
        'messages': [
            {'role': 'system',
             'content': '你是机械尺寸规格分析师。只依据参考图和已列出的部件输出严格 JSON，'
                        '不要新增未列出的部件，不要解释。'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': user_text},
                {'type': 'image_url', 'image_url': {'url': image_uri}},
            ]},
        ],
        'temperature': 0.2,
        'max_tokens': max_tokens,
    }
    result = _ark_request(config, '/chat/completions', body, timeout=120)
    choices = result.get('choices')
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    if first.get('finish_reason') == 'length':
        raise RuntimeError('视觉分析输出被截断，请减少部件或重试')
    message = first.get('message')
    content = _message_text(message.get('content') if isinstance(message, dict) else '')
    raw = _json_object(content)
    notes = raw.get('notes')
    if isinstance(notes, list):
        notes = '; '.join(str(item) for item in notes)
    return raw, {'model': name, 'notes': str(notes or '')[:500]}


def analyze_spec(config, image_path, parts, prompt='', model='',
                 overall_length=0.0, template='excavator'):
    return analyze_dimensions(config, image_path, parts, scope='overall', prompt=prompt,
                              model=model, overall_length=overall_length, template=template)


def submit(config, kind, params, prompt='', input_task_id=None, image_data=None, fallback=False):
    params = params if isinstance(params, dict) else {}
    provider = _pick_provider(config, params, fallback)
    if kind == 'textToImage' and image_data and provider != 'ark':
        raise ValueError('参考图生图只支持 Ark Provider，请把该节点 Provider 改为 Ark')
    if provider == 'ark':
        return _ark_submit(config, kind, params, prompt, image_data)
    return _tripo_submit(config, kind, params, prompt, input_task_id)


def _tripo_submit(config, kind, params, prompt, input_task_id):
    key = _key(config, 'tripo')
    if kind == 'textToImage':
        prompt = str(prompt or params.get('prompt') or '')[:6000]
        if not prompt.strip():
            raise ValueError('描述词不能为空')
        body = {'prompt': prompt, 'model': str(params.get('model') or 'seedream_v5'),
                'size': str(params.get('size') or '2K'),
                'output_format': _choice_param(params, 'outputFormat', ('png', 'jpeg'), 'png')}
        path = '/generation/text-to-image'
    elif kind == 'imageTo3D':
        task_id = input_task_id or params.get('inputTaskId')
        if not isinstance(task_id, str) or not re.fullmatch(r'task_[A-Za-z0-9_-]{4,128}', task_id):
            raise ValueError('图生 3D 需要上游 textToImage 的成功任务 ID')
        texture = _bool_param(params, 'texture', False)
        body = {'input': task_id, 'model': str(params.get('tripoModel') or params.get('model') or 'v3.1-20260211'),
                'texture': texture, 'pbr': texture and _bool_param(params, 'pbr', True),
                'face_limit': _int_param(params, 'faceLimit', 500, 150000) or 20000,
                'smart_low_poly': _bool_param(params, 'smartLowPoly', True)}
        if texture:
            body['texture_quality'] = _choice_param(params, 'textureQuality', ('standard', 'detailed'), 'standard')
            if _bool_param(params, 'autoSize'):
                body['auto_size'] = True
            if _choice_param(params, 'orientation', ('default', 'align_image'), 'default') == 'align_image':
                body['orientation'] = 'align_image'
            texture_seed = _int_param(params, 'textureSeed', 0)
            if texture_seed is not None:
                body['texture_seed'] = texture_seed
        model_seed = _int_param(params, 'modelSeed', 0)
        if model_seed is not None:
            body['model_seed'] = model_seed
        path = '/generation/image-to-model'
    else:
        raise ValueError('当前 Provider 不支持此节点类型')
    result = _request(TRIPO_BASE + path, key, body, timeout=45)
    task_id = result.get('task_id')
    if not isinstance(task_id, str) or not re.fullmatch(r'task_[A-Za-z0-9_-]{4,128}', task_id):
        raise RuntimeError('Provider 未返回有效 task_id')
    return {'taskId': task_id, 'provider': 'tripo', 'state': 'queued', 'submittedAt': time.time(),
            'requestType': kind}


def _ark_submit(config, kind, params, prompt, image_data):
    if kind == 'textToImage':
        prompt = str(prompt or params.get('prompt') or '')[:6000]
        if not prompt.strip():
            raise ValueError('描述词不能为空')
        body = {'model': str(params.get('model') or _provider_config(config, 'ark').get('image_model') or ARK_IMAGE_MODEL),
                'prompt': prompt, 'size': str(params.get('size') or '1K'),
                'response_format': 'url',
                'output_format': _choice_param(params, 'outputFormat', ('png', 'jpeg'), 'png'),
                'watermark': _bool_param(params, 'watermark', False)}
        if image_data:
            body['image'] = image_data
        result = _ark_request(config, '/images/generations', body, timeout=240)
        items = result.get('data')
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise RuntimeError('Ark 未返回图片地址')
        first = items[0]
        if first.get('error'):
            raise RuntimeError(_ark_error({'error': first['error']}, 200))
        url = first.get('url')
        if not isinstance(url, str) or not url:
            raise RuntimeError('Ark 未返回图片地址')
        _check_remote_url(url, 'Ark 图片')
        return {'taskId': 'arkimg_' + uuid.uuid4().hex[:16], 'provider': 'ark', 'state': 'success',
                'submittedAt': time.time(), 'requestType': kind,
                'output': {'generated_image_url': url}}
    if kind == 'imageTo3D':
        image_url = image_data if isinstance(image_data, str) and image_data else ''
        image_url = image_url or str(params.get('imageUrl') or params.get('image_url') or '').strip()
        if not image_url:
            raise ValueError('Seed3D 需要上游生成图或 imageUrl')
        if not image_url.startswith('data:image/') and not image_url.startswith('https://'):
            raise ValueError('Seed3D 输入图必须是 data URI 或 https 地址')
        content = [{'type': 'image_url', 'image_url': {'url': image_url}}]
        prompt = str(prompt or params.get('prompt') or '').strip()[:2000]
        if prompt:
            content.append({'type': 'text', 'text': prompt})
        body = {'model': str(params.get('model') or _provider_config(config, 'ark').get('model3d_model') or ARK_3D_MODEL),
                'content': content}
        result = _ark_request(config, '/contents/generations/tasks', body, timeout=60)
        task_id = result.get('id')
        if not isinstance(task_id, str) or not re.fullmatch(r'cgt-[A-Za-z0-9_-]{4,128}', task_id):
            raise RuntimeError('Ark 未返回有效任务 ID')
        return {'taskId': task_id, 'provider': 'ark', 'state': 'queued', 'submittedAt': time.time(),
                'requestType': kind}
    raise ValueError('当前 Provider 不支持此节点类型')


def poll(config, task):
    if isinstance(task, dict):
        provider = str(task.get('provider') or 'tripo')
        task_id = task.get('taskId')
    else:
        provider, task_id, task = 'tripo', task, {}
    if not isinstance(task_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{4,140}', task_id):
        raise ValueError('task_id 格式非法')
    if provider == 'ark':
        return _ark_poll(config, task_id, task)
    if not re.fullmatch(r'task_[A-Za-z0-9_-]{4,128}', task_id):
        raise ValueError('task_id 格式非法')
    result = _request(TRIPO_BASE + '/tasks/' + task_id, _key(config, 'tripo'), timeout=30)
    if not isinstance(result.get('status'), str):
        raise RuntimeError('Provider task 状态格式无效')
    output = result.get('output')
    if output is not None and not isinstance(output, dict):
        raise RuntimeError('Provider task 输出格式无效')
    return result


def _ark_success_output(content):
    if not isinstance(content, dict):
        return {}
    for key in ('model_url', 'file_url', 'glb_url', 'download_url', 'url'):
        value = content.get(key)
        if isinstance(value, str) and value:
            return {'model_url': value}
    for key, value in content.items():
        if isinstance(value, str) and value.startswith('https://') and key.endswith('_url'):
            return {'model_url': value}
    return {}


def _ark_poll(config, task_id, task):
    if task.get('requestType') == 'textToImage':
        output = task.get('output') if isinstance(task.get('output'), dict) else {}
        url = output.get('generated_image_url')
        if not isinstance(url, str) or not url:
            raise RuntimeError('Ark 图片任务缺少下载地址')
        return {'status': 'success', 'progress': 100, 'output': {'generated_image_url': url}}
    result = _ark_request(config, '/contents/generations/tasks/' + task_id, None, timeout=30)
    status = result.get('status')
    mapped = {'succeeded': 'success', 'failed': 'failed', 'expired': 'cancelled',
              'cancelled': 'cancelled', 'running': 'running', 'queued': 'queued'}.get(status)
    if not mapped:
        raise RuntimeError('Ark 返回了未知任务状态')
    progress = result.get('progress')
    if not isinstance(progress, int):
        progress = 100 if mapped == 'success' else 0
    error = result.get('error')
    message = ''
    if isinstance(error, dict):
        message = str(error.get('message') or error.get('code') or '')[:300]
    elif isinstance(error, str):
        message = error[:300]
    return {'status': mapped, 'progress': max(0, min(100, progress)),
            'error_message': message, 'output': _ark_success_output(result.get('content'))}


def download_model(url):
    parsed = urlparse(url or '')
    if parsed.scheme != 'https' or not _allowed_download_host(parsed.hostname) or parsed.username or parsed.password:
        raise ValueError('Provider 模型下载域名不在允许列表')
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            target = urlparse(new_url)
            if target.scheme != 'https' or not _allowed_download_host(target.hostname):
                raise ValueError('重定向后的模型域名不在允许列表')
            return super().redirect_request(request, response, code, message, headers, new_url)

    request = urllib.request.Request(url, headers={'Accept': 'model/gltf-binary,application/octet-stream,application/zip'})
    try:
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=90) as response:
            final = urlparse(response.geturl())
            if final.scheme != 'https' or not _allowed_download_host(final.hostname):
                raise ValueError('重定向后的模型域名不在允许列表')
            data = response.read(MAX_MODEL_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError('模型下载 HTTP %s' % error.code) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError('模型下载失败：%s' % type(error).__name__) from None
    if len(data) > MAX_MODEL_BYTES:
        raise ValueError('模型文件超过 150 MB 限制')
    if data[:2] == b'PK':
        data = _glb_from_zip(data)
    if len(data) < 12 or data[:4] != b'glTF':
        raise ValueError('下载文件不是有效的 GLB')
    declared = int.from_bytes(data[8:12], 'little')
    if declared != len(data):
        raise ValueError('GLB 文件长度校验失败')
    return data


def _glb_from_zip(data):
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith('.glb')]
            if not names:
                raise ValueError('压缩包中没有 GLB')
            return archive.read(names[0])
    except (zipfile.BadZipFile, KeyError) as error:
        raise ValueError('模型压缩包无效') from None


def download_image(url):
    parsed = urlparse(url or '')
    if parsed.scheme != 'https' or not _allowed_download_host(parsed.hostname) or parsed.username or parsed.password:
        raise ValueError('Provider 图片下载域名不在允许列表')
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            target = urlparse(new_url)
            if target.scheme != 'https' or not _allowed_download_host(target.hostname):
                raise ValueError('重定向后的图片域名不在允许列表')
            return super().redirect_request(request, response, code, message, headers, new_url)
    request = urllib.request.Request(url, headers={'Accept':'image/png,image/jpeg,image/webp'})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=60) as response:
        data = response.read(MAX_IMAGE_BYTES + 1)
        content_type = response.headers.get_content_type()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('图片超过 20 MB 限制')
    signatures = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff', 'image/webp': b'RIFF'}
    signature = signatures.get(content_type)
    if not signature or not data.startswith(signature) or (content_type == 'image/webp' and data[8:12] != b'WEBP'):
        raise ValueError('Provider 返回了无效或不支持的图片格式')
    return data, {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[content_type]
