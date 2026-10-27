#!/usr/bin/env python3
"""Three-view sheet post-processing: local panel crops and dimension captions."""

import os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - Pillow 缺失时由调用方降级
    Image = ImageDraw = ImageFont = None

PANEL_NAMES = ('front', 'side', 'top')
PANEL_DEVIATION_LIMIT = 0.06
GUTTER_TOLERANCE = 0.08
BLANK_INK_RATIO = 0.02
SAMPLE_WIDTH = 320
INK_THRESHOLD = 235
FONT_CANDIDATES = (
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
)


def _require_pillow():
    if Image is None:
        raise ValueError('THREEVIEW_UNAVAILABLE: 需要安装 Pillow 才能处理三视图')


def _empty_result(sheet_path=''):
    return {'sheetPath': sheet_path or '', 'frontPath': '', 'sidePath': '',
            'topPath': '', 'annotatedPath': '', 'warnings': []}


def _blank_columns(image):
    gray = image.convert('L')
    width, height = gray.size
    step = max(1, width // SAMPLE_WIDTH)
    scaled_width = max(3, width // step)
    scaled_height = max(1, height // step)
    small = gray.resize((scaled_width, scaled_height))
    pixels = list(small.getdata())
    ink = [0] * scaled_width
    for index, value in enumerate(pixels):
        if value < INK_THRESHOLD:
            ink[index % scaled_width] += 1
    limit = max(1, int(scaled_height * BLANK_INK_RATIO))
    return [count <= limit for count in ink], scaled_width


def _gutter_center(blank, scaled_width, expected):
    low = max(0, int((expected - GUTTER_TOLERANCE) * scaled_width))
    high = min(scaled_width - 1, int((expected + GUTTER_TOLERANCE) * scaled_width))
    runs = []
    index = low
    while index <= high:
        if not blank[index]:
            index += 1
            continue
        start = index
        while index + 1 <= high and blank[index + 1]:
            index += 1
        runs.append((start + index) / 2.0 / scaled_width)
        index += 1
    if not runs:
        return None
    return min(runs, key=lambda center: abs(center - expected))


def _panel_paths(out_dir, node_id):
    return {name + 'Path': os.path.join(out_dir, 'threeview_%s_%s.png' % (node_id, name))
            for name in PANEL_NAMES}


def crop_panels(sheet_path, out_dir, node_id):
    _require_pillow()
    result = _empty_result(sheet_path)
    try:
        image = Image.open(sheet_path)
        image.load()
    except (OSError, ValueError):
        result['warnings'].append('THREEVIEW_SHEET_MISSING: 三视图 sheet 不可读：%s' % sheet_path)
        return result
    width, height = image.size
    blank, scaled_width = _blank_columns(image)
    boundaries = [0.0]
    for number, expected in enumerate((1 / 3.0, 2 / 3.0), start=1):
        found = _gutter_center(blank, scaled_width, expected)
        if found is None:
            found = expected
            result['warnings'].append(
                'THREEVIEW_GUTTER_MISSING: 未找到第 %d 条分隔留白，按三等分裁切' % number)
        elif abs(found - expected) / expected > PANEL_DEVIATION_LIMIT:
            result['warnings'].append(
                'THREEVIEW_GUTTER_DEV: 第 %d 条分隔线偏离 %.1f%%，已按实际留白裁切'
                % (number, abs(found - expected) / expected * 100))
        boundaries.append(found)
    boundaries.append(1.0)
    os.makedirs(out_dir, exist_ok=True)
    paths = _panel_paths(out_dir, node_id)
    for index, name in enumerate(PANEL_NAMES):
        left = int(round(boundaries[index] * width))
        right = int(round(boundaries[index + 1] * width))
        if right <= left:
            result['warnings'].append('THREEVIEW_CROP_EMPTY: %s 视图裁切区域为空' % name)
            continue
        crop = image.crop((left, 0, right, height))
        crop.save(paths[name + 'Path'])
        result[name + 'Path'] = paths[name + 'Path']
    return result


def _font(size=14):
    for path in FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _annotation_lines(spec=None, measure=None):
    lines = []
    if isinstance(measure, dict) and measure.get('sizeM'):
        size = measure['sizeM']
        lines.append('单件 %s：X %.2f m / Y %.2f m / Z %.2f m'
                     % (measure.get('role') or '', float(size[0]), float(size[1]), float(size[2])))
    if isinstance(spec, dict):
        overall = spec.get('overall') if isinstance(spec.get('overall'), dict) else {}
        if overall:
            lines.append('整机：X %.2f m / Y %.2f m / Z %.2f m'
                         % (float(overall.get('lengthM') or 0), float(overall.get('widthM') or 0),
                            float(overall.get('heightM') or 0)))
        parts = spec.get('parts') if isinstance(spec.get('parts'), dict) else {}
        for role, part in list(parts.items())[:6]:
            size = (part or {}).get('sizeM')
            if not isinstance(size, list) or len(size) != 3:
                continue
            lines.append('%s：%.2f × %.2f × %.2f m'
                         % (role, float(size[0]), float(size[1]), float(size[2])))
    return lines


def annotate_sheet(sheet_path, out_path, spec=None, measure=None):
    _require_pillow()
    lines = _annotation_lines(spec, measure)
    image = Image.open(sheet_path).convert('RGB')
    if not lines:
        image.save(out_path)
        return out_path
    band = 20 * len(lines) + 12
    canvas = Image.new('RGB', (image.width, image.height + band), 'white')
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _font()
    for index, line in enumerate(lines):
        draw.text((12, image.height + 8 + index * 20), line, fill='black', font=font)
    canvas.save(out_path)
    return out_path


def process_three_view(sheet_path, out_dir, node_id, spec=None, measure=None, annotate=False):
    _require_pillow()
    if not sheet_path or not os.path.isfile(sheet_path):
        result = _empty_result(sheet_path)
        result['warnings'].append('THREEVIEW_SHEET_MISSING: 三视图 sheet 不存在，未裁切')
        return result
    result = crop_panels(sheet_path, out_dir, node_id)
    if annotate:
        try:
            output = os.path.join(out_dir, 'threeview_%s_annotated.png' % node_id)
            result['annotatedPath'] = annotate_sheet(sheet_path, output,
                                                     spec=spec, measure=measure)
        except (OSError, ValueError) as error:
            result['warnings'].append('THREEVIEW_ANNOTATE_FAILED: %s' % error)
    return result
