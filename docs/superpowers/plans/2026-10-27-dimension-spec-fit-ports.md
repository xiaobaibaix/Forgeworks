# 尺寸规格 + 校准 + 端口实施计划（P1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让挖掘机管线以结构化 `spec.json` 为尺寸事实来源：`blueprint` 生成/校验规格，`partImage` 输出端口锚点，`partModel` 用 Blender 校准到目标尺寸并输出米制端口与单件 `assembly`，旧图行为完全不变。

**Architecture:** 新增纯 Python 的 `tools/fw_spec.py`（schema、模板、24 个正交朝向、fit 选择、端口解析、mate 树）；`fw_providers.analyze_spec` 只负责把整机图转成候选 JSON；Bridge 负责确认门禁、落盘 `spec.json` 和把 spec/ports 注入节点结果；Blender 新增 `fit` 模式执行实际旋转/缩放/接地/端口定位；`fw_pipeline` 只做节点接线、spec 读取和调用钩子。所有新端口类型都是附加的，`schemaVersion` 仍为 1。

**Tech Stack:** Python 3.12 标准库（`json`、`math`、`itertools`、`unittest`、`subprocess`、`tempfile`）、Blender 5.2.3 Python API（`mathutils`）、现有静态前端 `js/pipeline.js` + `css/pipeline.css`。

**Spec:** `docs/superpowers/specs/2026-10-27-dimension-connector-assembly-design.md`

**执行入口：** 先读 [P1 执行入口](2026-10-27-dimension-spec-p1-start-here.md)（环境、基线、执行方式、安全边界、完成定义）。

## Global Constraints

- 运行 Python 一律用 `python`，不要用 `python3`（本机 `python3` 是坏的 Windows Store 别名）。
- 不发起任何真实付费 Provider 请求；测试全部 mock `fw_providers._ark_request` 或 `fw_providers.analyze_spec`。
- `tools/bridge_config.json` 含 Ark key，已在 gitignore；不得打印、回显、写入错误信息或提交。
- 用户已要求把交接文档提交并推送；实施过程中仍按测试检查点推进，除非用户另行要求，不要在实施任务里自动提交。
- 所有新增远程节点（`blueprint`，后续 P2/P3 的 `threeView`）都必须要求请求体 `confirmRemote: true` 且通过 loopback 同源校验。
- 新 JSON 路径使用相对资产目录的 POSIX 斜杠；`spec.json` 放在 `<asset>/pipeline/spec.json`。
- `schemaVersion` 保持 `1`；旧 `assemble`、KDTree snap、`partModel` 无 spec 时的 `part`/`mesh` 行为不得改变。
- 新增错误信息以 spec 的错误码开头：`SPEC_MISSING`、`SPEC_INVALID`、`SPEC_UNANCHORED`、`PART_ROLE_MISSING`、`FIT_ASPECT_MISMATCH`、`FIT_ORIENTATION_AMBIGUOUS`、`PORT_MISSING`。
- 测试命令统一用 `python -m unittest tests.<module> -v`；本机没有 pytest。
- Blender 集成测试找不到 Blender 时跳过，不把环境缺失算成代码失败。

## Handoff

计划与设计文档随分支 `feat/dimension-spec-p1` 推送到 `origin`。另一台机器开工前：

```bash
git fetch origin
git switch feat/dimension-spec-p1
```

先跑基线，确认起点与 2026-10-27 一致：

```bash
python -m unittest tests.test_fw_pipeline tests.test_fw_providers tests.test_bridge_providers tests.test_fw_parts -v
FW_BLENDER='E:\SteamLibrary\steamapps\common\Blender\blender.exe' python -m unittest tests.test_fw_blender -v
node --check js/pipeline.js
node --check js/data/prompts.js
```

基线结果：139 个非 Blender 测试中 138 通过，`CcSwitchImportTest.test_import_writes_key_endpoint_and_model` 因 Windows 不保留 `0o600` 权限而失败（环境问题，不是代码问题）；Blender 8 个测试全过；两个 JS 文件 `node --check` 通过。

实施入口：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，从 Task 1 开始。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `tools/fw_spec.py`（新建） | spec 常量/模板/校验、`from_vision`、端口锚点、24 朝向、fit 选择、mate 树、读写 `spec.json` |
| `tools/fw_providers.py`（修改） | 新增 `analyze_spec`，复用现有 Ark 视觉请求和 `_json_object` |
| `tools/fw_blender.py`（修改） | 新增 `--mode fit`，实际执行校准、接地、端口定位、导出 |
| `tools/fw_pipeline.py`（修改） | 新增 `blueprint` 节点类型、spec/ports 端口、`spec_for_node`、`partModel` fit 钩子 |
| `tools/bridge.py`（修改） | `blueprint` 提交/落盘、`partImage` 端口注入、确认门禁 |
| `js/pipeline.js`（修改） | 新节点/端口、blueprint 参数、spec/ports/fit 结果面板 |
| `css/pipeline.css`（修改） | spec/ports/fit 面板样式 |
| `tests/test_fw_spec.py`（新建） | schema、fit、端口、mate 树纯单元测试 |
| `tests/test_fw_providers.py`（修改） | `analyze_spec` 解析与错误测试 |
| `tests/test_fw_blender.py`（修改） | Blender `fit` 集成测试 |
| `tests/test_fw_pipeline.py`（修改） | 节点类型、spec 读取、fit 钩子、前端镜像静态测试 |
| `tests/test_bridge_providers.py`（修改） | blueprint 门禁/落盘、partImage 端口注入 |
| `tests/test_fw_parts.py`（不改） | 旧组装回归，确认 P1 未破坏 |

---

### Task 1: `fw_spec` 结构化规格、模板与校验

**Files:**
- Create: `tools/fw_spec.py`
- Test: `tests/test_fw_spec.py`

**Interfaces:**
- Consumes: 无（纯标准库）。
- Produces:
  - `SPEC_SCHEMA_VERSION = 1`
  - `PART_ROLES`、`ROLE_LABELS`、`EXCAVATOR_TEMPLATE`
  - `template_spec(asset_id='', template='excavator') -> dict`
  - `validate_spec(spec, warnings=None) -> dict`
  - `from_vision(raw, overall_length_m=0.0, template='excavator', asset_id='') -> dict`
  - `read_spec(path) -> dict`、`write_spec(path, spec) -> None`
  - `role_for_node(node_id, part_name='') -> str`
  - `anchor_ports(part_spec) -> list`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fw_spec.py`:

```python
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import fw_spec


