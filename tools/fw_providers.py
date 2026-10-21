"""Server-side provider adapters; no provider request runs without an explicit run action."""

import json
import os
import re
import urllib.error
import urllib.request

TRIPO_BASE = 'https://openapi.tripo3d.ai/v3'
TRIPO_DOWNLOAD_HOSTS = {'cdn.tripo3d.ai'}
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_MODEL_BYTES = 150 * 1024 * 1024


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
        raise RuntimeError('Provider HTTP %s' % error.code) from None
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


def _key(config):
    if not isinstance(config, dict):
        raise ValueError('Provider 配置格式无效')
    providers = config.get('providers')
    tripo = providers.get('tripo') if isinstance(providers, dict) else None
    value = tripo.get('api_key') if isinstance(tripo, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Tripo API key 未配置')
    return value.strip()


def submit(config, kind, params, prompt='', input_task_id=None):
    key = _key(config)
    params = params if isinstance(params, dict) else {}
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
    return {'taskId': task_id, 'provider': 'tripo', 'state': 'queued', 'submittedAt': __import__('time').time(),
            'requestType': kind}


def poll(config, task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r'task_[A-Za-z0-9_-]{4,128}', task_id):
        raise ValueError('task_id 格式非法')
    result = _request(TRIPO_BASE + '/tasks/' + task_id, _key(config), timeout=30)
    if not isinstance(result.get('status'), str):
        raise RuntimeError('Provider task 状态格式无效')
    output = result.get('output')
    if output is not None and not isinstance(output, dict):
        raise RuntimeError('Provider task 输出格式无效')
    return result


def download_model(url):
    from urllib.parse import urlparse
    parsed = urlparse(url or '')
    if parsed.scheme != 'https' or parsed.hostname not in TRIPO_DOWNLOAD_HOSTS or parsed.username or parsed.password:
        raise ValueError('Provider 模型下载域名不在允许列表')
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            target = urlparse(new_url)
            if target.scheme != 'https' or target.hostname not in TRIPO_DOWNLOAD_HOSTS:
                raise ValueError('重定向后的模型域名不在允许列表')
            return super().redirect_request(request, response, code, message, headers, new_url)

    request = urllib.request.Request(url, headers={'Accept': 'model/gltf-binary,application/octet-stream'})
    try:
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=60) as response:
            final = urlparse(response.geturl())
            if final.scheme != 'https' or final.hostname not in TRIPO_DOWNLOAD_HOSTS:
                raise ValueError('重定向后的模型域名不在允许列表')
            data = response.read(MAX_MODEL_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError('模型下载 HTTP %s' % error.code) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError('模型下载失败：%s' % type(error).__name__) from None
    if len(data) > MAX_MODEL_BYTES:
        raise ValueError('模型文件超过 150 MB 限制')
    if len(data) < 12 or data[:4] != b'glTF':
        raise ValueError('下载文件不是有效的 GLB')
    declared = int.from_bytes(data[8:12], 'little')
    if declared != len(data):
        raise ValueError('GLB 文件长度校验失败')
    return data


def download_image(url):
    from urllib.parse import urlparse
    parsed = urlparse(url or '')
    if parsed.scheme != 'https' or parsed.hostname not in TRIPO_DOWNLOAD_HOSTS or parsed.username or parsed.password:
        raise ValueError('Provider 图片下载域名不在允许列表')
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            target = urlparse(new_url)
            if target.scheme != 'https' or target.hostname not in TRIPO_DOWNLOAD_HOSTS:
                raise ValueError('重定向后的图片域名不在允许列表')
            return super().redirect_request(request, response, code, message, headers, new_url)
    request = urllib.request.Request(url, headers={'Accept':'image/png,image/jpeg,image/webp'})
    with urllib.request.build_opener(SafeRedirect()).open(request, timeout=40) as response:
        data = response.read(20 * 1024 * 1024 + 1)
        content_type = response.headers.get_content_type()
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('图片超过 20 MB 限制')
    signatures = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff', 'image/webp': b'RIFF'}
    signature = signatures.get(content_type)
    if not signature or not data.startswith(signature) or (content_type == 'image/webp' and data[8:12] != b'WEBP'):
        raise ValueError('Provider 返回了无效或不支持的图片格式')
    return data, {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[content_type]
