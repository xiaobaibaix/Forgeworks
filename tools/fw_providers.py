"""Server-side provider adapters; no provider request runs without an explicit run action."""

import json
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
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MODEL_BYTES = 150 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
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


def submit(config, kind, params, prompt='', input_task_id=None, image_data=None, fallback=False):
    params = params if isinstance(params, dict) else {}
    provider = _pick_provider(config, params, fallback)
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
                'size': str(params.get('size') or '2K'), 'output_format': 'png'}
        path = '/generation/text-to-image'
    elif kind == 'imageTo3D':
        task_id = input_task_id or params.get('inputTaskId')
        if not isinstance(task_id, str) or not re.fullmatch(r'task_[A-Za-z0-9_-]{4,128}', task_id):
            raise ValueError('图生 3D 需要上游 textToImage 的成功任务 ID')
        body = {'input': task_id, 'model': str(params.get('model') or 'v3.1-20260211'),
                'texture': bool(params.get('texture', False)), 'pbr': bool(params.get('texture', False)),
                'face_limit': max(500, min(150000, int(params.get('faceLimit') or 20000))),
                'smart_low_poly': bool(params.get('smartLowPoly', True))}
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
                'response_format': 'url', 'output_format': 'png', 'watermark': False}
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