class SpecValidationTest(unittest.TestCase):
    def test_excavator_template_is_valid(self):
        spec = fw_spec.template_spec('MC_EXCAVATOR')
        validated = fw_spec.validate_spec(spec)
        self.assertEqual(validated['schemaVersion'], 1)
        self.assertEqual(validated['units'], 'm')
        self.assertEqual(validated['assembly']['rootRole'], 'body')
        for role in ('body', 'track', 'boom', 'bucket', 'cab'):
            self.assertIn(role, validated['parts'])
            self.assertEqual(len(validated['parts'][role]['sizeM']), 3)

    def test_missing_overall_is_rejected(self):
        spec = fw_spec.template_spec('M1')
        del spec['overall']
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_negative_part_size_is_rejected(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['parts']['body']['sizeM'][0] = -1
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_unknown_connection_port_is_rejected(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['connections'][0]['a'] = 'bucket:no_such_port'
        with self.assertRaisesRegex(ValueError, 'SPEC_INVALID'):
            fw_spec.validate_spec(spec)

    def test_duplicate_port_connection_warns_and_is_skipped(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        duplicate = copy.deepcopy(spec['connections'][0])
        duplicate['id'] = 'c_duplicate'
        spec['connections'].append(duplicate)
        warnings = []
        validated = fw_spec.validate_spec(spec, warnings)
        self.assertEqual([item['id'] for item in validated['connections']].count('c_duplicate'), 0)
        self.assertTrue(any('重复' in warning for warning in warnings))

    def test_from_vision_uses_template_for_missing_parts_and_scales_to_anchor(self):
        raw = {
            'overall': {'lengthM': 7.2},
            'parts': {'bucket': {'sizeM': [1.0, 1.0, 1.0], 'confidence': 0.8}},
            'connections': [],
        }
        spec = fw_spec.from_vision(raw, overall_length_m=7.2, asset_id='M1')
        self.assertEqual(spec['overall']['source'], 'user')
        self.assertAlmostEqual(spec['overall']['lengthM'], 7.2)
        self.assertIn('body', spec['parts'])
        self.assertAlmostEqual(spec['parts']['body']['sizeM'][0], 4.2)
        self.assertAlmostEqual(spec['parts']['bucket']['sizeM'][0], 1.0)
        self.assertEqual(spec['connections'][0]['id'], 'c_bucket_boom')

    def test_read_write_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pipeline' / 'spec.json'
            original = fw_spec.template_spec('M1')
            fw_spec.write_spec(str(path), original)
            self.assertTrue(path.is_file())
            self.assertEqual(fw_spec.read_spec(str(path))['assetId'], 'M1')
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['units'], 'm')

    def test_role_for_node_handles_prefixes_and_chinese_names(self):
        self.assertEqual(fw_spec.role_for_node('partModel_body'), 'body')
        self.assertEqual(fw_spec.role_for_node('partImage_side_window', '侧窗'), 'window')
        self.assertEqual(fw_spec.role_for_node('partModel_boom', '动臂'), 'boom')
        self.assertEqual(fw_spec.role_for_node('mystery'), '')

    def test_anchor_ports_keep_anchor_but_have_no_metric_pos(self):
        part = fw_spec.template_spec('M1')['parts']['bucket']
        ports = fw_spec.anchor_ports(part)
        self.assertEqual(ports[0]['id'], 'ear_pin')
        self.assertEqual(ports[0]['anchorNorm'], [0.02, 0.5, 0.78])
        self.assertNotIn('pos', ports[0])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_spec -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fw_spec'`.

- [ ] **Step 3: Write minimal implementation**

Create `tools/fw_spec.py` with these exact contents (the fit functions in Task 2 are appended later):

```python
#!/usr/bin/env python3
"""Structured dimension specs, port anchors and assembly-tree planning."""

import copy
import json
import os
import tempfile

SPEC_SCHEMA_VERSION = 1
UNITS = 'm'
PART_ROLES = ('body', 'track', 'wheel', 'boom', 'bucket', 'cab', 'roof', 'door', 'window')
ROLE_LABELS = {
    'body': '车身', 'track': '履带', 'wheel': '车轮', 'boom': '动臂',
    'bucket': '铲斗', 'cab': '驾驶室', 'roof': '车顶', 'door': '车门',
    'window': '车窗',
}
ROLE_ALIASES = {
    'side_window': 'window', 'rear_window': 'window', 'front_window': 'window',
    '车体': 'body', '底盘': 'track', '履带': 'track', '轮子': 'wheel',
    '大臂': 'boom', '动臂': 'boom', '铲斗': 'bucket', '驾驶室': 'cab',
    '车顶': 'roof', '车门': 'door', '车窗': 'window', '玻璃': 'window',
}
FORWARDS = {
    '+X': (1.0, 0.0, 0.0), '-X': (-1.0, 0.0, 0.0),
    '+Y': (0.0, 1.0, 0.0), '-Y': (0.0, -1.0, 0.0),
    '+Z': (0.0, 0.0, 1.0), '-Z': (0.0, 0.0, -1.0),
}

EXCAVATOR_TEMPLATE = {
    'schemaVersion': 1,
    'assetId': '',
    'units': 'm',
    'overall': {'lengthM': 7.2, 'widthM': 2.4, 'heightM': 3.1,
                'source': 'template', 'confidence': 0.5},
    'assembly': {'rootRole': 'body'},
    'parts': {
        'body': {
            'role': 'body', 'sizeM': [4.2, 1.6, 1.4], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'boom_base', 'type': 'pin', 'anchor': [0.62, 0.5, 0.7],
                 'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.08},
                {'id': 'cab_mount', 'type': 'fixed', 'anchor': [0.2, 0.35, 0.9],
                 'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.05},
                {'id': 'track_mount', 'type': 'fixed', 'anchor': [0.5, 0.5, 0.05],
                 'axis': [0, 0, 1], 'normal': [1, 0, 0], 'radiusM': 0.12},
            ],
        },
        'track': {
            'role': 'track', 'sizeM': [4.6, 2.4, 1.0], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'axle', 'type': 'fixed', 'anchor': [0.5, 0.5, 0.9],
                 'axis': [0, 0, 1], 'normal': [1, 0, 0], 'radiusM': 0.12},
            ],
        },
        'boom': {
            'role': 'boom', 'sizeM': [3.6, 0.5, 0.7], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'base_pin', 'type': 'pin', 'anchor': [0.02, 0.5, 0.5],
                 'axis': [-1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.08},
                {'id': 'tip_pin', 'type': 'pin', 'anchor': [0.98, 0.5, 0.35],
                 'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.06},
            ],
        },
        'bucket': {
            'role': 'bucket', 'sizeM': [1.15, 1.2, 1.05], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'ear_pin', 'type': 'pin', 'anchor': [0.02, 0.5, 0.78],
                 'axis': [-1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.06},
            ],
        },
        'cab': {
            'role': 'cab', 'sizeM': [1.4, 0.9, 1.6], 'forward': '+X', 'confidence': 0.5,
            'ports': [
                {'id': 'floor', 'type': 'fixed', 'anchor': [0.5, 0.5, 0.02],
                 'axis': [0, 0, -1], 'normal': [1, 0, 0], 'radiusM': 0.05},
            ],
        },
    },
    'connections': [
        {'id': 'c_bucket_boom', 'a': 'bucket:ear_pin', 'b': 'boom:tip_pin', 'joint': 'pin'},
        {'id': 'c_boom_body', 'a': 'boom:base_pin', 'b': 'body:boom_base', 'joint': 'pin'},
        {'id': 'c_cab_body', 'a': 'cab:floor', 'b': 'body:cab_mount', 'joint': 'fixed'},
        {'id': 'c_track_body', 'a': 'track:axle', 'b': 'body:track_mount', 'joint': 'fixed'},
    ],
    'notes': [],
}


def template_spec(asset_id='', template='excavator'):
    if template != 'excavator':
        raise ValueError('SPEC_UNANCHORED: 没有机型模板 %s，请填写 overallLengthM' % template)
    spec = copy.deepcopy(EXCAVATOR_TEMPLATE)
    spec['assetId'] = str(asset_id or '')
    return validate_spec(spec)


def _number(value, label):
    if isinstance(value, bool):
        raise ValueError('SPEC_INVALID: %s 不能是布尔值' % label)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('SPEC_INVALID: %s 必须是数字' % label) from None
    return number


def _vec3(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('SPEC_INVALID: %s 必须是三个数字' % label)
    return [_number(item, label) for item in value]


def _unit(value, label):
    vector = _vec3(value, label)
    length = (vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2) ** 0.5
    if length < 1e-9:
        raise ValueError('SPEC_INVALID: %s 不能是零向量' % label)
    return [round(item / length, 9) for item in vector]


def validate_spec(spec, warnings=None):
    warnings = warnings if warnings is not None else []
    if not isinstance(spec, dict):
        raise ValueError('SPEC_INVALID: spec 必须是 JSON 对象')
    version = spec.get('schemaVersion')
    if version != SPEC_SCHEMA_VERSION:
        raise ValueError('SPEC_INVALID: schemaVersion 必须是 %d' % SPEC_SCHEMA_VERSION)
    if spec.get('units') != UNITS:
        raise ValueError('SPEC_INVALID: units 必须是 m')
    overall = spec.get('overall')
    if not isinstance(overall, dict):
        raise ValueError('SPEC_INVALID: 缺少 overall')
    normalized_overall = {}
    for key in ('lengthM', 'widthM', 'heightM'):
        value = _number(overall.get(key), 'overall.' + key)
        if value <= 0:
            raise ValueError('SPEC_INVALID: overall.%s 必须大于 0' % key)
        normalized_overall[key] = value
    source = str(overall.get('source') or 'template')
    if source not in ('user', 'template', 'vision'):
        raise ValueError('SPEC_INVALID: overall.source 只能是 user/template/vision')
    confidence = _number(overall.get('confidence', 0.5), 'overall.confidence')
    if not 0 <= confidence <= 1:
        raise ValueError('SPEC_INVALID: overall.confidence 必须在 0..1')
    normalized_overall.update({'source': source, 'confidence': confidence})

    raw_parts = spec.get('parts')
    if not isinstance(raw_parts, dict) or not raw_parts:
        raise ValueError('SPEC_INVALID: parts 必须是非空对象')
    parts = {}
    for role, raw_part in raw_parts.items():
        if role not in PART_ROLES:
            raise ValueError('SPEC_INVALID: 未知部件角色 %s' % role)
        if not isinstance(raw_part, dict):
            raise ValueError('SPEC_INVALID: parts.%s 必须是对象' % role)
        if raw_part.get('role') not in (None, role):
            raise ValueError('SPEC_INVALID: parts.%s.role 必须等于键名' % role)
        size = _vec3(raw_part.get('sizeM'), 'parts.%s.sizeM' % role)
        if any(value <= 0 for value in size):
            raise ValueError('SPEC_INVALID: parts.%s.sizeM 必须全部大于 0' % role)
        forward = str(raw_part.get('forward') or '+X').upper()
        if forward not in FORWARDS:
            raise ValueError('SPEC_INVALID: parts.%s.forward 非法' % role)
        part_confidence = _number(raw_part.get('confidence', 0.5), 'parts.%s.confidence' % role)
        if not 0 <= part_confidence <= 1:
            raise ValueError('SPEC_INVALID: parts.%s.confidence 必须在 0..1' % role)
        ports = []
        seen_ports = set()
        for raw_port in raw_part.get('ports') or []:
            if not isinstance(raw_port, dict):
                raise ValueError('SPEC_INVALID: parts.%s.ports 项必须是对象' % role)
            port_id = str(raw_port.get('id') or '').strip()
            if not port_id or port_id in seen_ports:
                raise ValueError('SPEC_INVALID: parts.%s 端口 id 为空或重复' % role)
            seen_ports.add(port_id)
            anchor = _vec3(raw_port.get('anchor'), 'ports.%s.anchor' % port_id)
            if any(value < -0.5 or value > 1.5 for value in anchor):
                raise ValueError('SPEC_INVALID: ports.%s.anchor 超出可用范围' % port_id)
            if any(value < 0 or value > 1 for value in anchor):
                warnings.append('端口 %s 的 anchor 超出 [0,1]，仅作为参考' % port_id)
            radius = _number(raw_port.get('radiusM', 0.02), 'ports.%s.radiusM' % port_id)
            if radius <= 0:
                raise ValueError('SPEC_INVALID: ports.%s.radiusM 必须大于 0' % port_id)
            ports.append({
                'id': port_id,
                'type': str(raw_port.get('type') or 'pin'),
                'anchor': anchor,
                'axis': _unit(raw_port.get('axis', [1, 0, 0]), 'ports.%s.axis' % port_id),
                'normal': _unit(raw_port.get('normal', [0, 0, 1]), 'ports.%s.normal' % port_id),
                'radiusM': radius,
            })
        parts[role] = {
            'role': role,
            'sizeM': size,
            'forward': forward,
            'confidence': part_confidence,
            'ports': ports,
        }
        if part_confidence < 0.4:
            warnings.append('部件 %s 的 confidence 低于 0.4' % role)

    raw_connections = spec.get('connections') or []
    if not isinstance(raw_connections, list):
        raise ValueError('SPEC_INVALID: connections 必须是数组')
    used_ports = set()
    connections = []
    for index, raw_connection in enumerate(raw_connections):
        if not isinstance(raw_connection, dict):
            raise ValueError('SPEC_INVALID: connections[%d] 必须是对象' % index)
        endpoints = []
        for side in ('a', 'b'):
            text = str(raw_connection.get(side) or '')
            if ':' not in text:
                raise ValueError('SPEC_INVALID: connections[%d].%s 必须是 role:port' % (index, side))
            role, port_id = text.split(':', 1)
            if role not in parts or port_id not in {item['id'] for item in parts[role]['ports']}:
                raise ValueError('SPEC_INVALID: connections[%d].%s 指向不存在的端口 %s'
                                 % (index, side, text))
            endpoints.append(text)
        if endpoints[0] == endpoints[1]:
            raise ValueError('SPEC_INVALID: 连接不能指向同一个端口')
        if endpoints[0] in used_ports or endpoints[1] in used_ports:
            warnings.append('端口重复连接，已跳过 connection %s'
                            % (raw_connection.get('id') or index))
            continue
        used_ports.update(endpoints)
        connections.append({
            'id': str(raw_connection.get('id') or 'c_%d_%s_%s'
                      % (index, endpoints[0].split(':')[0], endpoints[1].split(':')[0])),
            'a': endpoints[0],
            'b': endpoints[1],
            'joint': str(raw_connection.get('joint') or 'pin'),
        })

    assembly = spec.get('assembly') if isinstance(spec.get('assembly'), dict) else {}
    root_role = str(assembly.get('rootRole') or 'body')
    if root_role not in parts:
        warnings.append('assembly.rootRole=%s 不存在，改用连接度数最高的角色' % root_role)
        degrees = {role: 0 for role in parts}
        for connection in connections:
            for endpoint in (connection['a'], connection['b']):
                degrees[endpoint.split(':')[0]] += 1
        root_role = max(parts, key=lambda role: (degrees[role], role))

    return {
        'schemaVersion': SPEC_SCHEMA_VERSION,
        'assetId': str(spec.get('assetId') or ''),
        'units': UNITS,
        'overall': normalized_overall,
        'assembly': {'rootRole': root_role},
        'parts': parts,
        'connections': connections,
        'notes': [str(item) for item in (spec.get('notes') or [])],
    }


def from_vision(raw, overall_length_m=0.0, template='excavator', asset_id=''):
    if isinstance(raw, dict) and isinstance(raw.get('spec'), dict):
        raw = raw['spec']
    if not isinstance(raw, dict):
        raise ValueError('SPEC_INVALID: 视觉结果不是 JSON 对象')
    if template != 'excavator':
        raise ValueError('SPEC_UNANCHORED: 没有机型模板 %s' % template)
    spec = copy.deepcopy(EXCAVATOR_TEMPLATE)
    spec['assetId'] = str(asset_id or '')
    raw_parts = raw.get('parts') if isinstance(raw.get('parts'), dict) else {}
    for role, incoming in raw_parts.items():
        if role not in spec['parts'] or not isinstance(incoming, dict):
            continue
        target = spec['parts'][role]
        if isinstance(incoming.get('sizeM'), (list, tuple)):
            target['sizeM'] = list(incoming['sizeM'])
        if incoming.get('forward'):
            target['forward'] = str(incoming['forward']).upper()
        if isinstance(incoming.get('ports'), list) and incoming['ports']:
            target['ports'] = copy.deepcopy(incoming['ports'])
        if incoming.get('confidence') is not None:
            target['confidence'] = incoming['confidence']
    try:
        anchor = float(overall_length_m or 0)
    except (TypeError, ValueError):
        anchor = 0.0
    base_length = float(spec['overall']['lengthM'])
    if anchor > 0:
        factor = anchor / base_length
        spec['overall'] = {
            'lengthM': anchor,
            'widthM': float(spec['overall']['widthM']) * factor,
            'heightM': float(spec['overall']['heightM']) * factor,
            'source': 'user',
            'confidence': 0.9,
        }
        for part in spec['parts'].values():
            part['sizeM'] = [round(float(value) * factor, 6) for value in part['sizeM']]
    raw_connections = raw.get('connections')
    if isinstance(raw_connections, list) and raw_connections:
        spec['connections'] = copy.deepcopy(raw_connections)
    raw_assembly = raw.get('assembly') if isinstance(raw.get('assembly'), dict) else {}
    spec['assembly'] = {'rootRole': str(raw_assembly.get('rootRole') or 'body')}
    spec['notes'] = [str(item) for item in (raw.get('notes') or [])]
    return validate_spec(spec)


def read_spec(path):
    with open(path, encoding='utf-8') as stream:
        return validate_spec(json.load(stream))


def write_spec(path, spec):
    validated = validate_spec(spec)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.spec-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def role_for_node(node_id, part_name=''):
    text = str(node_id or '')
    for prefix in ('partModel_', 'partImage_', 'decimate_', 'assembly_', 'mate_'):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip().lower().replace('-', '_')
    if text in PART_ROLES:
        return text
    if text in ROLE_ALIASES:
        return ROLE_ALIASES[text]
    name = str(part_name or '').strip()
    for role, label in ROLE_LABELS.items():
        if label and label in name:
            return role
    return ''


def anchor_ports(part_spec):
    result = []
    for port in (part_spec or {}).get('ports') or []:
        result.append({
            'id': port['id'],
            'type': port.get('type') or 'pin',
            'anchorNorm': list(port['anchor']),
            'axis': list(port['axis']),
            'normal': list(port['normal']),
            'radiusM': port.get('radiusM', 0.02),
        })
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fw_spec -v`
Expected: `OK` (9 tests).

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_fw_spec -v`. Do not commit; report the test result and leave the files in the working tree.

---

### Task 2: 24 个正交朝向、fit 选择、米制端口与装配树

**Files:**
- Modify: `tools/fw_spec.py`
- Test: `tests/test_fw_spec.py`

**Interfaces:**
- Consumes: `template_spec`、`validate_spec`、`PART_ROLES`、`FORWARDS`。
- Produces:
  - `orientation_candidates() -> list[dict]`，恰好 24 个，全部行列式 +1。
  - `choose_orientation(measured, target, forward='+X', mode='uniform') -> dict`，字段 `matrix`、`scale`、`scalePerAxis`、`aspectError`、`rotationDeg`、`score`、`ambiguous`。
  - `resolve_ports(ports, bbox, matrix=None) -> list`，每项含 `pos`、`axis`、`normal`。
  - `build_mate_tree(spec) -> {'nodes': [...], 'edges': [...], 'warnings': [...]}`（P3 的 `/api/pipeline/spec/chain` 会直接复用）。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fw_spec.py` before `if __name__ == '__main__':`:

```python
class FitMathTest(unittest.TestCase):
    def test_twenty_four_proper_rotations_without_mirrors(self):
        candidates = fw_spec.orientation_candidates()
        self.assertEqual(len(candidates), 24)
        self.assertTrue(all(item['det'] == 1 for item in candidates))
        self.assertEqual(len({tuple(map(tuple, item['matrix'])) for item in candidates}), 24)

    def test_uniform_scale_matches_known_box(self):
        fit = fw_spec.choose_orientation([2, 1, 0.5], [4, 2, 1], '+X', 'uniform')
        self.assertAlmostEqual(fit['scale'], 2.0, places=9)
        self.assertAlmostEqual(fit['aspectError'], 0.0, places=9)
        self.assertEqual([round(value) for value in fit['rotationDeg']], [0, 0, 0])

    def test_axis_swap_chooses_quarter_turn(self):
        fit = fw_spec.choose_orientation([2, 1, 1], [1, 2, 1], '+X', 'uniform')
        self.assertAlmostEqual(fit['scale'], 1.0, places=9)
        self.assertAlmostEqual(fit['aspectError'], 0.0, places=9)
        self.assertEqual(abs(round(fit['rotationDeg'][2])), 90)

    def test_per_axis_scale_is_exact(self):
        # 目标 [4,2,1] 让恒等朝向成为首个最优解，缩放后每一轴都应精确命中。
        fit = fw_spec.choose_orientation([2, 1, 1], [4, 2, 1], '+X', 'perAxis')
        self.assertEqual(len(fit['scalePerAxis']), 3)
        self.assertAlmostEqual(fit['scalePerAxis'][0] * 2, 4, places=6)
        self.assertAlmostEqual(fit['scalePerAxis'][1] * 1, 2, places=6)
        self.assertAlmostEqual(fit['scalePerAxis'][2] * 1, 1, places=6)

    def test_center_anchor_resolves_to_bbox_center(self):
        ports = fw_spec.resolve_ports(
            [{'id': 'p', 'anchor': [0.5, 0.5, 0.5], 'axis': [1, 0, 0],
              'normal': [0, 0, 1], 'radiusM': 0.1}],
            {'min': [-1, -2, -3], 'max': [1, 2, 3]})
        self.assertEqual(ports[0]['pos'], [0.0, 0.0, 0.0])
        self.assertEqual(ports[0]['axis'], [1.0, 0.0, 0.0])

    def test_rotated_port_axis_uses_same_matrix(self):
        fit = fw_spec.choose_orientation([2, 1, 1], [1, 2, 1], '+X', 'uniform')
        ports = fw_spec.resolve_ports(
            [{'id': 'p', 'anchor': [0.5, 0.5, 0.5], 'axis': [1, 0, 0],
              'normal': [0, 0, 1], 'radiusM': 0.1}],
            {'min': [-1, -1, -1], 'max': [1, 1, 1]}, fit['matrix'])
        self.assertAlmostEqual(abs(ports[0]['axis'][1]), 1.0, places=9)


class MateTreeTest(unittest.TestCase):
    def test_excavator_tree_is_postorder_binary_chain(self):
        tree = fw_spec.build_mate_tree(fw_spec.template_spec('M1'))
        self.assertEqual([node['id'] for node in tree['nodes']][:2],
                         ['mate_boom_bucket', 'mate_body_boom'])
        self.assertEqual(tree['nodes'][0]['connection'], 'c_bucket_boom')
        self.assertEqual(tree['warnings'], [])

    def test_cycle_produces_warning_not_exception(self):
        spec = copy.deepcopy(fw_spec.template_spec('M1'))
        spec['parts']['body']['ports'].append(
            {'id': 'loop', 'type': 'pin', 'anchor': [0.5, 0.5, 0.5],
             'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.05})
        spec['parts']['bucket']['ports'].append(
            {'id': 'loop', 'type': 'pin', 'anchor': [0.5, 0.5, 0.5],
             'axis': [-1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.05})
        spec['connections'].append(
            {'id': 'c_loop', 'a': 'body:loop', 'b': 'bucket:loop', 'joint': 'pin'})
        tree = fw_spec.build_mate_tree(spec)
        self.assertTrue(any('环' in warning for warning in tree['warnings']))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_spec.FitMathTest tests.test_fw_spec.MateTreeTest -v`
Expected: FAIL with `AttributeError: module 'fw_spec' has no attribute 'orientation_candidates'`.

- [ ] **Step 3: Write minimal implementation**

Append to `tools/fw_spec.py`:

```python
def _det3(matrix):
    return (matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
            - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
            + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0]))


def _mat_vec(matrix, vector):
    return [sum(matrix[row][column] * vector[column] for column in range(3))
            for row in range(3)]


def orientation_candidates():
    from itertools import permutations, product
    candidates = []
    for perm in permutations(range(3)):
        for signs in product((-1, 1), repeat=3):
            matrix = [[0, 0, 0] for _ in range(3)]
            for axis in range(3):
                matrix[axis][perm[axis]] = signs[axis]
            determinant = _det3(matrix)
            if abs(determinant - 1) > 1e-9:
                continue
            candidates.append({
                'matrix': matrix,
                'perm': list(perm),
                'signs': list(signs),
                'det': 1,
            })
    return candidates


def _euler_deg(matrix):
    import math
    sy = max(-1.0, min(1.0, -matrix[2][0]))
    if abs(sy) < 1 - 1e-9:
        ry = math.asin(sy)
        rx = math.atan2(matrix[2][1], matrix[2][2])
        rz = math.atan2(matrix[1][0], matrix[0][0])
    else:
        ry = math.copysign(math.pi / 2, sy)
        rx = math.atan2(-matrix[1][2], matrix[1][1])
        rz = 0.0
    return [round(math.degrees(value), 6) for value in (rx, ry, rz)]


def choose_orientation(measured, target, forward='+X', mode='uniform'):
    if mode not in ('uniform', 'perAxis'):
        raise ValueError('FIT_ORIENTATION_AMBIGUOUS: 未知 fitMode %s' % mode)
    measured = [float(value) for value in measured]
    target = [float(value) for value in target]
    if len(measured) != 3 or len(target) != 3 or any(value <= 0 for value in measured + target):
        raise ValueError('SPEC_INVALID: measured/target 必须是三个正数')
    forward_vector = FORWARDS.get(str(forward or '+X').upper())
    if forward_vector is None:
        raise ValueError('SPEC_INVALID: 未知 forward %s' % forward)
    best = None
    for candidate in orientation_candidates():
        matrix = candidate['matrix']
        rotated = [measured[candidate['perm'][axis]] for axis in range(3)]
        if mode == 'perAxis':
            scale_per_axis = [target[axis] / rotated[axis] for axis in range(3)]
            scale = (scale_per_axis[0] * scale_per_axis[1] * scale_per_axis[2]) ** (1 / 3.0)
            aspect_error = max(abs(value / scale - 1.0) for value in scale_per_axis)
        else:
            denominator = sum(value * value for value in rotated)
            scale = sum(target[axis] * rotated[axis] for axis in range(3)) / denominator
            scale_per_axis = [scale, scale, scale]
            aspect_error = max(abs(rotated[axis] * scale - target[axis]) / target[axis]
                               for axis in range(3))
        rotated_forward = _mat_vec(matrix, [1, 0, 0])
        alignment = sum(rotated_forward[axis] * forward_vector[axis] for axis in range(3))
        score = aspect_error + 0.05 * (1.0 - alignment)
        item = {
            'matrix': matrix,
            'scale': scale,
            'scalePerAxis': scale_per_axis,
            'aspectError': aspect_error,
            'rotationDeg': _euler_deg(matrix),
            'score': score,
            'ambiguous': False,
        }
        if best is None or score < best['score'] - 1e-12:
            best = item
        elif abs(score - best['score']) <= 1e-12:
            best['ambiguous'] = True
    return best


def resolve_ports(ports, bbox, matrix=None):
    if isinstance(bbox, dict):
        lower = [float(value) for value in bbox['min']]
        upper = [float(value) for value in bbox['max']]
    else:
        lower = [float(value) for value in bbox[0]]
        upper = [float(value) for value in bbox[1]]
    result = []
    for port in ports or []:
        anchor = [float(value) for value in port.get('anchor', [0.5, 0.5, 0.5])]
        axis = _unit(port.get('axis', [1, 0, 0]), 'port.axis')
        normal = _unit(port.get('normal', [0, 0, 1]), 'port.normal')
        if matrix is not None:
            axis = _unit(_mat_vec(matrix, axis), 'port.axis')
            normal = _unit(_mat_vec(matrix, normal), 'port.normal')
        result.append({
            'id': str(port.get('id') or ''),
            'type': str(port.get('type') or 'pin'),
            'anchorNorm': anchor,
            'pos': [round(lower[axis_index] + anchor[axis_index]
                          * (upper[axis_index] - lower[axis_index]), 6)
                    for axis_index in range(3)],
            'axis': axis,
            'normal': normal,
            'radiusM': float(port.get('radiusM') or 0.02),
        })
    return result


def _find(parent, role):
    while parent[role] != role:
        parent[role] = parent[parent[role]]
        role = parent[role]
    return role


def _union(parent, left, right):
    left_root, right_root = _find(parent, left), _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def build_mate_tree(spec):
    validated = validate_spec(spec)
    warnings = []
    parent = {role: role for role in validated['parts']}
    edges = []
    for connection in validated['connections']:
        left_role = connection['a'].split(':')[0]
        right_role = connection['b'].split(':')[0]
        if _find(parent, left_role) == _find(parent, right_role):
            warnings.append('连接图有环，已跳过 connection %s' % connection['id'])
            continue
        _union(parent, left_role, right_role)
        edges.append(connection)

    adjacency = {role: [] for role in validated['parts']}
    for connection in edges:
        left_role = connection['a'].split(':')[0]
        right_role = connection['b'].split(':')[0]
        adjacency[left_role].append((right_role, connection))
        adjacency[right_role].append((left_role, connection))

    root_role = validated['assembly']['rootRole']
    visited = set()
    nodes = []
    plan_edges = []

    def visit(role, parent_role=None):
        visited.add(role)
        current = 'partModel_' + role
        for child_role, connection in adjacency[role]:
            if child_role == parent_role:
                continue
            child_result = visit(child_role, role)
            mate_id = 'mate_%s_%s' % (role, child_role)
            nodes.append({
                'id': mate_id,
                'connection': connection['id'],
                'aRole': role,
                'bRole': child_role,
                'a': current,
                'b': child_result,
            })
            plan_edges.append({'from': current, 'out': 'assembly', 'to': mate_id, 'in': 'a'})
            plan_edges.append({'from': child_result, 'out': 'assembly', 'to': mate_id, 'in': 'b'})
            current = mate_id
        return current

    visit(root_role)
    for role in validated['parts']:
        if role not in visited:
            warnings.append('连接图不连通，角色 %s 单独作为一棵装配树' % role)
            visit(role)
    return {'nodes': nodes, 'edges': plan_edges, 'warnings': warnings}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fw_spec -v`
Expected: `OK` (17 tests).

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_fw_spec -v`. Do not commit.

---

### Task 3: `fw_providers.analyze_spec`

**Files:**
- Modify: `tools/fw_providers.py`
- Test: `tests/test_fw_providers.py`

**Interfaces:**
- Consumes: `_provider_config`、`_vision_image_uri`、`_ark_request`、`_json_object`、`_message_text`、`ARK_VISION_MODEL`。
- Produces: `analyze_spec(config, image_path, parts, prompt='', model='', overall_length=0.0, template='excavator') -> (raw_spec, meta)`；`meta` 含 `model`、`notes`。

- [ ] **Step 1: Write the failing test**

Append a new class to `tests/test_fw_providers.py` before `if __name__ == '__main__':`:

```python
class ArkSpecTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.original = fw_providers._ark_request

    def tearDown(self):
        fw_providers._ark_request = self.original

    def _image(self, directory):
        path = pathlib.Path(directory) / 'overall.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n')
        return str(path)

    def test_parses_fenced_spec_json_and_sends_image(self):
        def fake(config, route, payload=None, timeout=60):
            self.calls.append((route, payload))
            return {'choices': [{'message': {'content':
                '```json\n{"parts":{"bucket":{"sizeM":[1.1,1.2,1.0],'
                '"forward":"+X","confidence":0.7}},"notes":["ok"]}\n```'}}]}

        fw_providers._ark_request = fake
        with tempfile.TemporaryDirectory() as directory:
            raw, meta = fw_providers.analyze_spec(
                ARK_CONFIG, self._image(directory),
                [{'name': '铲斗', 'description': '前端挖斗'}],
                prompt='保持比例', overall_length=7.2, template='excavator')

        self.assertEqual(raw['parts']['bucket']['sizeM'], [1.1, 1.2, 1.0])
        self.assertEqual(meta['model'], fw_providers.ARK_VISION_MODEL)
        self.assertEqual(meta['notes'], 'ok')
        route, payload = self.calls[0]
        self.assertEqual(route, '/chat/completions')
        content = payload['messages'][1]['content']
        self.assertEqual(content[0]['type'], 'text')
        self.assertEqual(content[1]['type'], 'image_url')
        self.assertIn('data:image/png;base64,', content[1]['image_url']['url'])
        self.assertIn('7.200', content[0]['text'])
        self.assertIn('bucket', content[0]['text'])

    def test_invalid_json_raises_runtime_error(self):
        fw_providers._ark_request = lambda *args, **kwargs: {
            'choices': [{'message': {'content': 'not json'}}]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, '有效 JSON'):
                fw_providers.analyze_spec(
                    ARK_CONFIG, self._image(directory), [{'name': '车身'}])

    def test_missing_image_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            fw_providers.analyze_spec(
                ARK_CONFIG, 'missing.png', [{'name': '车身'}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_providers.ArkSpecTest -v`
Expected: FAIL with `AttributeError: module 'fw_providers' has no attribute 'analyze_spec'`.

- [ ] **Step 3: Write minimal implementation**

Append to `tools/fw_providers.py` after `analyze_layout`:

```python
def analyze_spec(config, image_path, parts, prompt='', model='',
                 overall_length=0.0, template='excavator'):
    """让 Ark 视觉模型把整机效果图整理成结构化 spec 候选 JSON。"""
    name = str(model or _provider_config(config, 'ark').get('vision_model')
               or ARK_VISION_MODEL).strip()
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
        raise ValueError('没有可用于尺寸规格的部件')
    try:
        anchor = float(overall_length or 0)
    except (TypeError, ValueError):
        anchor = 0.0
    anchor_text = ('整机长度锚：%.3f 米' % anchor) if anchor > 0 else '整机长度锚：未提供'
    instruction = str(prompt or '').strip()[:1200]
    user_text = (
        '参考图是一台机械的整体效果图。已经拆出的部件：\n%s\n'
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
        'max_tokens': 1800,
    }
    result = _ark_request(config, '/chat/completions', body, timeout=120)
    choices = result.get('choices')
    message = ((choices or [{}])[0] or {}).get('message') if isinstance(choices, list) else None
    content = _message_text((message or {}).get('content'))
    raw = _json_object(content)
    notes = raw.get('notes')
    if isinstance(notes, list):
        notes = '; '.join(str(item) for item in notes)
    return raw, {'model': name, 'notes': str(notes or '')[:500]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fw_providers.ArkSpecTest -v`
Expected: `OK` (3 tests).

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_fw_providers -v`. Do not commit.

---

### Task 4: Blender `fit` 模式

**Files:**
- Modify: `tools/fw_blender.py`
- Test: `tests/test_fw_blender.py`

**Interfaces:**
- Consumes: `fw_spec.choose_orientation`、`fw_spec.resolve_ports`（从 `tools/` 导入），现有 `_mesh_objects`、`_object_bounds`、`_count_triangles`、`_write_report`。
- Produces: CLI `--mode fit --plan <json> --output <glb> --report <json>`。plan JSON：
  ```json
  {"input":"in.glb","targetSizeM":[1,2,1],"fitMode":"uniform","ground":false,"forward":"+X","ports":[...]}
  ```
  report JSON：`{"valid":true,"mode":"fit","fit":{"mode","scale","scalePerAxis","aspectError","rotationDeg","measuredBbox","grounded","ambiguous"},"ports":[...],"triangles":N}`。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fw_blender.py`:

```python
class BlenderFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blender = find_blender()
        if not cls.blender:
            raise unittest.SkipTest('Blender not installed')

    def _run_fit(self, source_size, target_size, forward='+X', ports=None, ground=False):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'source.glb'
            output = directory / 'fitted.glb'
            plan = directory / 'plan.json'
            make_box_glb(source, size=source_size)
            plan.write_text(json.dumps({
                'input': str(source), 'output': str(output),
                'targetSizeM': list(target_size), 'fitMode': 'uniform',
                'ground': ground, 'forward': forward, 'ports': ports or [],
            }), encoding='utf-8')
            report = run_blender(self.blender, [
                '--mode', 'fit', '--plan', str(plan), '--output', str(output)])
            self.assertTrue(output.is_file())
            return report

    def test_uniform_fit_scales_box_by_two(self):
        report = self._run_fit((2, 1, 1), (4, 2, 2))
        self.assertTrue(report['valid'], report)
        self.assertAlmostEqual(report['fit']['scale'], 2.0, places=3)
        self.assertAlmostEqual(report['fit']['aspectError'], 0.0, places=3)
        self.assertGreater(report['triangles'], 0)

    def test_fit_swaps_axes_with_quarter_turn(self):
        report = self._run_fit((2, 1, 1), (1, 2, 1))
        self.assertTrue(report['valid'], report)
        self.assertAlmostEqual(report['fit']['scale'], 1.0, places=3)
        self.assertEqual(abs(round(report['fit']['rotationDeg'][2])), 90)

    def test_fit_resolves_center_port(self):
        ports = [{'id': 'center', 'type': 'pin', 'anchor': [0.5, 0.5, 0.5],
                  'axis': [1, 0, 0], 'normal': [0, 0, 1], 'radiusM': 0.1}]
        report = self._run_fit((2, 1, 1), (2, 1, 1), ports=ports)
        self.assertTrue(report['valid'], report)
        center = report['ports'][0]['pos']
        self.assertAlmostEqual(center[0], 0.0, places=3)
        self.assertAlmostEqual(center[1], 0.0, places=3)
        self.assertAlmostEqual(center[2], 0.0, places=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_blender.BlenderFitTest -v`
Expected: FAIL at `--mode fit` / report missing `fit`, or `argparse` rejects `fit`; if Blender is absent the class is skipped — record that and continue.

- [ ] **Step 3: Write minimal implementation**

In `tools/fw_blender.py`:

1. Add the `fit` choice and import `fw_spec` after the standard imports:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fw_spec
```

2. Change the argparse choices:

```python
    parser.add_argument('--mode', choices=('inspect', 'decimate', 'measure', 'assemble', 'cut', 'fit'),
                        default='inspect')
```

3. Add `_fit(args)` before `def main()`:

```python
def _fit(args):
    import bpy
    from mathutils import Matrix

    report = {'valid': True, 'mode': 'fit', 'errors': []}
    try:
        if not args.plan:
            raise ValueError('fit 模式需要 --plan')
        with open(args.plan, encoding='utf-8') as stream:
            plan = json.load(stream)
        source = str(plan.get('input') or args.input or '')
        output = str(plan.get('output') or args.output or '')
        if not source or not os.path.isfile(source):
            raise ValueError('fit 输入 GLB 不存在')
        if not output:
            raise ValueError('fit 缺少输出路径')
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=source)
        objects = _mesh_objects()
        if not objects:
            raise ValueError('fit 输入没有网格')
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        if len(objects) > 1:
            bpy.ops.object.join()
        target = bpy.context.view_layer.objects.active
        bpy.context.view_layer.update()
        lower, upper = _object_bounds(target)
        measured = [upper[index] - lower[index] for index in range(3)]
        fit = fw_spec.choose_orientation(
            measured, plan['targetSizeM'], plan.get('forward', '+X'),
            plan.get('fitMode', 'uniform'))
        rotation = fit['matrix']
        scale = fit.get('scalePerAxis') or [fit['scale']] * 3
        rotation_matrix = Matrix((
            (rotation[0][0], rotation[0][1], rotation[0][2], 0.0),
            (rotation[1][0], rotation[1][1], rotation[1][2], 0.0),
            (rotation[2][0], rotation[2][1], rotation[2][2], 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        scale_matrix = Matrix((
            (scale[0], 0.0, 0.0, 0.0),
            (0.0, scale[1], 0.0, 0.0),
            (0.0, 0.0, scale[2], 0.0),
            (0.0, 0.0, 0.0, 1.0),
        ))
        target.matrix_world = scale_matrix @ rotation_matrix @ target.matrix_world
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        if plan.get('ground'):
            bpy.context.view_layer.update()
            lower, upper = _object_bounds(target)
            target.location.z -= lower[2]
            bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
        bpy.context.view_layer.update()
        lower, upper = _object_bounds(target)
        ports = fw_spec.resolve_ports(plan.get('ports') or [],
                                      {'min': lower, 'max': upper}, rotation)
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=output, export_format='GLB')
        if not os.path.isfile(output):
            raise RuntimeError('fit 未生成 GLB')
        report['fit'] = {
            'mode': plan.get('fitMode', 'uniform'),
            'scale': round(float(fit['scale']), 9),
            'scalePerAxis': [round(float(value), 9) for value in fit['scalePerAxis']],
            'aspectError': round(float(fit['aspectError']), 9),
            'rotationDeg': fit['rotationDeg'],
            'measuredBbox': {'min': [round(float(value), 6) for value in lower],
                             'max': [round(float(value), 6) for value in upper]},
            'grounded': bool(plan.get('ground')),
            'ambiguous': bool(fit.get('ambiguous')),
        }
        report['ports'] = ports
        report['triangles'] = _count_triangles([target])
    except Exception as error:
        report['valid'] = False
        report['errors'].append(str(error))
    return report
```

4. Register the handler in `main()`:

```python
    handlers = {'inspect': _inspect, 'decimate': _decimate,
                'measure': _measure, 'assemble': _assemble, 'cut': _cut,
                'fit': _fit}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fw_blender.BlenderFitTest -v`
Expected: `OK` (3 tests) when Blender is available; `OK (skipped=3)` when it is not.

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_fw_blender -v`. Do not commit.

---

### Task 5: 管线节点类型、spec 读取与端口解析

**Files:**
- Modify: `tools/fw_pipeline.py`
- Test: `tests/test_fw_pipeline.py`

**Interfaces:**
- Consumes: `fw_pipeline.pipeline_root`、`resolve_output`、`_graph_hashes`、`fw_spec.validate_spec`、`fw_spec.role_for_node`、`fw_spec.anchor_ports`。
- Produces:
  - `NODE_TYPES` 增加 `blueprint`；`partImage` 增加 `spec` 输入与 `ports` 输出；`partModel` 增加 `spec`/`ports` 输入与 `assembly` 输出。
  - `PROVIDER_TYPES` 包含 `blueprint`。
  - `spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id) -> dict | None`。
  - `ports_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id) -> list`。
  - `part_role_for_node(graph, by_id, node_id) -> str`。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fw_pipeline.py` before `if __name__ == '__main__':`:

```python
class SpecPipelineTest(unittest.TestCase):
    def test_node_types_include_p1_ports(self):
        self.assertEqual(fw_pipeline.NODE_TYPES['blueprint']['out']['spec'], 'spec')
        self.assertEqual(fw_pipeline.NODE_TYPES['partImage']['in']['spec'], 'spec')
        self.assertEqual(fw_pipeline.NODE_TYPES['partImage']['out']['ports'], 'ports')
        self.assertEqual(fw_pipeline.NODE_TYPES['partModel']['in']['ports'], 'ports')
        self.assertEqual(fw_pipeline.NODE_TYPES['partModel']['out']['assembly'], 'assembly')
        self.assertIn('blueprint', fw_pipeline.PROVIDER_TYPES)

    def test_validate_graph_accepts_spec_and_ports_edges(self):
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'blueprint', 'type': 'blueprint', 'params': {}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {}},
                {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
            ],
            'edges': [
                {'from': 'blueprint', 'out': 'spec', 'to': 'partImage_body', 'in': 'spec'},
                {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
                {'from': 'partImage_body', 'out': 'ports', 'to': 'partModel_body', 'in': 'ports'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'partModel_body', 'in': 'spec'},
            ],
        }
        fw_pipeline.validate_graph(graph)
        graph['edges'].append({'from': 'blueprint', 'out': 'spec',
                               'to': 'partModel_body', 'in': 'mesh'})
        with self.assertRaises(ValueError):
            fw_pipeline.validate_graph(graph)

    def test_spec_for_node_reads_upstream_output_and_spec_file(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = fw_spec.template_spec('M1')
            path = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'spec.json'
            fw_spec.write_spec(str(path), spec)
            graph = {
                'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                'nodes': [
                    {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                     'result': {'state': 'done', 'output': {'specPath': 'spec.json', 'spec': spec}}},
                    {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                ],
                'edges': [{'from': 'blueprint', 'out': 'spec',
                           'to': 'partModel_body', 'in': 'spec'}],
            }
            by_id, _ = fw_pipeline.validate_graph(graph)
            loaded = fw_pipeline.spec_for_node(directory, 'M1', 'machine', graph, by_id,
                                               'partModel_body')
            self.assertEqual(loaded['parts']['body']['role'], 'body')
            self.assertEqual(fw_pipeline.part_role_for_node(graph, by_id, 'partModel_body'), 'body')

    def test_ports_for_node_prefers_ports_input(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = {
                'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
                'nodes': [
                    {'id': 'partImage_body', 'type': 'partImage', 'params': {},
                     'result': {'state': 'done', 'output': {'ports': [{'id': 'p'}]}}},
                    {'id': 'partModel_body', 'type': 'partModel', 'params': {}},
                ],
                'edges': [{'from': 'partImage_body', 'out': 'ports',
                           'to': 'partModel_body', 'in': 'ports'}],
            }
            by_id, _ = fw_pipeline.validate_graph(graph)
            self.assertEqual(fw_pipeline.ports_for_node(directory, 'M1', 'machine', graph,
                                                        by_id, 'partModel_body'),
                             [{'id': 'p'}])
```

Add `import fw_spec` next to `import fw_pipeline` at the top of `tests/test_fw_pipeline.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_pipeline.SpecPipelineTest -v`
Expected: FAIL with `KeyError: 'blueprint'` / `AttributeError: spec_for_node`.

- [ ] **Step 3: Write minimal implementation**

In `tools/fw_pipeline.py`:

1. Add `import fw_spec` after `import fw_providers`.

2. Replace the three node definitions:

```python
    'blueprint': {'in': {'image': 'image', 'text': 'text'}, 'out': {'spec': 'spec'}},
    'partImage': {'in': {'text': 'text', 'image': 'image', 'spec': 'spec'},
                  'out': {'image': 'image', 'ports': 'ports'}},
    'partModel': {'in': {'image': 'image', 'spec': 'spec', 'ports': 'ports'},
                  'out': {'part': 'part', 'mesh': 'mesh', 'assembly': 'assembly'}},
```

3. Add `blueprint` to `PROVIDER_TYPES`:

```python
PROVIDER_TYPES = ('textToImage', 'imageTo3D', 'partImage', 'partModel', 'blueprint')
```

4. Add helpers after `_load_provider_config`:

```python
def spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'spec'), None)
    if not edge:
        return None
    source = by_id.get(edge.get('from'))
    if not source:
        raise ValueError('SPEC_MISSING: spec 上游节点不存在')
    result = source.get('result') or {}
    output = result.get('output') or {}
    candidate = output.get('spec')
    if isinstance(candidate, dict):
        return fw_spec.validate_spec(candidate)
    spec_path = output.get('specPath') or 'spec.json'
    root = pipeline_root(forgeworks_root, asset_id, kind)
    path = os.path.join(root, str(spec_path))
    if not os.path.isfile(path):
        raise ValueError('SPEC_MISSING: 上游规格尚未生成：%s' % spec_path)
    return fw_spec.read_spec(path)


def ports_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'ports'), None)
    if edge:
        source = by_id.get(edge.get('from')) or {}
        output = (source.get('result') or {}).get('output') or {}
        ports = output.get('ports')
        if isinstance(ports, list):
            return ports
        raise ValueError('PORT_MISSING: ports 上游没有端口结果')
    spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    if not spec:
        return []
    role = part_role_for_node(graph, by_id, node_id)
    part = spec['parts'].get(role)
    return fw_spec.anchor_ports(part) if part else []


def part_role_for_node(graph, by_id, node_id):
    edge = next((edge for edge in graph['edges']
                 if edge.get('to') == node_id and edge.get('in') == 'image'), None)
    source = by_id.get(edge.get('from')) if edge else None
    output = ((source or {}).get('result') or {}).get('output') or {}
    part_name = str(output.get('partName') or '')
    role = fw_spec.role_for_node(node_id, part_name)
    if not role:
        raise ValueError('PART_ROLE_MISSING: 无法从节点 %s 判断部件角色' % node_id)
    return role
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fw_pipeline.SpecPipelineTest -v`
Expected: `OK` (4 tests).

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_fw_pipeline -v`. Do not commit.

---

### Task 6: `execute_local` 的 blueprint 结果、partImage 端口、partModel fit 钩子

**Files:**
- Modify: `tools/fw_pipeline.py`
- Test: `tests/test_fw_pipeline.py`

**Interfaces:**
- Consumes: `spec_for_node`、`ports_for_node`、`part_role_for_node`、`_load_provider_config`、`resolve_output`、`pipeline_root`、`_digest`。
- Produces:
  - `_fit_with_blender(blender_path, plan) -> dict`
  - `_fit_is_current(forgeworks_root, asset_id, kind, node, spec) -> bool`
  - `_fit_part_model(forgeworks_root, asset_id, kind, graph, by_id, node_id, blender_path) -> dict`
  - `_attach_part_ports(...) -> None`
  - `execute_local` 在 `partModel` 任务成功且接了 spec 时写 `fit`/`ports`/`assembly`；`partImage` 成功时写 `role`/`ports`；`blueprint` 成功时复制 `task.output` 到节点输出。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fw_pipeline.py` before `if __name__ == '__main__':`:

```python
class SpecExecutionTest(unittest.TestCase):
    def _graph(self, spec):
        return {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'blueprint', 'type': 'blueprint', 'params': {'overallLengthM': 7.2},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'spec_1', 'state': 'success',
                     'output': {'spec': spec, 'specPath': 'spec.json'}}}},
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_body', 'state': 'success',
                     'output': {'imagePath': 'outputs/body.png'}},
                     'output': {'partName': '车身'}}},
                {'id': 'partModel_body', 'type': 'partModel', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'model_body', 'state': 'success',
                     'output': {'modelPath': 'outputs/model_body.glb'}}}},
            ],
            'edges': [
                {'from': 'blueprint', 'out': 'spec', 'to': 'partImage_body', 'in': 'spec'},
                {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
                {'from': 'partImage_body', 'out': 'image', 'to': 'partModel_body', 'in': 'image'},
                {'from': 'partImage_body', 'out': 'ports', 'to': 'partModel_body', 'in': 'ports'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'partModel_body', 'in': 'spec'},
            ],
        }

    def _fake_fit_report(self):
        return {
            'valid': True,
            'fit': {'mode': 'uniform', 'scale': 1.0, 'scalePerAxis': [1.0, 1.0, 1.0],
                    'aspectError': 0.02, 'rotationDeg': [0, 0, 0], 'grounded': False,
                    'ambiguous': False,
                    'measuredBbox': {'min': [-2.1, -0.8, -0.7], 'max': [2.1, 0.8, 0.7]}},
            'ports': [{'id': 'boom_base', 'type': 'pin', 'anchorNorm': [0.62, 0.5, 0.7],
                       'pos': [0.504, 0.0, 0.28], 'axis': [1, 0, 0],
                       'normal': [0, 0, 1], 'radiusM': 0.08}],
            'triangles': 1200,
        }

    def _prepare(self, directory, spec):
        fw_pipeline.save_graph(directory, 'M1', self._graph(spec), kind='machine')
        outputs = Path(fw_pipeline.pipeline_root(directory, 'M1')) / 'outputs'
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / 'model_body.glb').write_bytes(b'glb')
        return outputs

    def test_blueprint_output_is_copied_to_node_result(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            blueprint = next(node for node in result['graph']['nodes']
                             if node['id'] == 'blueprint')
            self.assertEqual(blueprint['result']['output']['spec']['assetId'], 'M1')

    def test_part_image_gets_role_and_anchor_ports_from_spec(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            part_image = next(node for node in result['graph']['nodes']
                              if node['id'] == 'partImage_body')
            self.assertEqual(part_image['result']['output']['role'], 'body')
            self.assertEqual(part_image['result']['output']['ports'][0]['id'], 'boom_base')
            self.assertNotIn('pos', part_image['result']['output']['ports'][0])

    def test_part_model_fit_writes_ports_assembly_and_report(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()):
                result = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                   blender_path='blender')
            node = next(node for node in result['graph']['nodes']
                        if node['id'] == 'partModel_body')
            output = node['result']['output']
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(output['role'], 'body')
            self.assertAlmostEqual(output['fit']['scale'], 1.0)
            self.assertEqual(output['assembly']['assemblyId'], 'asm_partModel_body')
            self.assertEqual(output['assembly']['connectors'][0]['id'], 'body:boom_base')
            self.assertEqual(output['assembly']['parts'][0]['role'], 'body')

    def test_part_model_fit_is_cached_by_task_and_spec_hash(self):
        spec = fw_spec.template_spec('M1')
        with tempfile.TemporaryDirectory() as directory:
            outputs = self._prepare(directory, spec)
            with mock.patch.object(fw_pipeline, '_fit_with_blender',
                                   return_value=self._fake_fit_report()) as fit:
                first = fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                                  blender_path='blender')
                fw_pipeline.save_graph(directory, 'M1', first['graph'], kind='machine')
                (outputs / 'model_fit_partModel_body.glb').write_bytes(b'glb')
                fw_pipeline.execute_local(directory, 'M1', kind='machine',
                                          blender_path='blender')
            self.assertEqual(fit.call_count, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_pipeline.SpecExecutionTest -v`
Expected: FAIL because `execute_local` does not copy blueprint output, attach ports, or call `_fit_with_blender`.

- [ ] **Step 3: Write minimal implementation**

In `tools/fw_pipeline.py`:

1. Add `FIT_TIMEOUT`, `_fit_with_blender`, `_attach_part_ports`, `_single_part_assembly`, `_fit_is_current`, `_fit_part_model` before `execute_local`:

```python
FIT_TIMEOUT = 300


def _fit_with_blender(blender_path, plan):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fw_blender.py')
    with tempfile.TemporaryDirectory(prefix='forgeworks-fit-') as temp_dir:
        plan_path = os.path.join(temp_dir, 'fit.json')
        report_path = os.path.join(temp_dir, 'report.json')
        with open(plan_path, 'w', encoding='utf-8') as stream:
            json.dump(plan, stream, ensure_ascii=False)
        try:
            completed = subprocess.run([
                blender_path, '--background', '--factory-startup', '--python-exit-code', '1',
                '--python', script, '--', '--mode', 'fit', '--plan', plan_path,
                '--output', plan['output'], '--report', report_path,
            ], capture_output=True, text=True, timeout=FIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ValueError('Blender 校准超时（%d 秒）' % FIT_TIMEOUT)
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
        return report


def _attach_part_ports(forgeworks_root, asset_id, kind, graph, by_id, node_id):
    spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    if not spec:
        return
    node = by_id[node_id]
    result = node.setdefault('result', {})
    output = result.setdefault('output', {})
    role = fw_spec.role_for_node(node_id, output.get('partName') or '')
    part = spec['parts'].get(role)
    if not part:
        raise ValueError('PART_ROLE_MISSING: spec 中没有角色 %s' % (role or node_id))
    output['role'] = role
    output['ports'] = fw_spec.anchor_ports(part)


def _single_part_assembly(asset_id, node_id, role, mesh_path, ports):
    connectors = []
    for port in ports:
        connectors.append({
            'id': '%s:%s' % (role, port.get('id')),
            'owner': role,
            'frame': {'pos': list(port.get('pos') or [0, 0, 0]),
                      'axis': list(port.get('axis') or [1, 0, 0]),
                      'normal': list(port.get('normal') or [0, 0, 1])},
            'radiusM': port.get('radiusM', 0.02),
        })
    return {
        'schemaVersion': 1,
        'assemblyId': 'asm_' + node_id,
        'assetId': asset_id,
        'meshPath': mesh_path,
        'parts': [{'partId': node_id, 'role': role, 'meshPath': mesh_path}],
        'connectors': connectors,
        'mates': [],
        'warnings': [],
    }


def _fit_is_current(forgeworks_root, asset_id, kind, node, spec):
    result = node.get('result') or {}
    task = result.get('providerTask') or {}
    output = result.get('output') or {}
    mesh_path = output.get('meshPath')
    if not mesh_path or output.get('fitSourceTaskId') != task.get('taskId'):
        return False
    if output.get('fitSpecHash') != _digest(spec):
        return False
    return bool(resolve_output(forgeworks_root, asset_id, kind,
                               os.path.basename(str(mesh_path))))


def _fit_part_model(forgeworks_root, asset_id, kind, graph, by_id, node_id, blender_path):
    node = by_id[node_id]
    result = node.setdefault('result', {})
    task = result.get('providerTask') or {}
    task_output = task.get('output') if isinstance(task.get('output'), dict) else {}
    model_path = task_output.get('modelPath')
    if not model_path:
        raise ValueError('SPEC_MISSING: 单件模型没有可校准的 GLB')
    source = resolve_output(forgeworks_root, asset_id, kind, os.path.basename(str(model_path)))
    if not source:
        raise ValueError('SPEC_MISSING: 单件模型文件不存在：%s' % model_path)
    if not blender_path:
        raise ValueError('未找到 Blender：请在 tools/bridge_config.json 配置 blender.path')
    spec = spec_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    role = part_role_for_node(graph, by_id, node_id)
    part = spec['parts'].get(role)
    if not part:
        raise ValueError('PART_ROLE_MISSING: spec 中没有角色 %s' % role)
    params = node.get('params') or {}
    fit_mode = str(params.get('fitMode') or 'uniform')
    ground = bool(params.get('ground'))
    ports = ports_for_node(forgeworks_root, asset_id, kind, graph, by_id, node_id)
    root = pipeline_root(forgeworks_root, asset_id, kind)
    outputs_dir = os.path.join(root, 'outputs')
    os.makedirs(outputs_dir, exist_ok=True)
    filename = 'model_fit_%s.glb' % node_id
    output = os.path.join(outputs_dir, filename)
    plan = {
        'input': source,
        'output': output,
        'targetSizeM': list(part['sizeM']),
        'fitMode': fit_mode,
        'ground': ground,
        'forward': part.get('forward', '+X'),
        'ports': ports,
    }
    report = _fit_with_blender(blender_path, plan)
    if not report.get('valid'):
        raise ValueError('FIT_ASPECT_MISMATCH: %s'
                         % ('; '.join(report.get('errors') or []) or 'Blender 校准失败'))
    fit = dict(report.get('fit') or {})
    if fit_mode == 'uniform' and float(fit.get('aspectError') or 0) > 0.15:
        raise ValueError('FIT_ASPECT_MISMATCH: 均匀校准无法消除长宽高差异（%.1f%%）'
                         % (float(fit['aspectError']) * 100))
    warnings = []
    if float(fit.get('aspectError') or 0) > 0.05:
        warnings.append('校准后仍有 %.1f%% 轴向偏差' % (float(fit['aspectError']) * 100))
    if fit.get('ambiguous'):
        warnings.append('FIT_ORIENTATION_AMBIGUOUS: 多个朝向评分接近，请检查 rotationDeg')
    fit['targetSizeM'] = list(part['sizeM'])
    fit['forward'] = part.get('forward', '+X')
    fit['fitMode'] = fit_mode
    relative = 'outputs/' + filename
    fitted_ports = report.get('ports') or []
    assembly = _single_part_assembly(asset_id, node_id, role, relative, fitted_ports)
    assembly['warnings'] = warnings
    output_data = result.setdefault('output', {})
    output_data.update({
        'role': role,
        'meshPath': relative,
        'fit': fit,
        'ports': fitted_ports,
        'assembly': assembly,
        'fitSourceTaskId': task.get('taskId'),
        'fitSpecHash': _digest(spec),
        'engine': 'blender',
        'updatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    })
    result['state'] = 'done'
    result.pop('error', None)
    return output_data
```

2. Replace the beginning of the `for node_id in order:` provider branch with:

```python
        if node['type'] in PROVIDER_TYPES:
            node.setdefault('result', {})
            task = node['result'].get('providerTask') or {}
            if task.get('state') == 'success':
                # 保留 dirty：上游或参数变了，旧产物不能当作现成结果
                if node['result'].get('state') != 'dirty':
                    node['result']['state'] = 'done'
                task_output = task.get('output') if isinstance(task.get('output'), dict) else {}
                if node['type'] == 'blueprint' and isinstance(task_output.get('spec'), dict):
                    node['result']['output'] = dict(node['result'].get('output') or {},
                                                    spec=task_output['spec'],
                                                    specPath=task_output.get('specPath', 'spec.json'))
                if node['type'] == 'partImage':
                    try:
                        _attach_part_ports(forgeworks_root, asset_id, kind, graph, by_id, node_id)
                    except ValueError as error:
                        node['result'].setdefault('warnings', []).append(str(error))
                if node['type'] == 'partModel':
                    try:
                        part_spec = spec_for_node(forgeworks_root, asset_id, kind,
                                                  graph, by_id, node_id)
                    except ValueError as error:
                        node['result']['state'] = 'blocked'
                        node['result']['error'] = str(error)
                        part_spec = None
                    if part_spec and not _fit_is_current(forgeworks_root, asset_id, kind,
                                                         node, part_spec):
                        try:
                            _fit_part_model(forgeworks_root, asset_id, kind, graph,
                                            by_id, node_id, blender_path)
                        except (ValueError, OSError) as error:
                            node['result']['state'] = 'blocked'
                            node['result']['error'] = str(error)
            elif task.get('state') in ('queued', 'running'):
                node['result']['state'] = task['state']
            else:
                node['result']['state'] = 'blocked'
                node['result']['error'] = '远程生成未执行：请在配置 Provider 密钥后由用户主动发起'
            continue
```

Also update the write-back guard inside `with _graph_lock(root):` so derived outputs from provider nodes are merged without letting local execution overwrite the provider task. Replace the existing block:

```python
            # 远程任务的状态由 submit/poll 维护；本地运行不覆盖正在等待/已完成的任务
            if computed['type'] in PROVIDER_TYPES:
                current_task = (current.get('result') or {}).get('providerTask') or {}
                if current_task:
                    continue
```

with:

```python
            # 远程任务的状态由 submit/poll 维护；本地运行只合并派生产物，不覆盖任务本身
            if computed['type'] in PROVIDER_TYPES:
                current_task = (current.get('result') or {}).get('providerTask') or {}
                if current_task:
                    computed_result = computed.get('result') or {}
                    derived = (computed_result.get('output')
                               if isinstance(computed_result.get('output'), dict) else {})
                    if derived:
                        current_result = current.setdefault('result', {})
                        current_result['output'] = dict(current_result.get('output') or {},
                                                        **derived)
                        changed = True
                    continue
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_fw_pipeline.SpecExecutionTest -v`
Expected: `OK` (4 tests).

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_fw_pipeline -v`. Do not commit.

---

### Task 7: Bridge `blueprint` 提交与 `partImage` 端口注入

**Files:**
- Modify: `tools/bridge.py`
- Test: `tests/test_bridge_providers.py`

**Interfaces:**
- Consumes: `fw_spec`、`fw_providers.analyze_spec`、`fw_pipeline.pipeline_root`、`resolve_output`。
- Produces:
  - `PROVIDER_NODE_TYPES` 包含 `blueprint`。
  - `POST /api/pipeline/provider/submit` 对 `blueprint` 同步返回 `output.spec`/`output.specPath`，任务 id 为 `spec_<sha1前16位>`，并写 `<asset>/pipeline/spec.json`。
  - `partImage` 节点输出增加 `role`、`ports`；`_part_image_prompt(text, part=None)` 可附加目标尺寸。

- [ ] **Step 1: Write the failing test**

Append a new class to `tests/test_bridge_providers.py` before `if __name__ == '__main__':`:

```python
class BlueprintBridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []
        created = bridge.create_project(str(self.workspace), '规格工程')
        self.root = Path(created['fwDir'])
        self.server = bridge.Bridge(('127.0.0.1', 0), bridge.BridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self.pipeline = Path(fw_pipeline.pipeline_root(str(self.root), 'M1', 'machine'))
        (self.pipeline / 'outputs').mkdir(parents=True, exist_ok=True)
        (self.pipeline / 'outputs' / 'overall.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        self.spec = fw_spec.template_spec('M1')
        self.graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'blueprint', 'type': 'blueprint',
                 'params': {'provider': 'ark', 'overallLengthM': 7.2,
                            'template': 'excavator'}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {'provider': 'ark'},
                 'result': {'output': {'partName': '车身'}}},
            ],
            'edges': [
                {'from': 'overall', 'out': 'image', 'to': 'blueprint', 'in': 'image'},
                {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
            ],
        }
        fw_pipeline.save_graph(str(self.root), 'M1', self.graph, kind='machine')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.tmp.cleanup()

    def _post(self, route, payload):
        request = urllib.request.Request(
            self.origin + '/api/' + route,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Origin': self.origin},
            method='POST')
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            return json.loads(error.read())

    def test_blueprint_requires_confirm_remote(self):
        with mock.patch.object(bridge.fw_providers, 'analyze_spec') as analyze:
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint'})
        self.assertFalse(result['ok'])
        self.assertIn('确认', result['error'])
        analyze.assert_not_called()

    def test_blueprint_writes_spec_and_node_output(self):
        def fake(config, image_path, parts, prompt='', model='', overall_length=0.0,
                 template='excavator'):
            return {'parts': {}, 'connections': []}, {'model': 'vision', 'notes': ''}

        with mock.patch.object(bridge.fw_providers, 'analyze_spec', side_effect=fake):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'blueprint',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        self.assertTrue((self.pipeline / 'spec.json').is_file())
        graph = fw_pipeline.load_graph(str(self.root), 'M1', kind='machine')
        node = next(node for node in graph['nodes'] if node['id'] == 'blueprint')
        self.assertEqual(node['result']['state'], 'done')
        self.assertEqual(node['result']['output']['spec']['assetId'], 'M1')
        self.assertTrue(node['result']['providerTask']['taskId'].startswith('spec_'))

    def test_part_image_gets_ports_from_spec_input(self):
        graph = {
            'schemaVersion': 1, 'assetId': 'M1', 'revision': 0,
            'nodes': [
                {'id': 'overall', 'type': 'textToImage', 'params': {},
                 'result': {'state': 'done', 'providerTask': {
                     'taskId': 'img_1', 'state': 'success',
                     'output': {'imagePath': 'outputs/overall.png'}}}},
                {'id': 'blueprint', 'type': 'blueprint', 'params': {},
                 'result': {'state': 'done', 'output': {'spec': self.spec,
                                                        'specPath': 'spec.json'}}},
                {'id': 'prompt_body', 'type': 'prompt', 'params': {'text': '车身'}},
                {'id': 'partImage_body', 'type': 'partImage', 'params': {'provider': 'ark'},
                 'result': {'output': {'partName': '车身'}}},
            ],
            'edges': [
                {'from': 'overall', 'out': 'image', 'to': 'partImage_body', 'in': 'image'},
                {'from': 'prompt_body', 'out': 'text', 'to': 'partImage_body', 'in': 'text'},
                {'from': 'blueprint', 'out': 'spec', 'to': 'partImage_body', 'in': 'spec'},
            ],
        }
        fw_pipeline.save_graph(str(self.root), 'M1', graph, kind='machine')

        def fake_submit(config, kind, params, prompt='', input_task_id=None,
                        image_data=None, fallback=False):
            return {'taskId': 'img_body', 'provider': 'ark', 'state': 'success',
                    'output': {}}

        with mock.patch.object(bridge.fw_providers, 'submit', side_effect=fake_submit):
            result = self._post('pipeline/provider/submit', {
                'assetId': 'M1', 'kind': 'machine', 'nodeId': 'partImage_body',
                'confirmRemote': True})
        self.assertTrue(result['ok'], result)
        node = next(node for node in result['graph']['nodes']
                    if node['id'] == 'partImage_body')
        self.assertEqual(node['result']['output']['role'], 'body')
        self.assertEqual(node['result']['output']['ports'][0]['id'], 'boom_base')
        self.assertNotIn('pos', node['result']['output']['ports'][0])
```

Add `import fw_spec` at the top of `tests/test_bridge_providers.py` next to the existing `fw_pipeline` import.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_bridge_providers.BlueprintBridgeTest -v`
Expected: FAIL with `目标节点不是受支持的远程生成节点` and no spec writing.

- [ ] **Step 3: Write minimal implementation**

In `tools/bridge.py`:

1. Load `fw_spec` beside the existing importlib loaders:

```python
_spec_spec = importlib.util.spec_from_file_location('fw_spec', os.path.join(ROOT, 'tools', 'fw_spec.py'))
fw_spec = importlib.util.module_from_spec(_spec_spec)
_spec_spec.loader.exec_module(fw_spec)
```

2. Extend the provider node tuple:

```python
PROVIDER_NODE_TYPES = ('textToImage', 'imageTo3D', 'partImage', 'partModel', 'blueprint')
```

3. Add helpers near `_part_reference_image`:

```python
def _upstream_image_path(root, asset_id, kind, incoming, nodes):
    edge = next((edge for edge in incoming if edge.get('in') == 'image'), None)
    if not edge:
        raise ValueError('尺寸规格需要整机效果图：请把整体效果图节点连到 image 口')
    source = nodes.get(edge.get('from')) or {}
    result = source.get('result') or {}
    provider = result.get('providerTask') if isinstance(result.get('providerTask'), dict) else {}
    task_output = provider.get('output') if isinstance(provider.get('output'), dict) else {}
    image_path = task_output.get('imagePath') or (result.get('output') or {}).get('imagePath')
    absolute = fw_pipeline.resolve_output(
        root, asset_id, kind, os.path.basename(str(image_path or '')))
    if not absolute:
        raise ValueError('整机效果图文件不可用，无法生成尺寸规格')
    return absolute


def _spec_from_incoming(root, asset_id, kind, nodes, incoming):
    edge = next((edge for edge in incoming if edge.get('in') == 'spec'), None)
    if not edge:
        return None
    output = ((nodes.get(edge.get('from')) or {}).get('result') or {}).get('output') or {}
    candidate = output.get('spec')
    if isinstance(candidate, dict):
        return fw_spec.validate_spec(candidate)
    path = output.get('specPath')
    if path:
        try:
            return fw_spec.read_spec(os.path.join(
                fw_pipeline.pipeline_root(root, asset_id, kind), str(path)))
        except (OSError, ValueError):
            return None
    return None
```

4. Change `_part_image_prompt`:

```python
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
```

5. In the provider submit route, after `params = node.get('params') or {}` and before `prompt = ''`, insert the blueprint branch:

```python
                if node['type'] == 'blueprint':
                    root = fw_pipeline.pipeline_root(fw_dir(), asset_id, kind)
                    spec_path = os.path.join(root, 'spec.json')
                    if bool(params.get('specLocked')) and os.path.isfile(spec_path):
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
                        raw, meta = fw_providers.analyze_spec(
                            read_json(CONFIG_FILE, {}) or {}, image_path,
                            [{'name': role, 'description': ''}
                             for role in fw_spec.PART_ROLES],
                            prompt=prompt_text or str(params.get('prompt') or ''),
                            overall_length=overall, template=template)
                        spec = fw_spec.from_vision(raw, overall_length_m=overall,
                                                   template=template, asset_id=asset_id)
                        digest = hashlib.sha1(json.dumps(
                            spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
                        task = {'taskId': 'spec_' + digest, 'provider': 'ark',
                                'state': 'success', 'requestType': 'blueprint',
                                'output': {'spec': spec, 'specPath': 'spec.json'}}
                    applied = {}

                    def apply_blueprint(latest):
                        latest_nodes, _ = fw_pipeline.validate_graph(latest)
                        latest_node = latest_nodes.get(node_id)
                        if not latest_node or latest_node.get('type') != 'blueprint':
                            raise ValueError('提交期间节点已被删除或修改')
                        fw_spec.write_spec(spec_path, spec)
                        state = latest_node.setdefault('result', {})
                        previous = state.get('providerTask')
                        if previous:
                            history = (state.get('history') or [])[-(PIPELINE_HISTORY_LIMIT - 1):]
                            state['history'] = history + [previous]
                        state['providerTask'] = task
                        state['output'] = {'spec': spec, 'specPath': 'spec.json'}
                        state['state'] = 'done'
                        state.pop('error', None)
                        applied['state'] = 'done'
                        return latest

                    result = fw_pipeline.update_graph(fw_dir(), asset_id, kind, apply_blueprint)
                    push_event('pipeline.progress', {'id': asset_id, 'nodeId': node_id,
                                                     'state': 'done', 'taskId': task['taskId']})
                    self._json({'ok': True, 'graph': result, 'task': task,
                                'taskId': task['taskId'], 'state': 'done'})
                    return
```

6. In the existing `partImage` branch, read the spec and pass the part:

```python
                        part_name = _part_name_from_prompt(prompt) or str(node_id)
                        spec_input = _spec_from_incoming(fw_dir(), asset_id, kind,
                                                         nodes, incoming)
                        role = fw_spec.role_for_node(node_id, part_name)
                        part_spec = ((spec_input or {}).get('parts') or {}).get(role) or {}
                        ports = fw_spec.anchor_ports(part_spec) if part_spec else []
                        prompt = _part_image_prompt(prompt, part_spec)
```

7. In `apply_latest`, extend the output assignment:

```python
                    if part_name:
                        extra = {'partName': part_name}
                        if spec_input:
                            extra.update(role=role, ports=ports)
                        state['output'] = dict(state.get('output') or {}, **extra)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_bridge_providers.BlueprintBridgeTest -v`
Expected: `OK` (3 tests).

- [ ] **Step 5: Checkpoint**

Run: `python -m unittest tests.test_bridge_providers -v`. Do not commit.

---

### Task 8: 前端镜像、静态回归与全量验证

**Files:**
- Modify: `js/pipeline.js`
- Modify: `css/pipeline.css`
- Test: `tests/test_fw_pipeline.py`（静态镜像测试）、`node --check`

**Interfaces:**
- Consumes: 现有 `PIPELINE_PORTS`、`PIPELINE_NODE_LABELS`、`pipelineParamForm`、`pipelineNodeCard`、`pipelineSubmitRemote`、`pipelineApi`。
- Produces: `blueprint` 节点、`spec`/`ports`/`assembly` 端口、blueprint 参数表单、spec/ports/fit 结果面板。

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fw_pipeline.py` before `if __name__ == '__main__':`:

```python
class FrontendMirrorTest(unittest.TestCase):
    def test_frontend_mirrors_p1_nodes_and_ports(self):
        source = (ROOT / 'js' / 'pipeline.js').read_text(encoding='utf-8')
        compact = ''.join(source.split())
        for expected in (
            "blueprint:{in:['image','text'],out:['spec']}",
            "partImage:{in:['text','image','spec'],out:['image','ports']}",
            "partModel:{in:['image','spec','ports'],out:['part','mesh','assembly']}",
            "blueprint:'尺寸规格'",
        ):
            self.assertIn(expected, compact)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_fw_pipeline.FrontendMirrorTest -v`
Expected: FAIL because `blueprint` is missing from the frontend.

- [ ] **Step 3: Write minimal implementation**

In `js/pipeline.js`:

1. Add the label and port definitions:

```js
const PIPELINE_NODE_LABELS = {
  prompt:'描述词', textToImage:'概念图生成', imageTo3D:'图生 3D', decimate:'减面',
  partImage:'单件效果图', partModel:'单件模型', assemble:'组装',
  blueprint:'尺寸规格',
  styleApply:'风格对齐', uv:'UV 展开', lod:'LOD 分级', collision:'碰撞体',
  animation:'动画', metadata:'元数据', validate:'质量门禁', manualEdit:'人工精修',
  variant:'变体', export:'导出', imageExport:'图标导出'
};
```

```js
const PIPELINE_PORTS = {
  prompt:{out:['text']}, textToImage:{in:['text'],out:['image']}, imageTo3D:{in:['image'],out:['mesh']},
  blueprint:{in:['image','text'],out:['spec']},
  decimate:{in:['mesh'],out:['mesh','part']},
  partImage:{in:['text','image','spec'],out:['image','ports']},
  partModel:{in:['image','spec','ports'],out:['part','mesh','assembly']},
  assemble:{in:['text','part','image'],out:['mesh']},
  styleApply:{in:['mesh'],out:['mesh']},
  uv:{in:['mesh'],out:['mesh']}, lod:{in:['mesh'],out:['mesh']}, collision:{in:['mesh'],out:['mesh']},
  animation:{in:['mesh'],out:['mesh']}, metadata:{in:['mesh'],out:['mesh']},
  validate:{in:['mesh'],out:['report']}, manualEdit:{in:['mesh'],out:['mesh']},
  variant:{in:['mesh'],out:['mesh']}, export:{in:['mesh','report']}, imageExport:{in:['image']}
};
```

2. Add `blueprint` to the three provider node arrays with these exact replacements.

   Replace the offline branch condition (line 1003):

   ```js
   }else if(['textToImage','imageTo3D','partImage','partModel','blueprint'].includes(node.type)){
   ```

   Replace the `pipelineSubmitRemote` guard (line 1172):

   ```js
   if(!node || !['textToImage','imageTo3D','partImage','partModel','blueprint'].includes(node.type)) return;
   ```

   Replace the remote-button condition in `pipelineNodeCard` (line 1673):

   ```js
   ${['textToImage','imageTo3D','partImage','partModel','blueprint'].includes(node.type)?`<button data-remote="${pipelineEscape(node.id)}">远程提交</button>${showPoll?`<button data-poll="${pipelineEscape(node.id)}">查询任务</button>`:''}`:''}
   ```

3. Add the blueprint parameter form at the top of `pipelineParamForm`:

```js
  if(node.type === 'blueprint'){
    return `<div class="pipeline-params">
      ${pipelineParamSelect(node, 'provider', '平台', [{value:'ark',label:'Ark'}], 'ark')}
      ${pipelineParamNumber(node, 'overallLengthM', '整机长度（m）', 'min="0" step="0.1"', '')}
      ${pipelineParamSelect(node, 'template', '机型模板', [{value:'excavator',label:'挖掘机'}], 'excavator')}
      ${pipelineParamText(node, 'prompt', '额外视觉提示', '')}
      ${pipelineParamCheck(node, 'specLocked', '锁定现有规格', false)}
      <small class="pipeline-params-hint">调用一次 Ark 视觉模型生成 spec.json；整机长度是绝对尺寸锚，模板补全其余部件。锁定后重跑只校验现有 spec，不再请求 Provider。</small>
    </div>`;
  }
```

4. In `pipelineSubmitRemote`, treat blueprint as a vision request:

```js
  if(!node || !['textToImage','imageTo3D','partImage','partModel','blueprint'].includes(node.type)) return;
  const imageNode=node.type==='textToImage'||node.type==='partImage';
  const visionNode=node.type==='blueprint';
  const model=provider==='ark'?(visionNode?'Doubao Vision':(imageNode?'Seedream 5.0 Pro':'Seed3D 2.0')):(imageNode?'Seedream v5':'v3.1');
```

5. Add a result-panel helper before `pipelineNodeCard`:

```js
function pipelineSpecPanel(node, output){
  const own = (node.result && node.result.output) || {};
  output = Object.assign({}, output || {}, own);
  if(node.type==='blueprint' && output && output.spec){
    const parts=output.spec.parts||{};
    const rows=Object.entries(parts).map(([role,part])=>{
      const size=(part.sizeM||[]).map(value=>Number(value).toFixed(2)).join(' × ');
      const confidence=part.confidence!=null?` · ${Math.round(Number(part.confidence)*100)}%`:'';
      return `<li>${pipelineEscape(role)} · ${pipelineEscape(size)} m${confidence}</li>`;
    }).join('');
    return `<details class="pipeline-spec"><summary>尺寸规格 · ${Object.keys(parts).length} 件</summary><ul>${rows}</ul><pre>${pipelineEscape(JSON.stringify(output.spec,null,2))}</pre></details>`;
  }
  if(node.type==='partImage' && Array.isArray(output.ports) && output.ports.length){
    return `<div class="pipeline-ports">${output.ports.map(port=>`<span>${pipelineEscape(port.id)} · ${pipelineEscape(port.type||'pin')}</span>`).join('')}</div>`;
  }
  if(node.type==='partModel' && output.fit){
    const fit=output.fit;
    const rotation=(fit.rotationDeg||[]).map(value=>Math.round(Number(value))).join('/');
    return `<div class="pipeline-fit">校准 ${Number(fit.scale||0).toFixed(3)}× · 偏差 ${(Number(fit.aspectError||0)*100).toFixed(1)}% · 旋转 ${pipelineEscape(rotation)}°</div>`;
  }
  return '';
}
```

6. In `pipelineNodeCard`, replace the template line that currently reads:

   ```js
       <small>${pipelineEscape(node.id)}${progress!=null?' · '+progress+'%':''}</small>${params}${media}${stageSummary?`<small class="pipeline-stage">${pipelineEscape(stageSummary)}</small>`:''}
   ```

   with:

   ```js
       <small>${pipelineEscape(node.id)}${progress!=null?' · '+progress+'%':''}</small>${params}${media}${pipelineSpecPanel(node,taskOutput)}${stageSummary?`<small class="pipeline-stage">${pipelineEscape(stageSummary)}</small>`:''}
   ```

7. Add styles to `css/pipeline.css`:

```css
.pipeline-spec,
.pipeline-fit,
.pipeline-ports {
  margin-top: 8px;
  font-size: 12px;
  color: inherit;
  opacity: .85;
}
.pipeline-spec summary { cursor: pointer; }
.pipeline-spec ul { margin: 6px 0; padding-left: 18px; }
.pipeline-spec pre {
  max-height: 180px;
  overflow: auto;
  font-size: 11px;
  white-space: pre-wrap;
}
.pipeline-ports { display: flex; flex-wrap: wrap; gap: 6px; }
.pipeline-ports span {
  border: 1px solid currentColor;
  border-radius: 999px;
  padding: 1px 8px;
  opacity: .8;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
node --check js/pipeline.js
python -m unittest tests.test_fw_pipeline.FrontendMirrorTest -v
```
Expected: `node --check` exits 0 with no output; unittest `OK`.

- [ ] **Step 5: Run the full P1 verification**

Run:

```bash
python -m unittest tests.test_fw_spec tests.test_fw_providers tests.test_fw_blender tests.test_fw_pipeline tests.test_bridge_providers tests.test_fw_parts -v
node --check js/pipeline.js
```

Expected:
- `test_fw_spec`: 17 tests pass.
- `test_fw_providers`, `test_fw_pipeline`, `test_bridge_providers`, `test_fw_parts`: all pass; legacy tests unchanged.
- `test_fw_blender`: passes when Blender is available; otherwise the fit class skips. Record the skip explicitly.
- `node --check`: exit 0.

Do not commit. Report exact counts and any skip.

---

## Self-Review

**Spec coverage (P1):**
- `fw_spec.py` schema/validation/templates/ports/fit/mate tree → Tasks 1, 2.
- `fw_providers.analyze_spec` → Task 3.
- `fw_blender.py` fit → Task 4.
- `fw_pipeline.py` node types, blueprint output, partImage ports, partModel fit hook → Tasks 5, 6.
- `bridge.py` blueprint confirm/落盘 and partImage ports → Task 7.
- `js/pipeline.js` + `css/pipeline.css` nodes/ports/params/result panels → Task 8.
- Old `assemble`/snap unchanged → `tests/test_fw_parts.py` in Task 8 full run; no `fw_parts.py` edits.
- Security/confirm gate/no real calls → Global Constraints, Task 3 mock, Task 7 confirm test.
- Error codes → Tasks 1, 2, 5, 6, 7.
- P2 `threeView` and P3 `mate`/decimate-assembly are intentionally out of this plan; their node types are not added here so the graph validator never accepts an unimplemented branch. `build_mate_tree` is a pure helper already tested here; P3 will wire it to `/api/pipeline/spec/chain`.

**Placeholder scan:** every step contains a concrete test, command, or code block. No TBD/TODO/"similar to".

**Type consistency:** `spec` keys use `parts[role].ports[].anchor` in spec JSON; `ports` results use `anchorNorm`/`pos`; `fw_spec.anchor_ports` converts between them. `fit` uses `scale`, `scalePerAxis`, `aspectError`, `rotationDeg`. `assembly.meshPath` is relative POSIX. `blueprint` task id is `spec_<16 hex>`. All function names in later tasks match earlier definitions.

**Known environment note:** Windows `python3` is a broken Store alias; all commands use `python`. Blender tests may skip when `FW_BLENDER` is unset; the skip is not a code failure.
