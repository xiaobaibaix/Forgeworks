# 管线产物自动回填资产并导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provider 生成成功后，浏览器端自动把图片/GLB 写回对应资产（机器 / 物品 / 元素），落盘到项目 `_Source`，并在配置了 UE 目标时自动导出。

**Architecture:** 继续采用“前端产文件、Bridge 落盘”的既有链路。浏览器轮询到任务成功后，`pipeline-adopt.js` 直接复用 `/api/export/asset` 写入 `icon` / `mesh`（machines 额外写 `preview`），随后复用 `project/publish` 自动导出 UE。机器 AI GLB 在 `viewer3d.js` 中替换程序化几何，整体变换保存在 `machine.model.transform`；`/api/export/asset` 改为按 role 合并 manifest，避免图标与模型互相覆盖。

**Tech Stack:** 原生 JS（非 ES module，`file://` 可直接打开）、three.js r147 vendored UMD（GLTFLoader / GLTFExporter / BufferGeometryUtils）、Python 3 Bridge、unittest、headless Edge smoke。

**Spec:** `docs/superpowers/specs/2026-10-24-pipeline-auto-adopt-export-design.md`

## Global Constraints

- 所有前端脚本保持非 module、全局函数风格，`file://` 下可直接运行；不得引入构建步骤或新依赖。
- three.js 固定使用仓库内 r147 vendored 文件（`js/vendor/three.min.js` 等）。
- 不新增 Provider API，不新增或改写现有 Provider 路由；只消费轮询已拿到的 `task.output.imagePath` / `task.output.modelPath`。
- 所有 Bridge 请求必须同源；`pipelineOutputURLFor` 只输出 basename，禁止路径穿越。
- 复用现有 `/api/export/asset` 与 `/api/project/publish`，不得新增旁路写盘端点。
- 不删除、不回滚项目里既有文件；导出失败只记录错误，不清理已写文件。
- 资产图标 128×128（`<ID>_icon.png` 供 machine，`<ID>.png` 供 item/element）；导出图标 256×256；机器预览 512×512。
- 上传图标（`iconSource === 'upload'`）永远优先于生成图标；生成流程不得覆盖它。
- 机器使用 AI GLB 时整体替换程序化几何；只允许整体 position / rotation / scale，不支持单部件编辑。
- 自动执行依赖浏览器保持打开；以 `generated.*.taskId` 幂等，重复轮询不得重复写盘。
- 同一资产的自动应用串行执行（每资产一个 Promise 队列），失败写 `PIPELINE.applyErrors[id]`，不阻断其他资产。
- 脚本版本戳：Task 6 先统一为 `20261024a1`，Task 13 再全量改为 `20261024a2`（改 `index.html` / `tests/smoke.html` 时同步全部 `?v=`）。
- Git 只使用显式路径暂存；禁止 `git add -A` / `git add .`。不得提交未跟踪的 `tests/test_bridge_picker.py`。
- 每个 feature commit 末尾必须包含 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。

## File Structure

**Create**

- `js/engines/glb.js` — 独立 GLB 读写与适配工具：加载、计算/应用整体变换、渲染缩略图、烘焙 GLB、统计三角面与材质、变换归一化。
- `js/pipeline-adopt.js` — 轮询成功后的资产落地编排：幂等检查、图片裁剪、GLB 缩略图、写资产状态、调用导出与 UE 发布、刷新导出节点。

**Modify**

- `tools/bridge.py` — `export_asset` 的 `files` / `meta` 按 role 合并，不再整体覆盖。
- `tools/fw_project.py` — item 的 UE 导出角色增加 `mesh`，`required` 仍为 `icon`。
- `tools/fw_pipeline.py` — `export` 节点根据 `_Sync/manifest.json` 判定 `done` / `blocked`。
- `js/core/state.js` — `normalizeAssets` 覆盖三种资产；新增 `normalizeModelTransform` / `normalizeAIModel`。
- `js/ui/editor.js` — 保存时合并旧对象并写 `iconSource`；机器图标与模型区块、物品 AI 模型区块、元素来源标签。
- `js/views/editor3d.js` — AI 模型整体变换面板、撤销/重做、适配占地、重置变换、恢复程序化几何。
- `js/engines/viewer3d.js` — AI GLB 加载与替换、缩略图、AI `toGLB`、查看器状态/按钮。
- `js/sync.js` — 机器/物品/元素哈希加入图标与模型；AI 模型导出与生成图标质量策略。
- `js/pipeline.js` — `pipelineOutputURLFor`、轮询/提交成功钩子、应用状态、卡片按钮、模板默认值。
- `js/views/machines.js` — 机器列表使用自定义/生成图标，AI 徽标与“变换”入口。
- `js/views/assets.js` — 物品 AI 徽标、元素生成图标标签。
- `index.html` / `tests/smoke.html` — 引入新脚本并统一版本戳。
- `tests/test_bridge_projects.py` / `tests/test_fw_project.py` / `tests/test_fw_pipeline.py` — 后端回归。

---

### Task 0: 预提交既有目录选择器修复

**Files:**
- Modify: `tools/bridge.py`（仅工作区中已有的 picker 修复）

**Interfaces:**
- Consumes: 无
- Produces: 干净的 `tools/bridge.py` 基线，后续 Task 1 的 diff 只包含 manifest 合并。

- [ ] **Step 1: 确认工作区 diff 只包含 picker 修复**

Run:
```bash
git diff -- tools/bridge.py
```
Expected: 只有 `pick_folder()` 中 Windows PowerShell owner 窗口与非零退出错误上报的改动；没有 `export_asset` 相关修改。

- [ ] **Step 2: 单独提交该修复**

```bash
git add tools/bridge.py
git commit -m "fix(bridge): Windows 目录选择器置顶并暴露 PowerShell 错误

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 3: 确认未跟踪测试文件仍未入库**

Run:
```bash
git status --short
```
Expected: `?? tests/test_bridge_picker.py` 仍在列表中；不要 `git add` 它。

---

### Task 1: Bridge 导出按 role 合并 manifest

**Files:**
- Modify: `tools/bridge.py:1357-1370`
- Test: `tests/test_bridge_projects.py`（追加 `BridgeExportMergeTest`）

**Interfaces:**
- Consumes: `bridge.create_project(path, name) -> {'fwDir': str, ...}`；`bridge.export_asset(kind, asset_id, files, meta) -> {'ok': bool, ...}`。
- Produces: 同一资产多次导出时，`manifest['assets'][id]['files']` 与 `['meta']` 都保留历史 role；后续 Task 10/11 依赖“图标导出不抹掉 mesh，模型导出不抹掉 icon”。

- [ ] **Step 1: 写失败测试**

在 `tests/test_bridge_projects.py` 末尾、`if __name__ == '__main__':` 之前追加：

```python
class BridgeExportMergeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.old_state = dict(bridge._state)
        self.old_state_file = bridge.STATE_FILE
        bridge.STATE_FILE = str(self.workspace / 'bridge-state.json')
        bridge._state.clear()
        bridge._state['recentProjects'] = []
        created = bridge.create_project(str(self.workspace), '导出合并')
        self.root = Path(created['fwDir'])
        self.old_find_blender = bridge.find_blender
        self.old_queue = bridge._queue_blender_check
        self.old_push = bridge.push_event
        self.queued = []
        bridge.find_blender = lambda: '/fake/blender'
        bridge._queue_blender_check = lambda *args: self.queued.append(args)
        bridge.push_event = lambda kind, data=None: None

    def tearDown(self):
        bridge.find_blender = self.old_find_blender
        bridge._queue_blender_check = self.old_queue
        bridge.push_event = self.old_push
        bridge._state.clear()
        bridge._state.update(self.old_state)
        bridge.STATE_FILE = self.old_state_file
        self.temp.cleanup()

    @staticmethod
    def _file(path, payload=b'x'):
        return {'path': path, 'b64': base64.b64encode(payload).decode('ascii')}

    def test_icon_then_mesh_keeps_both_roles_and_meta(self):
        first = bridge.export_asset(
            'machine', 'M1',
            {'icon': self._file('M1_icon.png', b'\x89PNG\r\n\x1a\n')},
            {'name': '钻机', 'iconHash': 'i1', 'iconSource': 'generated'})
        self.assertTrue(first['ok'], first)
        second = bridge.export_asset(
            'machine', 'M1',
            {'mesh': self._file('M1.glb', b'glTF')},
            {'name': '钻机', 'modelHash': 'm1'})
        self.assertTrue(second['ok'], second)
        record = bridge.load_manifest()['assets']['M1']
        self.assertEqual(sorted(record['files']), ['icon', 'mesh'])
        self.assertEqual(record['meta']['iconHash'], 'i1')
        self.assertEqual(record['meta']['iconSource'], 'generated')
        self.assertEqual(record['meta']['modelHash'], 'm1')
        self.assertEqual(len(self.queued), 1)

    def test_mesh_then_icon_preserves_mesh(self):
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'mesh': self._file('M1.glb', b'glTF')}, {'name': '钻机'})['ok'])
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'\x89PNG\r\n\x1a\n')},
            {'name': '钻机', 'iconHash': 'i2'})['ok'])
        record = bridge.load_manifest()['assets']['M1']
        self.assertEqual(sorted(record['files']), ['icon', 'mesh'])
        self.assertEqual(record['files']['mesh'][0]['path'], 'M1.glb')

    def test_same_role_replaces_old_entry(self):
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'old')}, {'name': '钻机'})['ok'])
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'new')}, {'name': '钻机'})['ok'])
        record = bridge.load_manifest()['assets']['M1']
        self.assertEqual(len(record['files']['icon']), 1)
        with open(self.root / record['sourceDir'] / 'M1_icon.png', 'rb') as stream:
            self.assertEqual(stream.read(), b'new')

    def test_icon_only_machine_does_not_queue_blender(self):
        self.assertTrue(bridge.export_asset(
            'machine', 'M1', {'icon': self._file('M1_icon.png', b'\x89PNG\r\n\x1a\n')},
            {'name': '钻机'})['ok'])
        self.assertEqual(self.queued, [])
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
python tests/test_bridge_projects.py BridgeExportMergeTest -v
```
Expected: `test_icon_then_mesh_keeps_both_roles_and_meta` 与 `test_mesh_then_icon_preserves_mesh` FAIL（`files` 只剩最后一次的 role）；其余两个可能已通过。

- [ ] **Step 3: 实现合并**

把 `tools/bridge.py` 中 `with _manifest_lock:` 至 `save_manifest(mf)` 一段替换为：

```python
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
```

注意：`save_tool_baseline`、冲突检测、`push_event` 全部保持原样。`rec['files']` 里旧 role 的条目路径来自旧 `sourceDir`；本功能不移动已存在资产目录，因此路径仍有效。

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
python tests/test_bridge_projects.py BridgeExportMergeTest -v
```
Expected: 4 tests PASS。

- [ ] **Step 5: 跑全量 Python 回归**

Run:
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
Expected: 全部 PASS（`tests/test_bridge_picker.py` 若因环境缺少依赖而失败，记录但不修改该文件）。

- [ ] **Step 6: 提交**

```bash
git add tools/bridge.py tests/test_bridge_projects.py
git commit -m "fix(bridge): 资产导出按 role 合并 manifest

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 物品 UE 导出支持 mesh

**Files:**
- Modify: `tools/fw_project.py:21`
- Test: `tests/test_fw_project.py`（修改 `_write_item`，追加两个测试）

**Interfaces:**
- Consumes: `fw_project.publish_to_ue(fw_root, ue_root, ids=None) -> {'ok','published','errors',...}`。
- Produces: `UE_EXPORT_ROLES['item'] == ('icon', 'mesh')`；item 的 manifest 可含 `mesh`，但 `required` 仍是 `icon`，只有图标的物品继续可发布。

- [ ] **Step 1: 扩展测试夹具**

把 `tests/test_fw_project.py` 的 `_write_item` 替换为：

```python
def _write_item(root, asset_id='I1', icon=True, mesh=False):
    manifest_file = root / '_Sync' / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    meta = {'name': '铁矿石', 'type': 'raw', 'iconHash': 'h1'}
    files = {'icon': [{'path': asset_id + '.png', 'sha1': 'icon-sha1', 'size': 8}]}
    if mesh:
        files['mesh'] = [{'path': asset_id + '.glb', 'sha1': 'mesh-sha1', 'size': 4}]
    manifest['assets'][asset_id] = {
        'kind': 'item',
        'state': 'exported',
        'files': files,
        'meta': meta,
    }
    source_dir = fw_project.asset_source_dir(root, 'item', asset_id, meta, manifest)
    manifest['assets'][asset_id]['sourceDir'] = source_dir
    base = root / source_dir
    base.mkdir(parents=True, exist_ok=True)
    if icon:
        (base / (asset_id + '.png')).write_bytes(b'\x89PNG\r\n\x1a\n')
    if mesh:
        (base / (asset_id + '.glb')).write_bytes(b'glTF')
    (base / 'prompt.txt').write_text('铁矿石描述词', encoding='utf-8')
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    return manifest
```

- [ ] **Step 2: 追加失败测试**

在 `tests/test_fw_project.py` 的 `PublishToUETest` 末尾追加：

```python
    def test_publish_item_with_mesh_copies_both_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_item(fw, 'I1', mesh=True)
            ue = workspace / 'UE'
            ue.mkdir()

            result = fw_project.publish_to_ue(fw, ue, ['I1'])
            self.assertTrue(result['ok'], result)
            exported = ue / 'Forgeworks' / '_Source' / '物品' / '图标' / '铁矿石'
            self.assertTrue((exported / 'I1.png').is_file())
            self.assertTrue((exported / 'I1.glb').is_file())
            manifest = json.loads(
                (ue / 'Forgeworks' / '_Sync' / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(manifest['assets']['I1']['files']), ['icon', 'mesh'])

    def test_publish_item_with_mesh_but_no_icon_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fw = Path(fw_project.create_project(directory, 'FW')['root'])
            _write_item(fw, 'I3', icon=False, mesh=True)
            ue = workspace / 'UE'
            ue.mkdir()

            result = fw_project.publish_to_ue(fw, ue, ['I3'])
            self.assertFalse(result['ok'])
            self.assertEqual(result['errors'][0]['id'], 'I3')
```

- [ ] **Step 3: 运行测试确认失败**

Run:
```bash
python tests/test_fw_project.py PublishToUETest -v
```
Expected: `test_publish_item_with_mesh_copies_both_roles` FAIL（`I1.glb` 未复制）；`test_publish_item_with_mesh_but_no_icon_fails` 已通过就是异常信号，需确认失败原因确实是缺 icon。

- [ ] **Step 4: 修改角色表**

把 `tools/fw_project.py:21` 改为：

```python
UE_EXPORT_ROLES = {'machine': ('mesh', 'icon'), 'item': ('icon', 'mesh'), 'element': ('icon',)}
```

`_publish_asset` 不需要改：`required = roles[0]` 仍然是 `icon`，`copied` 只包含实际存在的 role。

- [ ] **Step 5: 运行测试确认通过**

Run:
```bash
python tests/test_fw_project.py -v
```
Expected: 全部 PASS，包括既有的 `test_publish_includes_item_icons_without_internal_files`（默认 `mesh=False`，仍只有 `icon`）。

- [ ] **Step 6: 提交**

```bash
git add tools/fw_project.py tests/test_fw_project.py
git commit -m "feat(project): 物品导出支持附带 GLB 网格

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 管线导出节点读取 manifest 状态

**Files:**
- Modify: `tools/fw_pipeline.py:231-288`
- Test: `tests/test_fw_pipeline.py`（追加 `PipelineExportNodeTest`）

**Interfaces:**
- Consumes: `fw_pipeline.save_graph(root, asset_id, graph, kind)`；`fw_pipeline.execute_local(root, asset_id, target_id=None, through=False, kind='machine')`。
- Produces: `export` 节点在 manifest 满足角色要求时 `result.state == 'done'`，`result.output = {'sourceDir','files','exportedAt'}`；否则 `blocked`。`pipeline.js` 的卡片与 `pipeline-adopt.js` 的刷新只读这个结果。

- [ ] **Step 1: 写失败测试**

在 `tests/test_fw_pipeline.py` 末尾、`if __name__ == '__main__':` 之前追加：

```python
def _write_manifest(root, assets):
    sync = Path(root) / '_Sync'
    sync.mkdir(parents=True, exist_ok=True)
    (sync / 'manifest.json').write_text(
        json.dumps({'schemaVersion': 1, 'assets': assets}, ensure_ascii=False),
        encoding='utf-8')


def _export_graph(asset_id):
    return {
        'schemaVersion': 1,
        'assetId': asset_id,
        'revision': 0,
        'nodes': [{'id': 'export', 'type': 'export', 'x': 0, 'y': 0, 'params': {}}],
        'edges': [],
    }


class PipelineExportNodeTest(unittest.TestCase):
    def test_machine_export_done_when_mesh_and_icon_present(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'M1': {
                'kind': 'machine', 'sourceDir': '_Source/机器/钻机',
                'files': {
                    'mesh': [{'path': 'M1.glb'}],
                    'icon': [{'path': 'M1_icon.png'}],
                },
                'exportedAt': '2026-10-24T00:00:00Z',
            }})
            fw_pipeline.save_graph(directory, 'M1', _export_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'done')
            self.assertEqual(node['result']['output']['sourceDir'], '_Source/机器/钻机')
            self.assertEqual(node['result']['output']['files']['mesh'], ['M1.glb'])
            self.assertEqual(node['result']['output']['exportedAt'], '2026-10-24T00:00:00Z')

    def test_machine_export_blocked_without_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'M1': {
                'kind': 'machine',
                'files': {'mesh': [{'path': 'M1.glb'}]},
            }})
            fw_pipeline.save_graph(directory, 'M1', _export_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'blocked')
            self.assertIn('尚未导出到项目', node['result']['error'])

    def test_item_export_done_with_icon_only(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'I1': {
                'kind': 'item',
                'files': {'icon': [{'path': 'I1.png'}]},
                'exportedAt': '2026-10-24T00:00:00Z',
            }})
            fw_pipeline.save_graph(directory, 'I1', _export_graph('I1'), kind='item')
            result = fw_pipeline.execute_local(directory, 'I1', kind='item')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'done')

    def test_element_export_done_with_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_manifest(directory, {'Fe': {
                'kind': 'element',
                'files': {'icon': [{'path': 'Fe.png'}]},
                'exportedAt': '2026-10-24T00:00:00Z',
            }})
            fw_pipeline.save_graph(directory, 'Fe', _export_graph('Fe'), kind='element')
            result = fw_pipeline.execute_local(directory, 'Fe', kind='element')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'done')

    def test_export_blocked_without_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            fw_pipeline.save_graph(directory, 'M1', _export_graph('M1'), kind='machine')
            result = fw_pipeline.execute_local(directory, 'M1', kind='machine')
            node = next(n for n in result['graph']['nodes'] if n['type'] == 'export')
            self.assertEqual(node['result']['state'], 'blocked')
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
python tests/test_fw_pipeline.py PipelineExportNodeTest -v
```
Expected: `done` 相关测试 FAIL（当前 export 永远 `blocked`）。

- [ ] **Step 3: 实现 manifest 读取与节点判定**

在 `tools/fw_pipeline.py` 的 `_manifest_source_dir` 后面新增：

```python
def _manifest_asset(forgeworks_root, asset_id, kind):
    try:
        with open(os.path.join(forgeworks_root, '_Sync', 'manifest.json'), encoding='utf-8') as stream:
            manifest = json.load(stream)
    except (OSError, ValueError):
        return {}
    record = (manifest.get('assets') or {}).get(asset_id)
    if not isinstance(record, dict) or record.get('kind') != kind:
        return {}
    return record
```

在 `execute_local` 中，把 `imageExport` 分支之后、通用 `else` 之前插入：

```python
        elif node['type'] == 'export':
            result = node.setdefault('result', {})
            record = _manifest_asset(forgeworks_root, asset_id, kind)
            files = record.get('files') if isinstance(record.get('files'), dict) else {}
            required = ('mesh', 'icon') if kind == 'machine' else ('icon',)
            missing = [role for role in required if not files.get(role)]
            if record and not missing:
                result['state'] = 'done'
                result['output'] = {
                    'sourceDir': record.get('sourceDir'),
                    'files': {
                        role: [item.get('path') for item in files[role] if isinstance(item, dict)]
                        for role in required
                    },
                    'exportedAt': record.get('exportedAt'),
                }
            else:
                result['state'] = 'blocked'
                result['error'] = '尚未导出到项目；请先完成生成与同步导出'
```

然后删除 `execute_local` 循环末尾原有的：

```python
        if node['type'] == 'export':
            node['result']['state'] = 'blocked'
            node['result']['error'] = '导出需通过同步导出流程并满足 validate 门禁'
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
python tests/test_fw_pipeline.py -v
```
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add tools/fw_pipeline.py tests/test_fw_pipeline.py
git commit -m "feat(pipeline): 导出节点按 manifest 判定完成状态

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 资产字段归一化（三种资产 + AI 变换）

**Files:**
- Modify: `js/core/state.js:12-31`
- Test: `tests/smoke.html`（追加同步 check）

**Interfaces:**
- Consumes: `loadState()` 与 `normalizeAssets(target)` 的既有启动顺序；`state.js` 在 `three.min.js` 之前加载，因此这里不能依赖 `THREE` 或 `glb.js`。
- Produces: `normalizeModelTransform(transform) -> {position:{x,y,z},rotation:{x,y,z},scale:{x,y,z}}`；`normalizeAIModel(model) -> null | {source:'ai',provider,file,taskId,nodeId,generatedAt,triangles,autoFit,transform}`；保证 `S.elements/items/machines` 都有 `icon`、`iconSource`、`generated`。后续 `glb.js`/`viewer3d.js`/`sync.js` 都依赖这些字段存在。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 末尾（`check('Markdown 生成'...)` 之后、`}` 之前）追加：

```js
    check('资产字段补全 · 三种资产图标与模型', function(){
      var tmp = {
        elements:[{id:'E1'}],
        items:[{id:'I1'}],
        machines:[{id:'M1', model:{source:'ai', transform:{position:{x:2}, scale:{y:3}}, autoFit:false}}],
        recipes:[], techs:[]
      };
      normalizeAssets(tmp);
      if(tmp.elements[0].icon !== '' || tmp.elements[0].iconSource !== '') return '元素图标字段未补全';
      if(!tmp.elements[0].generated || tmp.elements[0].model !== undefined) return '元素 generated/model 未归一化';
      if(tmp.items[0].model !== null) return '物品非 AI 模型应为 null';
      if(!tmp.items[0].generated) return '物品 generated 未补全';
      var m = tmp.machines[0];
      if(m.icon !== '' || m.iconSource !== '') return '机器图标字段未补全';
      if(m.model.source !== 'ai' || m.model.autoFit !== false) return 'AI 模型字段未保留';
      var t = m.model.transform;
      if(t.position.x !== 2 || t.position.z !== 0) return '位置归一化错误';
      if(t.scale.x !== 1 || t.scale.y !== 3) return '缩放归一化错误';
      if(t.rotation.y !== 0) return '旋转归一化错误';
      return '三种资产字段一致';
    });
    check('AI 模型变换默认值', function(){
      var t = normalizeModelTransform(null);
      return t.position.x === 0 && t.position.y === 0 && t.position.z === 0 &&
             t.rotation.x === 0 && t.rotation.y === 0 && t.rotation.z === 0 &&
             t.scale.x === 1 && t.scale.y === 1 && t.scale.z === 1 ? 'ok' : '默认值错误';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run:
```bash
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless --no-sandbox \
  --use-gl=swiftshader --enable-unsafe-swiftshader --virtual-time-budget=8000 --dump-dom \
  "file:///F:/workspace/ue/Forgeworks/tests/smoke.html" > /tmp/smoke.html
sed -n '/SELFTEST_JSON_START/,/SELFTEST_JSON_END/p' /tmp/smoke.html
```
Expected: `资产字段补全` 与 `AI 模型变换默认值` FAIL（`normalizeModelTransform is not defined`）。

- [ ] **Step 3: 实现归一化**

把 `js/core/state.js` 的 `normalizeAssets` 整体替换为：

```js
function normalizeAssets(target){
  ['elements','items','machines','recipes','techs'].forEach(k=>{
    if(!Array.isArray(target[k])) target[k]=[];   // MCP 可能只写入部分集合
  });
  (target.elements||[]).forEach(el=>{
    if(typeof el.icon !== 'string') el.icon = '';
    if(typeof el.iconSource !== 'string') el.iconSource = '';
    if(!el.generated || typeof el.generated !== 'object') el.generated = {};
    delete el.model;                                                  // 元素不生成 3D 模型
  });
  (target.items||[]).forEach(it=>{
    if(typeof it.icon !== 'string') it.icon = '';
    if(typeof it.mesh !== 'string') it.mesh = '';
    if(typeof it.mat !== 'string') it.mat = '';
    if(typeof it.visual !== 'string') it.visual = '';
    if(!it.modelStatus) it.modelStatus = defaultModelStatus(it.visual || it.type);
    if(typeof it.iconSource !== 'string') it.iconSource = '';
    if(!it.generated || typeof it.generated !== 'object') it.generated = {};
    it.model = normalizeAIModel(it.model);
  });
  (target.machines||[]).forEach(m=>{
    if(typeof m.icon !== 'string') m.icon = '';
    if(typeof m.iconSource !== 'string') m.iconSource = '';
    if(!m.generated || typeof m.generated !== 'object') m.generated = {};
    m.model = normalizeAIModel(m.model);
  });
}

/** 只保留 AI 模型；旧数据或程序化模型返回 null */
function normalizeAIModel(model){
  if(!model || model.source !== 'ai') return null;
  return {
    source: 'ai',
    provider: typeof model.provider === 'string' ? model.provider : '',
    file: typeof model.file === 'string' ? model.file : '',
    taskId: typeof model.taskId === 'string' ? model.taskId : '',
    nodeId: typeof model.nodeId === 'string' ? model.nodeId : '',
    generatedAt: typeof model.generatedAt === 'string' ? model.generatedAt : '',
    triangles: Number.isFinite(Number(model.triangles)) ? Number(model.triangles) : 0,
    autoFit: model.autoFit !== false,
    transform: normalizeModelTransform(model.transform),
  };
}

/** 整体变换补全；ratio 轴缺省为 1，位移/旋转缺省为 0 */
function normalizeModelTransform(transform){
  const t = transform || {};
  const axis = (value, fallback)=>{
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  };
  const p = t.position || {}, r = t.rotation || {}, s = t.scale || {};
  return {
    position: {x:axis(p.x,0), y:axis(p.y,0), z:axis(p.z,0)},
    rotation: {x:axis(r.x,0), y:axis(r.y,0), z:axis(r.z,0)},
    scale:    {x:axis(s.x,1), y:axis(s.y,1), z:axis(s.z,1)},
  };
}
```

- [ ] **Step 4: 运行 smoke 确认通过**

Run: 同 Step 2 命令。
Expected: 两个新 check 通过，`summary.fail == 0`。

- [ ] **Step 5: 提交**

```bash
git add js/core/state.js tests/smoke.html
git commit -m "feat(state): 归一化资产图标与 AI 模型字段

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 编辑器保存合并旧对象并记录图标来源

**Files:**
- Modify: `js/ui/editor.js:323-379`（并在文件内新增两个辅助函数）
- Test: `tests/smoke.html`（追加同步 check）

**Interfaces:**
- Consumes: `S`、`modalState`、`saveState()`、`closeModal()`、`render()`；图标区 `#iconPrev` 的 `dataset.pending` / `dataset.cleared` 约定。
- Produces: `editorIconValue(coll, id) -> {icon: string, iconSource: ''|'upload'}`；`mergeEditorRecord(existing, patch) -> object`；保存后旧字段（`ui3d`、`generated`、`model`）不会丢失，机器/物品/元素都写 `iconSource`。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('编辑器保存保留旧字段', function(){
      var merged = mergeEditorRecord(
        {id:'M1', name:'旧', ui3d:{parts:{a:{}}}, model:{source:'ai'}, generated:{model:{taskId:'t'}}},
        {id:'M1', name:'新', icon:'', iconSource:''});
      if(merged.name !== '新') return '新值未覆盖';
      if(!merged.ui3d || !merged.ui3d.parts.a) return 'ui3d 丢失';
      if(!merged.model || merged.model.source !== 'ai') return 'model 丢失';
      if(!merged.generated || merged.generated.model.taskId !== 't') return 'generated 丢失';
      return 'ok';
    });
    check('编辑器图标来源标记', function(){
      var host = document.createElement('div');
      host.innerHTML = '<div id="iconPrev" data-pending="data:image/png;base64,AA"></div>';
      document.body.appendChild(host);
      var value = editorIconValue('machines', 'NOT_EXIST');
      host.remove();
      return value.icon === 'data:image/png;base64,AA' && value.iconSource === 'upload'
        ? 'ok' : '来源标记错误';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 两个新 check FAIL（`mergeEditorRecord is not defined`）。

- [ ] **Step 3: 新增辅助函数**

在 `js/ui/editor.js` 的 `commitEditor` 之前加入：

```js
/** 读取图标区的待提交值，并标记来源 */
function editorIconValue(coll, id){
  const prev = document.getElementById('iconPrev');
  const existing = (S[coll] || []).find(x=>x.id===id) || {};
  if(prev && prev.dataset.pending) return {icon: prev.dataset.pending, iconSource: 'upload'};
  if(prev && prev.dataset.cleared) return {icon: '', iconSource: ''};
  return {icon: existing.icon || '', iconSource: existing.iconSource || ''};
}

/** 编辑保存时保留未在表单里出现的字段（ui3d / generated / model 等） */
function mergeEditorRecord(existing, patch){
  return existing ? Object.assign({}, existing, patch) : patch;
}
```

- [ ] **Step 4: 修改 commitEditor 的图标读取与合并**

元素分支替换为：

```js
  if(coll==='elements'){
    const iconState = editorIconValue('elements', id);
    obj={id:g('id').trim(),name:g('name').trim(),symbol:g('symbol').trim(),
      color:g('color').trim(),tier:+g('tier'),
      icon:iconState.icon,iconSource:iconState.iconSource};
  }
```

物品分支替换为：

```js
  else if(coll==='items'){
    const iconState = editorIconValue('items', id);
    obj={id:g('id').trim(),name:g('name').trim(),tier:+g('tier'),
      type:g('type'),value:+g('value')||0,color:g('color').trim(),desc:g('desc'),
      icon:iconState.icon,iconSource:iconState.iconSource,
      mesh:(g('mesh')||'').trim(),
      mat:(g('mat')||'').trim(),
      modelStatus:g('modelStatus')||'primitive'};
  }
```

机器分支替换为：

```js
  else if(coll==='machines'){
    const iconState = editorIconValue('machines', id);
    obj={id:g('id').trim(),name:g('name').trim(),cat:g('cat'),
      tier:+g('tier'),footprint:g('footprint').trim(),power:+g('power')||0,desc:g('desc'),
      icon:iconState.icon,iconSource:iconState.iconSource};
  }
```

末尾合并替换为：

```js
  if(isNew){ S[coll].push(obj); }
  else {
    const arr = S[coll];
    const i = arr.findIndex(x=>x.id===id);
    if(i >= 0){
      obj = mergeEditorRecord(arr[i], obj);
      arr[i] = obj;
    }else{
      S[coll].push(obj);
    }
  }
  saveState(); closeModal(); clearCostCache(); clearIconCache(); render(); toast('已保存');
```

- [ ] **Step 5: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令（脚本尚未加版本戳变更，不必先改）。
Expected: 两个新 check 通过；其余 check 不回归。

- [ ] **Step 6: 提交**

```bash
git add js/ui/editor.js tests/smoke.html
git commit -m "fix(editor): 保存时保留资产扩展字段并记录图标来源

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 独立 GLB 工具 `js/engines/glb.js`

**Files:**
- Create: `js/engines/glb.js`
- Modify: `index.html`（脚本列表）、`tests/smoke.html`（脚本列表 + check）
- Test: `tests/smoke.html`

**Interfaces:**
- Consumes: `THREE`（r147）、`THREE.GLTFLoader`、`THREE.GLTFExporter`、`parseFootprint(footprint) -> [w,d]`。
- Produces（全部为全局函数）：
  - `fwNormalizeTransform(transform) -> {position,rotation,scale}`（与 `normalizeModelTransform` 同结构）
  - `fwApplyGLBTransform(object, transform) -> void`
  - `fwLoadGLBScene(arrayBuffer) -> Promise<THREE.Object3D>`
  - `fwComputeFitTransform(object, kind, footprint) -> transform`
  - `fwRenderGLBThumbnail(scene, transform, size) -> dataURL`
  - `fwBakeGLBScene(scene, transform, userData, callback(buffer, error)) -> void`
  - `fwCountTriangles(root) -> number`、`fwCountMaterials(root) -> number`

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('GLB 工具已加载', function(){
      return typeof fwLoadGLBScene === 'function' &&
             typeof fwBakeGLBScene === 'function' &&
             typeof fwRenderGLBThumbnail === 'function' ? 'ok' : '未加载';
    });
    check('GLB 适配变换 · 机器占地', function(){
      if(typeof fwComputeFitTransform !== 'function') return '未加载';
      var mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 4));
      var t = fwComputeFitTransform(mesh, 'machine', '4×2');
      if(Math.abs(t.scale.x - 0.5) > 1e-6) return '缩放=' + t.scale.x;
      if(Math.abs(t.position.y - 0.25) > 1e-6) return '未贴地 y=' + t.position.y;
      return Math.abs(t.position.x) < 1e-6 && Math.abs(t.position.z) < 1e-6 ? 'ok' : '未居中';
    });
    check('GLB 适配变换 · 物品等比', function(){
      var mesh = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 4));
      var t = fwComputeFitTransform(mesh, 'item', '');
      if(Math.abs(t.scale.x - 0.25) > 1e-6) return '缩放=' + t.scale.x;
      return Math.abs(t.position.y - 0.125) < 1e-6 ? 'ok' : '未贴地 y=' + t.position.y;
    });
    check('GLB 变换归一化', function(){
      var t = fwNormalizeTransform({position:{x:'2'}, scale:{z:3}});
      return t.position.x === 2 && t.position.y === 0 && t.scale.x === 1 && t.scale.z === 3
        ? 'ok' : '默认值错误';
    });
```

- [ ] **Step 2: 引入脚本并运行 smoke 确认失败**

在 `index.html` 的 `js/engines/viewer3d.js` 之前加入：

```html
<script src="js/engines/glb.js?v=20261024a1"></script>
```

在 `tests/smoke.html` 的第 4 组（`viewer3d.js` 之前）加入：

```html
<script src="../js/engines/glb.js?v=20261024a1"></script>
```

同时把两个文件里所有 `?v=20261023z2` 替换为 `?v=20261024a1`。

Run: Task 4 Step 2 的 smoke 命令。
Expected: 四个 GLB check FAIL（`fwLoadGLBScene is not defined`）。

- [ ] **Step 3: 实现 `js/engines/glb.js`**

```js
/* Forgeworks · js/engines/glb.js */
/* 独立 GLB 工具：不依赖 UI，供 viewer3d / pipeline-adopt 共用。 */
(function(){
  function axisNumber(value, fallback){
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function fwNormalizeTransform(transform){
    const t = transform || {};
    const p = t.position || {}, r = t.rotation || {}, s = t.scale || {};
    return {
      position: {x:axisNumber(p.x,0), y:axisNumber(p.y,0), z:axisNumber(p.z,0)},
      rotation: {x:axisNumber(r.x,0), y:axisNumber(r.y,0), z:axisNumber(r.z,0)},
      scale:    {x:axisNumber(s.x,1), y:axisNumber(s.y,1), z:axisNumber(s.z,1)},
    };
  }

  function fwApplyGLBTransform(object, transform){
    const t = fwNormalizeTransform(transform);
    object.position.set(t.position.x, t.position.y, t.position.z);
    object.rotation.set(t.rotation.x, t.rotation.y, t.rotation.z);
    object.scale.set(t.scale.x, t.scale.y, t.scale.z);
    object.updateMatrixWorld(true);
  }

  /** 解析 GLB 字节为 THREE 场景；失败时 reject Error */
  function fwLoadGLBScene(buffer){
    return new Promise(function(resolve, reject){
      if(!THREE.GLTFLoader){ reject(new Error('GLTFLoader 未加载')); return; }
      const loader = new THREE.GLTFLoader();
      loader.parse(buffer, '', function(gltf){
        const root = gltf.scene || (gltf.scenes && gltf.scenes[0]);
        if(!root){ reject(new Error('GLB 中没有场景')); return; }
        root.traverse(function(node){
          if(node.isMesh){
            node.castShadow = true;
            node.receiveShadow = true;
          }
        });
        resolve(root);
      }, function(error){
        reject(error instanceof Error ? error : new Error(String(error)));
      });
    });
  }

  /**
   * 计算整体变换：
   * - machine 等比缩放至占地内，底面贴地、水平居中；
   * - item 等比缩放至最长边 1，底面贴地、水平居中。
   */
  function fwComputeFitTransform(object, kind, footprint){
    const bbox = new THREE.Box3().setFromObject(object);
    if(bbox.isEmpty()) throw new Error('模型包围盒为空');
    const size = bbox.getSize(new THREE.Vector3());
    const center = bbox.getCenter(new THREE.Vector3());
    let scale = 1;
    if(kind === 'machine'){
      const fp = (typeof parseFootprint === 'function') ? parseFootprint(footprint) : [1, 1];
      const bw = Number(fp[0]) || 1, bd = Number(fp[1]) || 1;
      scale = Math.min(bw / (size.x || 1), bd / (size.z || 1)) || 1;
    }else{
      const maxDim = Math.max(size.x, size.y, size.z) || 1;
      scale = 1 / maxDim;
    }
    return {
      position: {x:-center.x * scale, y:-bbox.min.y * scale, z:-center.z * scale},
      rotation: {x:0, y:0, z:0},
      scale:    {x:scale, y:scale, z:scale},
    };
  }

  /** 透明背景缩略图；克隆场景避免把实时模型移出 viewer */
  function fwRenderGLBThumbnail(scene, transform, size){
    const px = Math.max(32, Math.round(size || 256));
    const canvas = document.createElement('canvas');
    canvas.width = px; canvas.height = px;
    const renderer = new THREE.WebGLRenderer({
      canvas: canvas, alpha: true, antialias: true, preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(1);
    renderer.setSize(px, px, false);
    renderer.setClearColor(0x000000, 0);
    if('outputEncoding' in renderer && THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;

    const renderScene = new THREE.Scene();
    const holder = new THREE.Group();
    holder.add(scene.clone(true));
    fwApplyGLBTransform(holder, transform);
    renderScene.add(holder);

    const bbox = new THREE.Box3().setFromObject(holder);
    const center = bbox.getCenter(new THREE.Vector3());
    const radius = bbox.getBoundingSphere(new THREE.Sphere()).radius || 1;
    const camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100);
    camera.position.copy(center).addScaledVector(
      new THREE.Vector3(1, 1.15, 1).normalize(), radius * 2.6);
    camera.lookAt(center);

    renderScene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.copy(center).add(new THREE.Vector3(radius, radius * 1.6, radius));
    renderScene.add(key);

    renderer.render(renderScene, camera);
    const url = canvas.toDataURL('image/png');
    renderer.dispose();
    return url;
  }

  /** 把整体变换与元数据烘焙进单文件 GLB；克隆避免影响实时场景 */
  function fwBakeGLBScene(scene, transform, userData, callback){
    if(!THREE.GLTFExporter){ callback(null, new Error('GLTFExporter 未加载')); return; }
    const holder = new THREE.Group();
    holder.name = (userData && userData.name) || 'AI_Model';
    holder.userData = Object.assign({}, userData || {});
    holder.add(scene.clone(true));
    fwApplyGLBTransform(holder, transform);
    const size = new THREE.Box3().setFromObject(holder).getSize(new THREE.Vector3());
    const extras = Object.assign({}, holder.userData.forgeworks || {}, {
      source: 'pipeline-ai',
      bounds: {x:+size.x.toFixed(3), y:+size.y.toFixed(3), z:+size.z.toFixed(3)},
    });
    holder.userData.forgeworks = extras;
    const exporter = new THREE.GLTFExporter();
    exporter.parse(holder, function(result){
      callback(result, null);
    }, function(error){
      callback(null, error instanceof Error ? error : new Error(String(error)));
    }, {binary: true, onlyVisible: true});
  }

  function fwCountTriangles(root){
    let total = 0;
    root.traverse(function(node){
      if(!node.isMesh || !node.geometry) return;
      const geometry = node.geometry;
      const position = geometry.attributes && geometry.attributes.position;
      if(geometry.index) total += geometry.index.count / 3;
      else if(position) total += position.count / 3;
    });
    return Math.round(total);
  }

  function fwCountMaterials(root){
    const seen = new Set();
    root.traverse(function(node){
      if(!node.isMesh || !node.material) return;
      (Array.isArray(node.material) ? node.material : [node.material]).forEach(function(mat){
        if(mat) seen.add(mat.uuid);
      });
    });
    return seen.size;
  }

  window.fwNormalizeTransform = fwNormalizeTransform;
  window.fwApplyGLBTransform = fwApplyGLBTransform;
  window.fwLoadGLBScene = fwLoadGLBScene;
  window.fwComputeFitTransform = fwComputeFitTransform;
  window.fwRenderGLBThumbnail = fwRenderGLBThumbnail;
  window.fwBakeGLBScene = fwBakeGLBScene;
  window.fwCountTriangles = fwCountTriangles;
  window.fwCountMaterials = fwCountMaterials;
})();
```

- [ ] **Step 4: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 四个 GLB check 通过，`summary.fail == 0`。

- [ ] **Step 5: 提交**

```bash
git add js/engines/glb.js index.html tests/smoke.html
git commit -m "feat(glb): 新增独立 GLB 适配、缩略图与烘焙工具

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: viewer3d 加载 AI GLB 并替换程序化几何

**Files:**
- Modify: `js/engines/viewer3d.js`（AI 状态、`applyLayers`、`loadAIModel`、`toGLB`、API、`open3DViewer`）
- Test: `tests/smoke.html`（异步 check）

**Interfaces:**
- Consumes: Task 6 的 `fwLoadGLBScene` / `fwComputeFitTransform` / `fwApplyGLBTransform` / `fwRenderGLBThumbnail` / `fwBakeGLBScene` / `fwCountTriangles` / `fwCountMaterials` / `fwNormalizeTransform`；`pipelineOutputURLFor(id, kind, file)`（Task 11 提供，运行期存在）；`machine.model`。
- Produces: `createViewer3D(...)` 返回值新增：
  - `whenModelReady() -> Promise<{ok:boolean, procedural:boolean, error?:string, size?:number}>`
  - `getAIModelInfo() -> null | {provider,taskId,file,triangles,materials}`
  - `getAIModelError() -> string|null`
  - `getAIModelTransform() -> transform|null`
  - `setAIModelTransform(transform) -> boolean`
  - `computeDefaultAIModelTransform() -> transform|null`
  - `toThumbnail(size) -> dataURL`（无 AI 时返回 `''`）
  - `getParts()` 在 AI 模式下返回 `[]`
  - `toGLB` 在 AI 模式下烘焙 AI 场景

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runAsync()` 中，`v._advance(0.2);` 之后加入：

```js
      out.checks.push({
        name: '查看器 AI API',
        ok: typeof v.whenModelReady === 'function' &&
            typeof v.getAIModelInfo === 'function' &&
            typeof v.setAIModelTransform === 'function' &&
            typeof v.computeDefaultAIModelTransform === 'function' &&
            typeof v.toThumbnail === 'function',
        detail: ''
      });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: `查看器 AI API` FAIL。

- [ ] **Step 3: 加入 AI 状态与图层隐藏**

在 `const group = new THREE.Group(); scene.add(group);` 之后、`const meshes = [];` 之前加入：

```js
  /* ---------- AI 模型（管线 GLB 替换程序化几何） ---------- */
  const aiRequested = !!(machine.model && machine.model.source === 'ai' && machine.model.file);
  let aiActive = false, aiHolder = null, aiScene = null, aiTransform = null;
  let aiInfo = null, aiError = null;
  let aiReadyResolve = null;
  const aiReady = new Promise(function(resolve){ aiReadyResolve = resolve; });
  if(!aiRequested) aiReadyResolve({ok:true, procedural:true});
```

在 `applyLayers()` 开头 `const layers = state.layers;` 之后加入：

```js
    if(group) group.visible = !aiActive;
```

把粒子两行改为：

```js
    if(emberPoints) emberPoints.visible = !aiActive && !!layers.particles;
    if(smokePoints) smokePoints.visible = !aiActive && !!layers.particles;
```

- [ ] **Step 4: 加载 AI 模型**

在 `resize();`（约 1129 行）之后加入：

```js
  function loadAIModel(){
    if(!aiRequested) return;
    const url = pipelineOutputURLFor(machine.id, 'machine', machine.model.file);
    fetch(url).then(function(response){
      if(!response.ok) throw new Error('模型文件不可用（HTTP ' + response.status + '）');
      return response.arrayBuffer();
    }).then(function(buffer){
      return fwLoadGLBScene(buffer);
    }).then(function(scene){
      aiScene = scene;
      aiHolder = new THREE.Group();
      aiHolder.name = machine.id + '_AI';
      aiHolder.add(scene);
      const saved = machine.model.autoFit === false ? machine.model.transform : null;
      aiTransform = saved ? fwNormalizeTransform(saved)
        : fwComputeFitTransform(scene, 'machine', machine.footprint);
      fwApplyGLBTransform(aiHolder, aiTransform);
      aiInfo = {
        provider: machine.model.provider || '',
        taskId: machine.model.taskId || '',
        file: machine.model.file || '',
        triangles: fwCountTriangles(scene),
        materials: fwCountMaterials(scene),
      };
      aiActive = true;
      scene.add(aiHolder);          // 不能挂在 group 下：group 在 AI 模式下会被隐藏
      applyLayers();
      placeCamera(HOME.yaw, HOME.pitch, HOME.dist);
      if(controls){ controls.target.copy(target); controls.update(); }
      aiReadyResolve({ok:true, procedural:false});
    }).catch(function(error){
      aiError = error && error.message ? error.message : String(error);
      aiActive = false;
      applyLayers();
      aiReadyResolve({ok:false, error:aiError, procedural:true});
    });
  }
  loadAIModel();
```

- [ ] **Step 5: 新增返回 API**

在 `return {` 内、`dispose:` 之前加入：

```js
    whenModelReady: function(){ return aiReady; },
    getAIModelInfo: function(){ return aiInfo ? Object.assign({}, aiInfo) : null; },
    getAIModelError: function(){ return aiError; },
    getAIModelTransform: function(){
      return aiTransform ? JSON.parse(JSON.stringify(aiTransform)) : null;
    },
    setAIModelTransform: function(transform){
      if(!aiHolder) return false;
      aiTransform = fwNormalizeTransform(transform);
      fwApplyGLBTransform(aiHolder, aiTransform);
      state.needsRender = true;
      return true;
    },
    computeDefaultAIModelTransform: function(){
      if(!aiScene) return null;
      aiTransform = fwComputeFitTransform(aiScene, 'machine', machine.footprint);
      return JSON.parse(JSON.stringify(aiTransform));
    },
    toThumbnail: function(size){
      if(!aiActive || !aiScene || !aiTransform) return '';
      return fwRenderGLBThumbnail(aiScene, aiTransform, size || 256);
    },
```

- [ ] **Step 6: 扩展 `getParts` / `reset` / `dispose`**

`getParts` 开头加入：

```js
      if(aiActive) return [];
```

`reset` 改为：

```js
    reset: function(){
      placeCamera(HOME.yaw, HOME.pitch, HOME.dist);
      if(controls){ controls.target.copy(target); controls.update(); }
    },
```

（AI 模式下相机 HOME 也已按占地设置，无需额外分支。）

`dispose` 中 `renderer.dispose();` 之前加入：

```js
      if(aiHolder && aiHolder.parent) aiHolder.parent.remove(aiHolder);
      if(aiScene){
        aiScene.traverse(function(node){
          if(!node.isMesh) return;
          if(node.geometry) node.geometry.dispose();
          const mats = Array.isArray(node.material) ? node.material : [node.material];
          mats.forEach(function(mat){
            if(!mat) return;
            ['map','normalMap','roughnessMap','metalnessMap','emissiveMap','alphaMap'].forEach(function(key){
              if(mat[key] && mat[key].dispose) mat[key].dispose();
            });
            mat.dispose();
          });
        });
      }
```

- [ ] **Step 7: `toGLB` 增加 AI 分支**

在 `toGLB: function(onDone){` 的 `if(!MergeUtils ...) return;` 之后加入：

```js
      if(aiActive && aiHolder && aiScene){
        const size = new THREE.Box3().setFromObject(aiHolder).getSize(new THREE.Vector3());
        fwBakeGLBScene(aiScene, aiTransform, {
          name: machine.id,
          forgeworks: {
            generator: 'Forgeworks',
            source: 'pipeline-ai',
            id: machine.id,
            name: machine.name,
            category: machine.cat,
            footprint: machine.footprint,
            tier: machine.tier,
            provider: (machine.model && machine.model.provider) || '',
            taskId: (machine.model && machine.model.taskId) || '',
            unit: 'meter (1 unit = 1 grid)',
            pivot: 'bottom-center',
          },
        }, function(result, error){
          if(error){ onDone(null, error); return; }
          onDone(result, null, {
            materials: aiInfo ? aiInfo.materials : fwCountMaterials(aiScene),
            vertices: 0,
            triangles: aiInfo ? aiInfo.triangles : fwCountTriangles(aiScene),
            sizeM: [ +size.x.toFixed(3), +size.y.toFixed(3), +size.z.toFixed(3) ],
            sizeCm: [ Math.round(size.x*100), Math.round(size.y*100), Math.round(size.z*100) ],
          });
        });
        return;
      }
```

- [ ] **Step 8: `open3DViewer` 增加 AI 状态与按钮文案**

在 canvas 覆盖层中，`v3Layers` 之前加入：

```html
        '<div id="v3AiStatus" style="display:none;position:absolute;right:12px;top:10px;font-size:11px;' +
             'color:#5f5e5a;background:rgba(255,255,255,.9);padding:4px 9px;border-radius:6px;' +
             'max-width:320px">加载 AI 模型…</div>' +
```

给底部说明 div 增加 `id`：

```html
        '<div id="v3Info" style="font-size:11.5px;color:var(--text-2);line-height:1.7">' +
```

在 `_activeViewer = V;` 之后加入：

```js
  if(m.model && m.model.source === 'ai'){
    const status = document.getElementById('v3AiStatus');
    status.style.display = 'block';
    status.textContent = '加载 AI 模型…';
    document.getElementById('v3Layers').style.display = 'none';
    const preset = document.getElementById('v3Preset');
    if(preset && preset.parentElement) preset.parentElement.style.display = 'none';
    document.getElementById('v3Parts').textContent = '变换模型';
    document.getElementById('v3Gen').textContent = '重新生成模型';
    V.whenModelReady().then(function(result){
      if(!result.ok){
        status.textContent = 'AI 模型加载失败：' + result.error + '（显示程序化几何）';
        return;
      }
      const info = V.getAIModelInfo() || {};
      status.textContent = 'AI 模型 · ' + (info.provider || 'provider') +
        (info.triangles ? ' · ' + info.triangles + ' 面' : '') +
        (info.materials ? ' · ' + info.materials + ' 材质' : '');
      document.getElementById('v3Aspects').innerHTML = '';
      document.getElementById('v3Info').textContent =
        'AI 生成模型；在“变换模型”中调整整体位置、旋转与缩放。导出的 GLB 已烘焙该变换。';
    });
  }
```

`renderAspectStrip()` 在 `whenModelReady` 解析后才执行清空，不会覆盖 AI 状态。

- [ ] **Step 9: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: `查看器 AI API` 通过；既有 `GLB 可被 UE 导入` 仍通过。

- [ ] **Step 10: 提交**

```bash
git add js/engines/viewer3d.js tests/smoke.html
git commit -m "feat(viewer3d): AI GLB 替换程序化几何并支持整体变换

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: 3D 编辑器支持 AI 整体变换与恢复程序化

**Files:**
- Modify: `js/views/editor3d.js`（全文重构模式分支）
- Test: `tests/smoke.html`（同步 check）

**Interfaces:**
- Consumes: Task 7 的 `whenModelReady` / `getAIModelTransform` / `setAIModelTransform` / `computeDefaultAIModelTransform`；Task 6 的 `fwNormalizeTransform`；`machine.model.transform`。
- Produces: `restoreProceduralGeometry(machine) -> boolean`（全局）；AI 模式下编辑器只展示 9 个整体变换输入，支持撤销/重做、“适配占地”、“重置变换”（回到打开编辑器时的已应用变换）、“恢复程序化几何”。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('恢复程序化几何 · 清理模型与模型图标', function(){
      var m = {model:{source:'ai'}, icon:'x', iconSource:'generated',
               generated:{model:{at:'2026-10-24T00:00:00Z'}, image:{at:'2026-10-23T00:00:00Z'}}};
      var changed = restoreProceduralGeometry(m);
      return changed && m.model === undefined && m.icon === '' && m.iconSource === '' &&
             m.generated.model === undefined && m.generated.image === undefined
               ? 'ok' : '未清理';
    });
    check('恢复程序化几何 · 保留更新的概念图', function(){
      var m = {model:{source:'ai'}, icon:'x', iconSource:'generated',
               generated:{model:{at:'2026-10-22T00:00:00Z'}, image:{at:'2026-10-24T00:00:00Z'}}};
      restoreProceduralGeometry(m);
      return m.icon === 'x' && m.iconSource === 'generated' ? 'ok' : '误删概念图';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 两个 check FAIL（`restoreProceduralGeometry is not defined`）。

- [ ] **Step 3: 新增恢复函数**

在 `js/views/editor3d.js` 顶部、`let _partEditor = null;` 之后加入：

```js
/** 删除 AI 模型，恢复程序化几何；若图标来自该模型则一并回退到自动图标 */
function restoreProceduralGeometry(machine){
  if(!machine || !machine.model) return false;
  const generated = machine.generated || {};
  const modelAt = generated.model
    ? Date.parse(generated.model.at || generated.model.generatedAt || '') || 0 : 0;
  const imageAt = generated.image
    ? Date.parse(generated.image.at || generated.image.generatedAt || '') || 0 : 0;
  if(machine.iconSource === 'generated' && modelAt >= imageAt){
    machine.icon = '';
    machine.iconSource = '';
    if(generated.image) delete generated.image;   // 该图标记录属于模型，不能留作幂等依据
  }
  delete machine.model;
  if(generated.model) delete generated.model;
  return true;
}
```

- [ ] **Step 4: 改造 open3DEditor 的模板与模式初始化**

把 `open3DEditor` 开头的两行（`const modal = document.getElementById('modal');` 与 `modal.innerHTML = ...;`）整体替换为下面代码（保留原有结构，只加 `wantsAI` 与加载提示，避免重复声明 `modal`）：

```js
  const wantsAI = !!(machine.model && machine.model.source === 'ai');
  const modal = document.getElementById('modal');
  modal.innerHTML = `<header><h3>${editor3dEscape(machine.name)} · ${wantsAI ? '模型变换' : '部件编辑器'}</h3><span class="x" id="e3dClose">×</span></header>
    <div class="content" style="padding:0"><div style="display:grid;grid-template-columns:minmax(280px,1fr) 300px;min-height:520px">
      <canvas id="e3dCanvas" style="width:100%;height:520px;background:#f2f0ec"></canvas>
      <aside style="padding:12px;border-left:1px solid var(--border);overflow:auto">
      <div style="display:flex;gap:6px;flex-wrap:wrap"><button id="e3dUndo">撤销</button><button id="e3dRedo">重做</button><button id="e3dReset">${wantsAI ? '适配占地' : '复位部件'}</button><button id="e3dInitial" style="display:none">重置变换</button><button id="e3dSnap">吸附：开</button></div>
        <div id="e3dParts" style="max-height:150px;overflow:auto;margin:10px 0"></div>
        <div id="e3dFields"><span class="hint">加载模型…</span></div>
      </aside>
    </div></div><footer><button class="primary" id="e3dDone">完成</button></footer>`;
```

- [ ] **Step 5: 加入 AI 模式函数**

在 `const clone = value=>JSON.parse(JSON.stringify(value || {}));` 之后加入：

```js
  let aiMode = false;
  const aiUndo = [], aiRedo = [];
  // 打开编辑器时的已应用变换；“重置变换”回到这里（区别于“适配占地”的重新计算）
  const initialModel = wantsAI
    ? {transform: clone(machine.model.transform), autoFit: machine.model.autoFit !== false}
    : null;

  function readAIInputs(){
    const read = key=>{
      const value = Number(document.querySelector('[data-e3d-ai="'+key+'"]').value);
      return Number.isFinite(value) ? value : 0;
    };
    return fwNormalizeTransform({
      position: {x:read('px'), y:read('py'), z:read('pz')},
      rotation: {x:read('rx')*Math.PI/180, y:read('ry')*Math.PI/180, z:read('rz')*Math.PI/180},
      scale:    {x:read('sx') || 1, y:read('sy') || 1, z:read('sz') || 1},
    });
  }

  function renderAIFields(){
    const el = document.getElementById('e3dFields');
    const t = viewer.getAIModelTransform() || machine.model.transform || normalizeModelTransform(null);
    const field = (label,key,value,step)=>`<label style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin:5px 0;font-size:11px">${label}<input data-e3d-ai="${key}" type="number" value="${Number(value)}" step="${step}" style="width:110px"></label>`;
    el.innerHTML = `<strong>AI 模型整体变换</strong>
      ${field('位置 X','px',t.position.x,0.01)}${field('位置 Y','py',t.position.y,0.01)}${field('位置 Z','pz',t.position.z,0.01)}
      ${field('旋转 X°','rx',t.rotation.x*180/Math.PI,1)}${field('旋转 Y°','ry',t.rotation.y*180/Math.PI,1)}${field('旋转 Z°','rz',t.rotation.z*180/Math.PI,1)}
      ${field('缩放 X','sx',t.scale.x,0.01)}${field('缩放 Y','sy',t.scale.y,0.01)}${field('缩放 Z','sz',t.scale.z,0.01)}
      <div style="font-size:10px;color:var(--text-3);margin-top:8px">修改后自动保存为手动变换；「适配占地」会重新计算。</div>`;
    el.querySelectorAll('[data-e3d-ai]').forEach(input=>input.onchange=()=>{
      aiUndo.push(clone(viewer.getAIModelTransform() || machine.model.transform));
      if(aiUndo.length > 50) aiUndo.shift();
      aiRedo.length = 0;
      const next = readAIInputs();
      machine.model.transform = next;
      machine.model.autoFit = false;
      viewer.setAIModelTransform(next);
      viewer.redraw();
      saveState();
    });
  }

  function initAIMode(){
    aiMode = true;
    document.getElementById('e3dParts').innerHTML = '<span class="hint">AI 模型不支持单部件编辑。</span>';
    document.getElementById('e3dSnap').style.display = 'none';
    document.getElementById('e3dReset').textContent = '适配占地';
    document.getElementById('e3dInitial').style.display = '';
    document.getElementById('e3dInitial').onclick = ()=>{
      if(!initialModel) return;
      aiUndo.push(clone(viewer.getAIModelTransform() || machine.model.transform));
      if(aiUndo.length > 50) aiUndo.shift();
      aiRedo.length = 0;
      machine.model.transform = clone(initialModel.transform);
      machine.model.autoFit = initialModel.autoFit;
      viewer.setAIModelTransform(machine.model.transform);
      viewer.redraw(); renderAIFields(); saveState();
      toast('已重置为应用时的变换');
    };
    document.getElementById('e3dReset').insertAdjacentHTML('afterend', '<button id="e3dRestore">恢复程序化几何</button>');
    document.getElementById('e3dRestore').onclick = ()=>{
      if(!confirm('删除 AI 模型并恢复程序化几何？若图标来自该模型，会回退为自动图标。')) return;
      if(!restoreProceduralGeometry(machine)) return;
      saveState();
      close();
      toast('已恢复程序化几何，需重新导出');
    };
    renderAIFields();
  }

  function initPartsMode(){
    aiMode = false;
    document.getElementById('e3dSnap').style.display = '';
    document.getElementById('e3dInitial').style.display = 'none';
    const restore = document.getElementById('e3dRestore');
    if(restore) restore.remove();
    renderParts();
    renderFields();
  }
```

- [ ] **Step 6: 替换初始化、撤销/重做与复位**

删除原来的：

```js
  renderParts();
  renderFields();
```

改为：

```js
  if(wantsAI){
    viewer.whenModelReady().then(function(result){
      if(result.ok){ initAIMode(); return; }
      initPartsMode();
      toast('AI 模型加载失败：' + result.error);
    });
  }else{
    initPartsMode();
  }
```

撤销/重做替换为：

```js
  document.getElementById('e3dUndo').onclick=()=>{
    if(aiMode){
      if(!aiUndo.length) return;
      aiRedo.push(clone(machine.model.transform));
      machine.model.transform = aiUndo.pop();
      machine.model.autoFit = false;
      viewer.setAIModelTransform(machine.model.transform);
      viewer.redraw(); renderAIFields(); saveState();
      return;
    }
    if(!undo.length) return;
    saveSnapshot(redo); machine.ui3d.parts=undo.pop(); apply(); renderFields(); persist();
  };
  document.getElementById('e3dRedo').onclick=()=>{
    if(aiMode){
      if(!aiRedo.length) return;
      aiUndo.push(clone(machine.model.transform));
      machine.model.transform = aiRedo.pop();
      machine.model.autoFit = false;
      viewer.setAIModelTransform(machine.model.transform);
      viewer.redraw(); renderAIFields(); saveState();
      return;
    }
    if(!redo.length) return;
    saveSnapshot(undo); machine.ui3d.parts=redo.pop(); apply(); renderFields(); persist();
  };
```

复位按钮替换为：

```js
  document.getElementById('e3dReset').onclick=()=>{
    if(aiMode){
      aiUndo.push(clone(viewer.getAIModelTransform() || machine.model.transform));
      if(aiUndo.length > 50) aiUndo.shift();
      aiRedo.length = 0;
      const next = viewer.computeDefaultAIModelTransform();
      machine.model.transform = next;
      machine.model.autoFit = true;
      viewer.setAIModelTransform(next);
      viewer.redraw(); renderAIFields(); saveState(); toast('已适配占地');
      return;
    }
    if(!selected || !confirm('复位所选部件的变换和材质？')) return;
    saveSnapshot(undo); redo.length=0;
    delete ensureParts()[selected]; apply(); renderFields(); persist();
  };
```

- [ ] **Step 7: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 两个新 check 通过；既有的 3D 视图/GLB check 不回归。

- [ ] **Step 8: 提交**

```bash
git add js/views/editor3d.js tests/smoke.html
git commit -m "feat(editor3d): AI 模型整体变换与恢复程序化

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: 资产编辑器与列表展示 AI 图标/模型

**Files:**
- Modify: `js/ui/editor.js`（`iconResourceHTML` + 元素/物品/机器表单）
- Modify: `js/views/machines.js`（`machineIconHTML` + 列/按钮）
- Modify: `js/views/assets.js`（物品徽标 + 元素来源标签）
- Test: `tests/smoke.html`

**Interfaces:**
- Consumes: `S`、`pipelineEnter(id, opts)`、`open3DEditor(id)`、`isoPreview(machine, angle, px)`、`iconHTML` / `elementIconHTML`、`saveState()`。
- Produces: `iconResourceHTML` 新增 `customLabel` / `generateLabel` 选项；`machineIconHTML(machine, px) -> string`；列表能区分 AI 生成图标、AI 模型与程序化几何。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('图标资源区支持来源文案', function(){
      var html = iconResourceHTML({
        hasCustom:true,
        customLabel:'当前使用<strong>AI 生成图标</strong>',
        generateLabel:'AI 生成 →'
      });
      return html.indexOf('AI 生成图标') >= 0 && html.indexOf('AI 生成 →') >= 0
        ? 'ok' : '文案未生效';
    });
    check('机器图标优先使用资产图标', function(){
      var html = machineIconHTML({id:'M1', icon:'data:image/png;base64,AA'}, 40);
      return html.indexOf('<img') === 0 && html.indexOf('data:image/png') > 0 ? 'ok' : '未使用图标';
    });
    check('机器无图标回退等轴测', function(){
      var m = JSON.parse(JSON.stringify(S.machines[0]));
      m.icon = '';
      var html = machineIconHTML(m, 40);
      return html.indexOf('<svg') === 0 ? 'ok' : '未回退';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 三个 check FAIL（文案硬编码 / `machineIconHTML is not defined`）。

- [ ] **Step 3: 扩展 `iconResourceHTML`**

把函数开头与提示/按钮三处改为：

```js
function iconResourceHTML(opt){
  opt = opt || {};
  const hasCustom = !!opt.hasCustom;
  const sourceLabel = opt.customLabel || (hasCustom
    ? '当前使用<strong>自定义图标</strong>'
    : '当前使用<strong>自动生成图标</strong>');
  return `<div style="border-top:1px solid var(--border);margin:16px 0 12px;padding-top:14px">
    <div style="font-size:12px;font-weight:500;margin-bottom:10px">图标</div>
    <div style="display:flex;gap:14px;align-items:flex-start">
      <div id="iconPrev" title="点击「上传图标」选择文件，或把图片拖到这里"
           style="width:72px;height:72px;flex:0 0 72px;display:flex;align-items:center;
           justify-content:center;background:var(--panel-2);border:1px solid var(--border);border-radius:10px">
        ${opt.previewHTML||''}
      </div>
      <div style="flex:1">
        <div id="iconHint" style="font-size:11px;color:var(--text-3);margin-bottom:8px">
          ${sourceLabel}
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <label class="sm" style="display:inline-block;padding:6px 12px;border:1px solid var(--border-2);
                 border-radius:7px;cursor:pointer;font-size:12px;background:var(--panel)">
            上传图标<input type="file" id="iconFile" accept="image/*" style="display:none">
          </label>
          <button class="sm" id="iconClear" ${hasCustom?'':'disabled'}>恢复自动生成</button>
          ${opt.showGenerate?`<button class="sm" id="iconGen">${opt.generateLabel || '生成图标 →'}</button>`:''}
        </div>
        <div style="font-size:10.5px;color:var(--text-3);margin-top:6px">
          上传或拖入的图片会自动缩放到 128×128 并转成内嵌数据，避免撑爆 localStorage。
        </div>
      </div>
    </div>
  </div>`;
}
```

- [ ] **Step 4: 元素与物品传入来源文案**

元素 `iconResourceHTML(...)` 调用改为：

```js
      iconResourceHTML({
        previewHTML: d?elementIconHTML(d,52):'',
        hasCustom,
        showGenerate: !isNew,
        customLabel: d && d.iconSource === 'generated'
          ? '当前使用<strong>AI 生成图标</strong>' : undefined,
        generateLabel: 'AI 生成 →',
      });
```

物品 `iconResourceHTML(...)` 调用改为：

```js
      iconResourceHTML({
        previewHTML: d?iconHTML(d,52):'',
        hasCustom,
        showGenerate: !isNew,
        customLabel: d && d.iconSource === 'generated'
          ? '当前使用<strong>AI 生成图标</strong>' : undefined,
        generateLabel: 'AI 生成 →',
      }) +
```

- [ ] **Step 5: 物品模型区块增加 AI 状态**

在物品表单的模型区块中，把 `<div style="font-size:12px;font-weight:500;margin-bottom:10px">模型</div>` 之后插入：

```js
        ${(d && d.model && d.model.source === 'ai')
          ? `<div style="font-size:11px;background:var(--panel-2);padding:10px;border-radius:7px;margin-bottom:10px">
               <div><strong>AI 模型</strong> · ${d.model.provider||'provider'} · ${d.model.triangles||0} 面</div>
               <div style="font-family:var(--mono);font-size:10.5px;margin-top:4px">${d.model.file||''}</div>
               <div style="font-size:10.5px;color:var(--text-3);margin-top:2px">任务 ${d.model.taskId||'—'} · ${d.model.generatedAt||''}</div>
               <div style="font-size:10.5px;color:var(--text-3);margin-top:4px">自动导出优先使用 AI 模型</div>
               <div style="margin-top:8px"><button class="sm" id="iModelRemove">移除 AI 模型</button></div>
             </div>`
          : `<div style="font-size:11px;color:var(--text-3);margin-bottom:8px">
               ${d && d.mesh ? '程序化网格路径已填写' : '尚未生成 3D 模型'}
             </div>
             <div style="margin-bottom:10px">${isNew ? '' : '<button class="sm" id="iModelGen">生成模型 →</button>'}</div>
             <div style="font-size:10.5px;color:var(--text-3);margin-bottom:8px">AI 模型优先用于自动导出</div>`}
```

在物品的 `bindIconResource({...});` 之后加入：

```js
    const iModelGen = document.getElementById('iModelGen');
    if(iModelGen) iModelGen.onclick = ()=>{
      if(!d) return;
      const dirty = editorFormSnapshot(watchedFields) !== initialForm || editorIconDirty();
      if(!editorConfirmLeave(dirty)) return;
      const fromView = cur;
      closeModal();
      pipelineEnter(d.id, {view: fromView, assetId: d.id, modal: 'editor', coll: 'items'});
    };
    const iModelRemove = document.getElementById('iModelRemove');
    if(iModelRemove) iModelRemove.onclick = ()=>{
      const item = S.items.find(x=>x.id===d.id);
      if(!item) return;
      if(!confirm('移除 AI 模型？图标不会被删除。')) return;
      delete item.model;
      if(item.generated) delete item.generated.model;
      saveState(); clearIconCache();
      renderEditorForm('items', item, false);
      toast('已移除 AI 模型');
    };
```

- [ ] **Step 6: 机器表单增加图标与模型区块**

把 `else if(coll==='machines'){ ... }` 整段替换为：

```js
  else if(coll==='machines'){
    const hasCustom = !!(d && d.icon && d.icon.trim());
    const aiModel = !!(d && d.model && d.model.source === 'ai');
    const iconLabel = d && d.iconSource === 'generated'
      ? '当前使用<strong>AI 生成图标</strong>'
      : null;
    const modelBlock = aiModel
      ? `<div style="font-size:11px;background:var(--panel-2);padding:10px;border-radius:7px">
           <div><strong>AI 模型</strong> · ${d.model.provider||'provider'} · ${d.model.triangles||0} 面</div>
           <div style="font-family:var(--mono);font-size:10.5px;margin-top:4px">${d.model.file||''}</div>
           <div style="font-size:10.5px;color:var(--text-3);margin-top:2px">任务 ${d.model.taskId||'—'} · ${d.model.generatedAt||''}</div>
           <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
             <button class="sm" id="mModelEdit">变换模型 →</button>
             <button class="sm" id="mModelRemove">移除 AI 模型</button>
           </div>
         </div>`
      : `<div style="font-size:11px;color:var(--text-3)">当前为程序化几何</div>
         <div style="margin-top:8px">${isNew ? '' : '<button class="sm" id="mModelGen">生成模型 →</button>'}</div>`;
    b.innerHTML = F('id','ID', d?.id||'','text','required') + F('name','名称', d?.name||'') +
      SEL('cat','分类', d?.cat||'加工',
        ['采集','分离','冶炼','合金','化工','加工','组装','回收'].map(c=>({v:c,t:c}))) +
      SEL('tier','等级', String(d?.tier??0), [0,1,2,3,4].map(t=>({v:String(t),t:'T'+t}))) +
      F('footprint','占地（如 3×3）', d?.footprint||'2×2') +
      F('power','耗电 kW', d?.power??100,'number') + F('desc','说明', d?.desc||'') +
      iconResourceHTML({
        previewHTML: d ? machineIconHTML(d, 52) : '',
        hasCustom,
        showGenerate: !isNew,
        customLabel: iconLabel || undefined,
        generateLabel: 'AI 生成 →',
      }) +
      `<div style="border-top:1px solid var(--border);margin:14px 0 12px;padding-top:14px">
        <div style="font-size:12px;font-weight:500;margin-bottom:10px">模型</div>
        ${modelBlock}
      </div>`;

    const watchedFields = ['id','name','cat','tier','footprint','power','desc'];
    const initialForm = editorFormSnapshot(watchedFields);
    const makeTmp = ()=>({
      id:document.getElementById('f_id').value,
      name:document.getElementById('f_name').value,
      cat:document.getElementById('f_cat').value,
      tier:document.getElementById('f_tier').value,
      footprint:document.getElementById('f_footprint').value,
    });
    const openPipeline = ()=>{
      if(!d) return;
      const dirty = editorFormSnapshot(watchedFields) !== initialForm || editorIconDirty();
      if(!editorConfirmLeave(dirty)) return;
      const fromView = cur;
      closeModal();
      pipelineEnter(d.id, {view: fromView, assetId: d.id, modal: 'editor', coll: 'machines'});
    };
    bindIconResource({
      makeTmp,
      renderAuto: tmp=>isoPreview(tmp, 0, 52),
      onGenerate: openPipeline,
    });
    const mModelGen = document.getElementById('mModelGen');
    if(mModelGen) mModelGen.onclick = openPipeline;
    const mModelEdit = document.getElementById('mModelEdit');
    if(mModelEdit) mModelEdit.onclick = ()=>{
      const dirty = editorFormSnapshot(watchedFields) !== initialForm || editorIconDirty();
      if(!editorConfirmLeave(dirty)) return;
      const id = d.id;
      closeModal();
      open3DEditor(id);
    };
    const mModelRemove = document.getElementById('mModelRemove');
    if(mModelRemove) mModelRemove.onclick = ()=>{
      const machine = S.machines.find(x=>x.id===d.id);
      if(!machine) return;
      if(!confirm('移除 AI 模型并恢复程序化几何？图标不会被删除。')) return;
      delete machine.model;
      if(machine.generated) delete machine.generated.model;
      saveState(); clearIconCache();
      renderEditorForm('machines', machine, false);
      toast('已移除 AI 模型');
    };
  }
```

- [ ] **Step 7: 机器列表使用资产图标与 AI 徽标**

在 `js/views/machines.js` 顶部加入：

```js
function machineIconHTML(m, size){
  const px = size || 40;
  if(m && m.icon){
    return `<img src="${m.icon}" width="${px}" height="${px}" style="border-radius:6px;object-fit:contain;background:var(--panel-2)" alt="">`;
  }
  return isoPreview(m, 0, px);
}
```

把列定义改为：

```js
    {t:'图标',w:'54px',f:r=>machineIconHTML(r, 40)},
    {t:'ID',w:'150px',f:r=>`<code>${r.id}</code>`},
    {t:'名称',w:'130px',f:r=>r.name + (r.model && r.model.source === 'ai'
      ? ' <span class="tag" style="background:#e7f4ec;color:#1f7a4d">AI</span>' : '')},
```

操作列改为：

```js
    {t:'操作',w:'96px',f:r=>
      `<button class="sm" data-m3d="${r.id}" title="查看 3D 预览">3D</button>
       <button class="sm" data-medit3d="${r.id}" title="${r.model && r.model.source === 'ai' ? '调整 AI 模型整体变换' : '编辑 3D 部件'}">${r.model && r.model.source === 'ai' ? '变换' : '部件'}</button>
       <button class="sm" data-medit="${r.id}" title="编辑参数">编辑</button>`},
```

- [ ] **Step 8: 资源视图徽标**

物品卡片中，把 `hasCustom` 之后的标签行替换为：

```js
      ${it.iconSource === 'generated'
        ? '<div style="font-size:9.5px;color:var(--accent);margin-top:4px">AI 生成图标</div>'
        : (hasCustom ? '<div style="font-size:9.5px;color:var(--blue);margin-top:4px">自定义图标</div>' : '')}
      ${it.model && it.model.source === 'ai'
        ? '<div style="font-size:9.5px;color:var(--accent);margin-top:2px">AI 模型</div>' : ''}
      ${hasMesh?`<div style="font-size:9.5px;color:var(--accent);margin-top:2px">已绑模型</div>`:''}
```

元素卡片中，把来源标签改为：

```js
        <span class="tag">${el.iconSource === 'generated' ? 'AI 生成' : (hasCustom ? '自定义' : '自动生成')}</span>
```

- [ ] **Step 9: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 三个新 check 通过，所有视图渲染 check 仍通过。

- [ ] **Step 10: 提交**

```bash
git add js/ui/editor.js js/views/machines.js js/views/assets.js tests/smoke.html
git commit -m "feat(editor): 资产编辑器与列表展示 AI 图标和模型

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: 同步状态与手动导出支持 AI 模型/生成图标

**Files:**
- Modify: `js/sync.js`（`assetModelHash`、状态判断、`syncExportMachine` / `syncExportItem` / `syncExportElement`）
- Test: `tests/smoke.html`

**Interfaces:**
- Consumes: Task 4 的 `normalizeModelTransform` / `asset.model` / `asset.iconSource`；Task 6 的 `fwNormalizeTransform` / `fwLoadGLBScene` / `fwComputeFitTransform` / `fwBakeGLBScene` / `fwCountTriangles`；Task 11 的 `pipelineOutputURLFor`（运行期存在，导出时才调用）。
- Produces: `assetModelHash(model) -> string`、`machineModelHash(machine) -> string`、`itemModelHash(item) -> string`；manifest `meta.modelHash` / `meta.model` / `meta.iconSource`；AI 模型手动同步时写入 `mesh`（机器 + 物品），生成图标在 manifest 已有文件时不重复编码。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('模型哈希随变换变化', function(){
      var a = itemModelHash({model:{file:'a.glb',taskId:'t',
        transform:{position:{x:0,y:0,z:0},rotation:{x:0,y:0,z:0},scale:{x:1,y:1,z:1}}}});
      var b = itemModelHash({model:{file:'a.glb',taskId:'t',
        transform:{position:{x:1,y:0,z:0},rotation:{x:0,y:0,z:0},scale:{x:1,y:1,z:1}}}});
      return a !== b ? 'ok' : '变换未参与哈希';
    });
    check('机器内容哈希覆盖图标与模型', function(){
      var m = JSON.parse(JSON.stringify(S.machines[0]));
      delete m.icon; delete m.iconSource; delete m.model;
      var base = machineContentHash(m);
      m.icon = 'data:image/png;base64,AA';
      m.iconSource = 'generated';
      var withIcon = machineContentHash(m);
      m.model = {source:'ai', file:'M1.glb', taskId:'t', autoFit:true,
        transform:normalizeModelTransform(null)};
      var withModel = machineContentHash(m);
      return base !== withIcon && withIcon !== withModel ? 'ok' : '哈希未覆盖';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 第一个 check FAIL（`itemModelHash is not defined`）；第二个 check FAIL（哈希不变）。

- [ ] **Step 3: 加入模型哈希并扩展内容哈希**

在 `syncDataHash` 之后加入：

```js
/** 模型身份 + 整体变换的 hash；没有模型时返回“空模型”的稳定值 */
function assetModelHash(model){
  if(!model) return syncDataHash(null);
  return syncDataHash({
    source: model.source || '',
    file: model.file || '',
    taskId: model.taskId || '',
    transform: typeof fwNormalizeTransform === 'function'
      ? fwNormalizeTransform(model.transform) : (model.transform || null),
    autoFit: model.autoFit !== false,
  });
}
function machineModelHash(m){ return assetModelHash(m.model); }
function itemModelHash(it){ return assetModelHash(it.model); }
```

把 `machineContentHash` 替换为：

```js
/** 机器数据的 contentHash：影响几何/语义/图标/模型的字段 */
function machineContentHash(m){
  return syncDataHash({
    id: m.id, name: m.name, cat: m.cat, footprint: m.footprint,
    tier: m.tier, power: m.power,
    icon: (m.icon || '').trim(),
    iconSource: m.iconSource || '',
    model: machineModelHash(m),
  });
}
```

`itemIconHash` 的字段表加入 `iconSource`：

```js
function itemIconHash(it){
  return syncDataHash({
    id: it.id, name: it.name, type: it.visual || it.type, color: it.color || '',
    customIcon: (it.icon || '').trim(), iconSource: it.iconSource || '',
    style: styleCacheTag(),
  });
}
```

- [ ] **Step 4: 扩展 UE / 同步状态判断**

把 `machineUEState` 的 `stale` 替换为：

```js
  const aiStale = m.model && m.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || meta.modelHash !== machineModelHash(m))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (meta.contentHash && meta.contentHash !== machineContentHash(m))
             || (meta.styleHash   && meta.styleHash   !== machineStyleHash(m));
```

把 `itemUEState` 的 `stale` 替换为：

```js
  const aiStale = it.model && it.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || meta.modelHash !== itemModelHash(it))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (meta.iconHash && meta.iconHash !== itemIconHash(it));
```

把 `machineSyncState` 的 `stale` 替换为：

```js
  const aiStale = m.model && m.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || saved.modelHash !== machineModelHash(m))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (saved.contentHash && saved.contentHash !== ch)
             || (saved.styleHash   && saved.styleHash   !== sh);
```

把 `itemSyncState` 的 `stale` 替换为：

```js
  const aiStale = it.model && it.model.source === 'ai'
    ? (!hasAssetFile(rec, 'mesh') || saved.modelHash !== itemModelHash(it))
    : false;
  const stale = !hasAssetFile(rec, 'icon') || aiStale
             || (saved.iconHash && saved.iconHash !== itemIconHash(it));
```

`elementSyncState` 只补缺图标判断：

```js
  const stale = !hasAssetFile(rec, 'icon')
             || (saved.iconHash && saved.iconHash !== elementIconHash(el));
```

- [ ] **Step 5: 改造 `syncExportMachine`**

把函数从 `async function syncExportMachine(id, opt){` 到其结束 `}` 整段替换为：

```js
async function syncExportMachine(id, opt){
  opt = opt || {};
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const m = machineOf(id);
  if(!m) return { ok:false, error:'机器不存在: ' + id };
  if(!haveThree()) return { ok:false, error:'three.js 未加载' };

  // 1. 离屏生成 GLB；AI 模型先等加载完成，再取缩略图与烘焙结果
  if(typeof fwTexturesReady === 'function') await fwTexturesReady();
  const cv = document.createElement('canvas');
  cv.width = 64; cv.height = 64;
  const isAI = !!(m.model && m.model.source === 'ai');
  let V = null, glbBuf = null, glbErr = null, meta = null;
  let aiThumb256 = '', aiThumb512 = '';
  try{
    V = createViewer3D(cv, m);
    if(isAI){
      const ready = await V.whenModelReady();
      if(!ready.ok) throw new Error('AI 模型加载失败: ' + ready.error);
      aiThumb256 = V.toThumbnail(256);
      aiThumb512 = V.toThumbnail(512);
    }
    await new Promise(function(resolve){
      V.toGLB(function(result, err, mt){
        glbBuf = result; glbErr = err; meta = mt; resolve();
      });
    });
  }catch(e){
    glbErr = e;
  }finally{
    if(V && V.dispose) V.dispose();
  }
  if(glbErr || !glbBuf) return { ok:false, error:'GLB 生成失败: ' + (glbErr && glbErr.message) };

  // 2. 质量门禁
  const st = getStyle();
  const budget = parseInt((st.spec.machine.match(/(\d+)\s*~\s*(\d+)/) || [])[2], 10) || 900;
  const gate = {
    triangles: meta.triangles || 0,
    budget: budget,
    over: (meta.triangles || 0) > budget,
    severe: (meta.triangles || 0) > budget * 2,
    sizeCm: meta.sizeCm,
    materials: meta.materials,
  };

  // 3. 图标：上传优先；AI 模型用 256 缩略图；程序化几何用等轴测
  const previewSvg = isoPreview(m, 0, 132);
  const previewSvgFile = {
    path: m.id + '_preview.svg',
    b64: btoa(unescape(encodeURIComponent(previewSvg))),
  };
  let iconB64, previewFile;
  try{
    if(m.icon && m.iconSource !== 'generated'){
      iconB64 = await imagePngB64(m.icon, 256, '上传图标 ' + m.id);
      previewFile = previewSvgFile;
    }else if(isAI){
      if(!aiThumb256 || !aiThumb512) throw new Error('AI 缩略图不可用');
      iconB64 = aiThumb256.slice(aiThumb256.indexOf(',') + 1);
      previewFile = {
        path: m.id + '_preview.png',
        b64: aiThumb512.slice(aiThumb512.indexOf(',') + 1),
      };
    }else{
      iconB64 = await machineIconB64(m, 256);
      previewFile = previewSvgFile;
    }
  }catch(e){
    return { ok:false, error:'机器图标生成失败: ' + e.message };
  }

  // 4. POST 给 Bridge
  const body = {
    kind: 'machine',
    id: m.id,
    files: {
      mesh:    { path: m.id + '.glb', b64: bufToB64(glbBuf) },
      preview: previewFile,
      icon:    { path: m.id + '_icon.png', b64: iconB64 },
    },
    meta: {
      name: m.name, category: m.cat, footprint: m.footprint, tier: m.tier,
      triangles: gate.triangles, triangleBudget: budget,
      materials: gate.materials, sizeCm: gate.sizeCm,
      style: { presetId: st.id, name: st.name,
               accent: accentFor(m.cat, st) },
      gate: gate,
      textures: typeof FW_TEX !== 'undefined' ? Object.keys(FW_TEX.items) : [],
      contentHash: machineContentHash(m),
      styleHash: machineStyleHash(m),
      modelHash: machineModelHash(m),
      iconSource: m.iconSource || '',
      model: isAI ? {
        source: 'ai', provider: m.model.provider || '', file: m.model.file || '',
        taskId: m.model.taskId || '', triangles: gate.triangles,
        transform: fwNormalizeTransform(m.model.transform),
        autoFit: m.model.autoFit !== false,
      } : null,
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    syncLog('导出 ' + m.id + '：' + (r.files.mesh ? r.files.mesh[0] : '') +
            ((r.files.icon && r.files.icon[0]) ? ' + ' + r.files.icon[0] : '') +
            '（' + gate.triangles + ' 三角面' + (gate.over ? '，超预算 ' + budget + ' ⚠' : '') + '）',
            gate.severe ? 'warn' : 'ok');
    await syncLoadManifest();
  }
  return { ok: !!(r && r.ok), gate, response: r };
}
```

- [ ] **Step 6: 改造 `syncExportItem`**

把函数整段替换为：

```js
/** 导出单个物品（图标 + 可选 AI 模型）到 Bridge（→ _Source/物品/图标/<中文名>/）。 */
async function syncExportItem(id){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const it = (S.items || []).find(function(item){ return item.id === id; });
  if(!it) return { ok:false, error:'物品不存在: ' + id };

  const rec = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[it.id];
  const skipIcon = it.iconSource === 'generated' && hasAssetFile(rec, 'icon');
  const files = {};
  if(!skipIcon){
    try{
      files.icon = { path: it.id + '.png', b64: await iconPngB64(it, 256) };
    }catch(e){
      return { ok:false, error:'图标生成失败: ' + e.message };
    }
  }

  let modelMeta = null;
  if(it.model && it.model.source === 'ai'){
    try{
      const url = pipelineOutputURLFor(it.id, 'item', it.model.file);
      const response = await fetch(url);
      if(!response.ok) throw new Error('HTTP ' + response.status);
      const scene = await fwLoadGLBScene(await response.arrayBuffer());
      const transform = (it.model.autoFit === false && it.model.transform)
        ? fwNormalizeTransform(it.model.transform)
        : fwComputeFitTransform(scene, 'item', '');
      const baked = await new Promise(function(resolve, reject){
        fwBakeGLBScene(scene, transform, {
          name: it.id,
          forgeworks: { generator:'Forgeworks', source:'pipeline-ai',
                        id:it.id, name:it.name, kind:'item' },
        }, function(result, error){
          if(error) reject(error); else resolve(result);
        });
      });
      files.mesh = { path: it.id + '.glb', b64: bufToB64(baked) };
      modelMeta = {
        source:'ai', provider: it.model.provider || '', file: it.model.file || '',
        taskId: it.model.taskId || '', triangles: fwCountTriangles(scene),
        transform: fwNormalizeTransform(transform),
        autoFit: it.model.autoFit !== false,
      };
    }catch(e){
      return { ok:false, error:'AI 模型导出失败: ' + e.message };
    }
  }

  const st = getStyle();
  const body = {
    kind: 'item',
    id: it.id,
    files: files,
    meta: {
      name: it.name, type: it.type, visual: it.visual || null,
      tier: it.tier, color: it.color || '',
      customIcon: !!(it.icon && it.icon.trim()),
      iconSource: it.iconSource || '',
      size: 256,
      style: { presetId: st.id, name: st.name },
      iconHash: itemIconHash(it),
      modelHash: itemModelHash(it),
      model: modelMeta,
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    const iconName = r.files && r.files.icon ? r.files.icon[0] : '';
    syncLog('导出 ' + it.id + '：' + (iconName || '仅更新元数据') +
            (r.files && r.files.mesh ? ' + ' + r.files.mesh[0] : ''), 'ok');
    await syncLoadManifest();
  }
  return { ok: !!(r && r.ok), response: r };
}
```

- [ ] **Step 7: 改造 `syncExportElement`**

把函数整段替换为：

```js
/** 导出单个元素图标到 Bridge（→ _Source/元素/<中文名>/<ID>.png）。 */
async function syncExportElement(id){
  if(!SYNC.online) return { ok:false, error:'Bridge 不在线（先启动 tools/bridge.py）' };
  const el = (S.elements || []).find(function(x){ return x.id === id; });
  if(!el) return { ok:false, error:'元素不存在: ' + id };

  const rec = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[el.id];
  const skipIcon = el.iconSource === 'generated' && hasAssetFile(rec, 'icon');
  const files = {};
  if(!skipIcon){
    try{
      files.icon = {
        path: el.id + '.png',
        b64: await imagePngB64(elementIconURL(el), 256, '元素图标 ' + el.id),
      };
    }catch(e){
      return { ok:false, error:'图标生成失败: ' + e.message };
    }
  }

  const st = getStyle();
  const body = {
    kind: 'element',
    id: el.id,
    files: files,
    meta: {
      name: el.name, symbol: el.symbol || '', tier: el.tier, color: el.color || '',
      customIcon: !!(el.icon && el.icon.trim()),
      iconSource: el.iconSource || '',
      size: 256,
      style: { presetId: st.id, name: st.name },
      iconHash: elementIconHash(el),
    },
  };
  const r = await syncApi('export/asset', body);
  if(r && r.ok){
    syncLog('导出元素 ' + el.id + '：' +
            ((r.files && r.files.icon) ? r.files.icon[0] : '仅更新元数据'), 'ok');
    await syncLoadManifest();
  }
  return { ok: !!(r && r.ok), response: r };
}
```

- [ ] **Step 8: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 两个新 check 通过，`summary.fail == 0`。

- [ ] **Step 9: 提交**

```bash
git add js/sync.js tests/smoke.html
git commit -m "feat(sync): AI 模型与生成图标参与同步状态和手动导出

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: 轮询成功后自动回填资产并导出

**Files:**
- Create: `js/pipeline-adopt.js`
- Modify: `js/pipeline.js`（`PIPELINE` 状态、轮询/提交钩子、`pipelineOutputURLFor`、返回文案、模板默认值）
- Modify: `index.html`
- Modify: `tests/smoke.html`

**Interfaces:**
- Consumes: Task 4 的 `normalizeModelTransform`；Task 6 的 GLB 工具；Task 10 的 `machineContentHash` / `itemModelHash` / `machineModelHash` / `itemIconHash` / `elementIconHash` / `hasAssetFile`；`pipelineApi(route, body)`；`syncLoadManifest()`；`syncPublishUE(ids)`；`saveState()`；`syncSaveProjectNow()`。
- Produces: `window.pipelineAdoptTask(assetId, kind, nodeId, nodeType, task, force) -> Promise<{ok, skipped?, duplicate?, note?, warning?, applied?, error?}>`；`PIPELINE.applyQueue` / `applyStatus` / `applyErrors`；`pipelineOutputURLFor(assetId, kind, file) -> string`（只保留文件名）。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('管线输出 URL 仅使用文件名', function(){
      var url = pipelineOutputURLFor('M1', 'machine', 'C:\\tmp\\..\\M1.glb');
      return url === '/api/pipeline/output/M1/M1.glb?kind=machine' ? 'ok' : ('异常: ' + url);
    });
    check('管线落地编排已加载', function(){
      return typeof pipelineAdoptTask === 'function' ? 'ok' : '未加载';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: `pipelineOutputURLFor is not defined` / `pipelineAdoptTask is not defined`。

- [ ] **Step 3: 扩展 `pipeline.js` 状态与输出 URL**

把第 1 行 `const PIPELINE = {...};` 替换为：

```js
const PIPELINE = {assetId:null, kind:'machine', graph:null, providers:{}, selected:null, busy:false, source:'local', archive:null, zoom:1, pan:{x:0,y:0}, returnTo:null, remote:{}, pollers:{}, applyQueue:{}, applyStatus:{}, applyErrors:{}};
```

把 `pipelineReturnLabel` 的 editor 文案改为：

```js
  if(target.modal === 'editor') return '← 返回资产编辑';
```

把 `pipelineOutputURL` 整段替换为：

```js
/** 只接受文件名，杜绝 ../ 与盘符路径；Bridge 端也按 basename 解析。 */
function pipelineOutputURLFor(assetId, kind, file){
  if(!file) return '';
  const name = String(file).replace(/\\/g, '/').split('/').pop();
  if(!name || name === '.' || name === '..') return '';
  return '/api/pipeline/output/' + encodeURIComponent(assetId) + '/' +
    encodeURIComponent(name) + '?kind=' + encodeURIComponent(kind);
}

function pipelineOutputURL(file){
  if(!pipelineBridgeReady() || !PIPELINE.assetId) return '';
  return pipelineOutputURLFor(PIPELINE.assetId, PIPELINE.kind, file);
}
```

- [ ] **Step 4: 在轮询/提交成功后调用落地**

把 `pipelinePollLoop` 的签名与内容改为：

```js
function pipelinePollLoop(assetId, kind, nodeId, attempt, delay, nodeType){
  const key = pipelinePollKey(assetId, kind, nodeId);
  if(PIPELINE.pollers[key]) return;
  if(!nodeType && PIPELINE.assetId === assetId && PIPELINE.kind === kind && PIPELINE.graph){
    const polled = PIPELINE.graph.nodes.find(item=>item.id === nodeId);
    nodeType = polled ? polled.type : '';
  }
  PIPELINE.pollers[key] = setTimeout(async () => {
    delete PIPELINE.pollers[key];
    if(!pipelineBridgeReady()) return;
    try{
      const result = await pipelineApi('pipeline/provider/poll', {assetId, kind, nodeId});
      const task = result.task || {};
      const current = PIPELINE.assetId === assetId && PIPELINE.kind === kind;
      if(current){
        PIPELINE.graph = result.graph;
        pipelineRefreshNode(nodeId);
      }
      if(task.state === 'queued' || task.state === 'running'){
        pipelinePollLoop(assetId, kind, nodeId, 0, 4000, nodeType);
        return;
      }
      if(current){
        const label = task.provider === 'ark' ? 'Ark' : (task.provider === 'tripo' ? 'Tripo' : 'Provider');
        toast(task.state === 'success'
          ? label + ' 生成完成'
          : label + ' 任务' + pipelineStateLabel(task.state) + (task.error ? '：' + task.error : ''));
      }
      if(task.state === 'success'){
        pipelineAdoptTask(assetId, kind, nodeId, nodeType, task);
      }
    }catch(error){
      if(attempt < 3) pipelinePollLoop(assetId, kind, nodeId, attempt + 1, 5000, nodeType);
      else toast('查询远程任务失败：' + error.message);
    }
  }, delay == null ? 1500 : delay);
}
```

在 `pipelineSubmitRemote` 的 `if(task.state==='queued'||task.state==='running') pipelineTrackRemote(nodeId);` 之后加：

```js
    if(task.state==='success') pipelineAdoptTask(PIPELINE.assetId,PIPELINE.kind,nodeId,node.type,task);
```

在 `pipelinePollRemote` 的 `if(task.state==='queued'||task.state==='running') pipelineTrackRemote(nodeId);` 之后加：

```js
    const polled=PIPELINE.graph&&PIPELINE.graph.nodes.find(item=>item.id===nodeId);
    if(task.state==='success'&&polled) pipelineAdoptTask(PIPELINE.assetId,PIPELINE.kind,nodeId,polled.type,task);
```

把 `pipelineTrackRemote` 替换为（把节点类型带进轮询，用户切走后仍能自动应用）：

```js
function pipelineTrackRemote(nodeId){
  const key = pipelinePollKey(PIPELINE.assetId, PIPELINE.kind, nodeId);
  if(PIPELINE.pollers[key]){ clearTimeout(PIPELINE.pollers[key]); delete PIPELINE.pollers[key]; }
  const node = PIPELINE.graph && PIPELINE.graph.nodes.find(item=>item.id===nodeId);
  pipelinePollLoop(PIPELINE.assetId, PIPELINE.kind, nodeId, 0, undefined, node && node.type);
}
```

把 `renderPipelineView` 中恢复排队任务的调用改为：

```js
    if(task&&(task.state==='queued'||task.state==='running')) pipelinePollLoop(PIPELINE.assetId,PIPELINE.kind,node.id,0,1200,node.type);
```

- [ ] **Step 5: 修正模板默认值**

在 `renderPipelineView` 的 `view.innerHTML` 之前加入：

```js
  const defaultTemplate = PIPELINE.kind === 'element' ? 'icon'
    : (PIPELINE.kind === 'item' ? 'item' : 'machine');
```

把模板 `<option>` 中的：

```js
${template.id===(PIPELINE.graph.template || (PIPELINE.kind==='element'?'icon':'machine'))?'selected':''}
```

改为：

```js
${template.id===(PIPELINE.graph.template || defaultTemplate)?'selected':''}
```

- [ ] **Step 6: 新建 `js/pipeline-adopt.js`**

```js
/* Forgeworks · js/pipeline-adopt.js
 * Provider 任务成功后：把概念图/模型写进资产、导出到项目 _Source，并在配置了 UE 目标时发布。
 * 依赖：fw* GLB 工具、sync.js、pipeline.js。所有请求同源，不接触 Provider 原始接口。
 */
(function(){
  'use strict';

  function pipelineFindAsset(kind, assetId){
    if(kind === 'machine') return (S.machines || []).find(function(item){ return item.id === assetId; });
    if(kind === 'item') return (S.items || []).find(function(item){ return item.id === assetId; });
    return (S.elements || []).find(function(item){ return item.id === assetId; });
  }

  function iconPath(kind, assetId){
    return kind === 'machine' ? assetId + '_icon.png' : assetId + '.png';
  }

  /** 资产与 manifest 只记录 basename；原始路径留在管线存档。 */
  function baseName(file){
    return String(file || '').replace(/\\/g, '/').split('/').pop();
  }

  function imageB64(dataUrl){
    const text = String(dataUrl || '');
    const comma = text.indexOf(',');
    if(comma < 0) throw new Error('图片数据为空');
    return text.slice(comma + 1);
  }

  function loadImage(url){
    return new Promise(function(resolve, reject){
      const img = new Image();
      img.crossOrigin = 'anonymous';       // Bridge 带 ACAO:*，file:// 页面也能读像素
      img.onload = function(){ resolve(img); };
      img.onerror = function(){ reject(new Error('图片加载失败')); };
      img.src = url;
    });
  }

  function cropSquare(img, size){
    const width = img.naturalWidth || img.width;
    const height = img.naturalHeight || img.height;
    const side = Math.min(width, height);
    if(!side) throw new Error('图片尺寸无效');
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d');
    if(!ctx) throw new Error('Canvas 不可用');
    ctx.drawImage(img, (width - side) / 2, (height - side) / 2, side, side, 0, 0, size, size);
    return canvas.toDataURL('image/png');
  }

  function modelMeta(asset){
    return {
      source: 'ai',
      provider: asset.model.provider || '',
      file: baseName(asset.model.file),
      taskId: asset.model.taskId || '',
      nodeId: asset.model.nodeId || '',
      generatedAt: asset.model.generatedAt || '',
      triangles: asset.model.triangles || 0,
      transform: fwNormalizeTransform(asset.model.transform),
      autoFit: asset.model.autoFit !== false,
    };
  }

  function adoptMeta(asset, kind){
    const style = getStyle();
    const styleMeta = {presetId: style.id, name: style.name};
    if(kind === 'machine'){
      const meta = {
        name: asset.name, category: asset.cat, footprint: asset.footprint, tier: asset.tier,
        style: {presetId: style.id, name: style.name, accent: accentFor(asset.cat, style)},
        contentHash: machineContentHash(asset),
        styleHash: machineStyleHash(asset),
        modelHash: machineModelHash(asset),
        iconSource: asset.iconSource || '',
        model: asset.model ? modelMeta(asset) : null,
      };
      // 没有模型时不要写入 triangles:0，避免图标导出覆盖已有 mesh 的统计
      if(asset.model) meta.triangles = asset.model.triangles || 0;
      return meta;
    }
    if(kind === 'item'){
      return {
        name: asset.name, type: asset.type, visual: asset.visual || null,
        tier: asset.tier, color: asset.color || '',
        customIcon: !!(asset.icon && asset.icon.trim()),
        iconSource: asset.iconSource || '', size: 256, style: styleMeta,
        iconHash: itemIconHash(asset), modelHash: itemModelHash(asset),
        model: asset.model ? modelMeta(asset) : null,
      };
    }
    return {
      name: asset.name, symbol: asset.symbol || '', tier: asset.tier, color: asset.color || '',
      customIcon: !!(asset.icon && asset.icon.trim()),
      iconSource: asset.iconSource || '', size: 256, style: styleMeta,
      iconHash: elementIconHash(asset),
    };
  }

  async function persistAsset(){
    saveState();
    if(typeof syncSaveProjectNow === 'function'){
      try{ await syncSaveProjectNow(); }catch(_){ /* 项目文件稍后由同步重试 */ }
    }
  }

  async function exportAsset(asset, kind, files){
    try{
      await pipelineApi('export/asset', {
        kind: kind, id: asset.id, files: files, meta: adoptMeta(asset, kind),
      });
      await syncLoadManifest();
      return {ok:true};
    }catch(error){
      return {ok:false, error:error.message || String(error)};
    }
  }

  async function publishIfConfigured(assetId, kind){
    const target = typeof SYNC !== 'undefined' && SYNC.status && SYNC.status.ueTarget;
    if(!target) return {ok:true, skipped:true, reason:'no-target'};
    const rec = SYNC.manifest && SYNC.manifest.assets && SYNC.manifest.assets[assetId];
    const need = kind === 'machine' ? ['mesh', 'icon'] : ['icon'];
    if(!rec || need.some(function(role){ return !hasAssetFile(rec, role); })){
      return {ok:true, skipped:true, reason:'not-ready'};
    }
    return syncPublishUE([assetId]) || {ok:false, error:'发布失败'};
  }

  async function adoptImage(asset, kind, task, file, nodeId){
    // 上传图标永远优先；机器有 AI 模型时图标以模型渲染图为准。两者都不被概念图覆盖
    if(asset.iconSource === 'upload'){
      return {ok:true, skipped:true, note:'已保留上传图标，未用概念图覆盖'};
    }
    if(kind === 'machine' && asset.model){
      return {ok:true, skipped:true, note:'机器已使用 AI 模型图标，概念图仅保留在管线存档'};
    }
    let icon, icon256;
    try{
      const img = await loadImage(pipelineOutputURLFor(asset.id, kind, file));
      icon = cropSquare(img, 128);        // 资产数据只存 128px
      icon256 = cropSquare(img, 256);     // 写入 _Source 的导出图
    }catch(error){
      return {ok:false, error:'读取概念图失败: ' + error.message};
    }
    const at = new Date().toISOString();
    const name = baseName(file);
    asset.icon = icon;
    asset.iconSource = 'generated';
    asset.generated = asset.generated || {};
    asset.generated.image = {
      taskId: task.taskId || '', nodeId: nodeId, at: at, file: name,
    };
    await persistAsset();
    const exported = await exportAsset(asset, kind, {
      icon: {path: iconPath(kind, asset.id), b64: imageB64(icon256)},
    });
    if(!exported.ok) return Object.assign({}, exported, {applied:true});
    return {ok:true};
  }

  async function adoptModel(asset, kind, task, file, nodeId){
    if(kind === 'element') return {ok:false, error:'元素只支持图标，不支持 3D 模型'};
    const name = baseName(file);
    let scene, transform, baked;
    try{
      const response = await fetch(pipelineOutputURLFor(asset.id, kind, name));
      if(!response.ok) throw new Error('HTTP ' + response.status);
      scene = await fwLoadGLBScene(await response.arrayBuffer());
      transform = fwComputeFitTransform(scene, kind,
        kind === 'machine' ? asset.footprint : '');
      baked = await new Promise(function(resolve, reject){
        fwBakeGLBScene(scene, transform, {
          name: asset.id,
          forgeworks: {generator:'Forgeworks', source:'pipeline-ai',
                       id:asset.id, name:asset.name, kind:kind},
        }, function(result, error){
          if(error) reject(error); else resolve(result);
        });
      });
    }catch(error){
      return {ok:false, error:'处理模型失败: ' + error.message};
    }

    // 缩略图失败不应丢弃已经烘焙好的模型：模型与 mesh 照常落地，图标稍后手动重试
    let thumb128 = '', thumb256 = '', thumb512 = '', thumbError = '';
    try{
      thumb128 = fwRenderGLBThumbnail(scene, transform, 128);
      thumb256 = fwRenderGLBThumbnail(scene, transform, 256);
      thumb512 = fwRenderGLBThumbnail(scene, transform, 512);
    }catch(error){
      thumbError = error.message || String(error);
      thumb128 = ''; thumb256 = ''; thumb512 = '';   // 部分失败时宁可都不写，避免空图标
    }

    const at = new Date().toISOString();
    asset.model = {
      source:'ai', provider: task.provider || '', file: name,
      taskId: task.taskId || '', nodeId: nodeId, generatedAt: at,
      transform: fwNormalizeTransform(transform), autoFit: true,
      triangles: fwCountTriangles(scene),
    };
    asset.generated = asset.generated || {};
    asset.generated.model = {
      taskId: task.taskId || '', nodeId: nodeId, at: at, file: name,
    };

    let iconChanged = false;
    if(thumb128 && kind === 'machine' && asset.iconSource !== 'upload'){
      asset.icon = thumb128;
      asset.iconSource = 'generated';
      asset.generated.image = {
        taskId: task.taskId || '', nodeId: nodeId, at: at, file: name,
      };
      iconChanged = true;
    }else if(thumb128 && kind === 'item' && !(asset.icon && asset.icon.trim())){
      asset.icon = thumb128;
      asset.iconSource = 'generated';
      asset.generated.image = {
        taskId: task.taskId || '', nodeId: nodeId, at: at, file: name,
      };
      iconChanged = true;
    }

    await persistAsset();
    const files = {mesh: {path: asset.id + '.glb', b64: bufToB64(baked)}};
    if(iconChanged){
      files.icon = {path: iconPath(kind, asset.id), b64: imageB64(thumb256)};
    }
    if(kind === 'machine' && thumb512){
      files.preview = {path: asset.id + '_preview.png', b64: imageB64(thumb512)};
    }
    const exported = await exportAsset(asset, kind, files);
    if(!exported.ok) return Object.assign({}, exported, {applied:true});
    const result = {ok:true, triangles: asset.model.triangles};
    if(thumbError) result.warning = '模型已应用，但缩略图生成失败：' + thumbError;
    return result;
  }

  async function adoptAsset(assetId, kind, slot, nodeId, task, file){
    const asset = pipelineFindAsset(kind, assetId);
    if(!asset) return {ok:false, error:'资产已删除: ' + assetId};
    const result = slot === 'image'
      ? await adoptImage(asset, kind, task, file, nodeId)
      : await adoptModel(asset, kind, task, file, nodeId);
    // skipped 表示本次没有改动资产（已有模型/上传图标），不应再触发导出
    if(!result.ok || result.skipped) return result;
    const published = await publishIfConfigured(asset.id, kind);
    if(!published.ok){
      return Object.assign({}, result, {
        warning:'已应用，但导出 UE 失败：' + (published.error || '未知错误'),
      });
    }
    if(published.skipped && published.reason === 'no-target'){
      const note = '已应用到项目（未设置 UE 目标）：' + asset.name;
      return Object.assign({}, result, {
        note: result.warning ? note + '（' + result.warning + '）' : note,
      });
    }
    return result;
  }

  function refreshExportNode(assetId, kind){
    if(cur !== 'pipeline' || PIPELINE.assetId !== assetId || PIPELINE.kind !== kind) return;
    if(!pipelineBridgeReady() || !PIPELINE.graph) return;
    if(!PIPELINE.graph.nodes.some(function(node){ return node.type === 'export'; })) return;
    pipelineApi('pipeline/run', {assetId:assetId, kind:kind, nodeId:'export'})
      .then(function(result){
        if(PIPELINE.assetId !== assetId || PIPELINE.kind !== kind) return;
        PIPELINE.graph = result.graph;
        renderPipelineView();
      })
      .catch(function(){ /* 导出节点刷新失败不影响已落地的资产 */ });
  }

  /**
   * Provider 任务成功后的落地入口。
   * force=true 用于用户点“重新应用”；自动轮询按 generated.<slot>.taskId 幂等。
   */
  function pipelineAdoptTask(assetId, kind, nodeId, nodeType, task, force){
    if(!task || task.state !== 'success'){
      return Promise.resolve({ok:false, error:'任务尚未成功'});
    }
    if(nodeType !== 'textToImage' && nodeType !== 'imageTo3D'){
      return Promise.resolve({ok:true, skipped:true});
    }
    if(typeof pipelineBridgeReady !== 'function' || !pipelineBridgeReady()){
      return Promise.resolve({ok:false, error:'Bridge 未连接'});
    }
    if(typeof syncProjectReady !== 'function' || !syncProjectReady()){
      return Promise.resolve({ok:false, error:'未打开 Forgeworks 项目'});
    }
    const slot = nodeType === 'textToImage' ? 'image' : 'model';
    if(slot === 'model' && kind === 'element') return Promise.resolve({ok:true, skipped:true});
    const output = task.output || {};
    const file = slot === 'image' ? output.imagePath : output.modelPath;
    if(!file) return Promise.resolve({ok:false, error:'任务没有输出文件'});
    const asset = pipelineFindAsset(kind, assetId);
    if(!asset) return Promise.resolve({ok:false, error:'资产已删除: ' + assetId});
    const done = asset.generated && asset.generated[slot];
    if(!force && done && done.taskId && done.taskId === task.taskId){
      return Promise.resolve({ok:true, skipped:true});
    }

    const key = kind + ':' + assetId;
    const previous = PIPELINE.applyQueue[key] || Promise.resolve();
    PIPELINE.applyStatus[assetId] = '应用中…';
    PIPELINE.applyErrors[assetId] = '';
    if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();

    const next = previous.then(function(){
      // 排队期间前一次应用可能已完成，必须重新检查幂等，避免同一任务导出两次
      const latest = pipelineFindAsset(kind, assetId);
      const doneNow = latest && latest.generated && latest.generated[slot];
      if(!force && doneNow && doneNow.taskId && doneNow.taskId === task.taskId){
        return {ok:true, skipped:true, duplicate:true};
      }
      return adoptAsset(assetId, kind, slot, nodeId, task, file);
    }).then(function(result){
      if(!result.ok){
        PIPELINE.applyStatus[assetId] = result.applied ? '导出失败' : '应用失败';
        PIPELINE.applyErrors[assetId] = result.error || '未知错误';
        if(typeof syncLog === 'function') syncLog('自动应用失败：' + PIPELINE.applyErrors[assetId], 'warn');
        toast((result.applied ? '已应用到资产，但导出失败：' : '应用失败：') + PIPELINE.applyErrors[assetId]);
        if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
        else render();
        return result;
      }
      if(result.duplicate){
        PIPELINE.applyStatus[assetId] = '已应用';
        PIPELINE.applyErrors[assetId] = '';
        if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
        return result;
      }
      if(result.skipped){
        PIPELINE.applyStatus[assetId] = '已跳过';
        PIPELINE.applyErrors[assetId] = result.note || '';
        if(result.note) toast(result.note);
        if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
        else render();
        return result;
      }
      PIPELINE.applyStatus[assetId] = '已应用';
      PIPELINE.applyErrors[assetId] = result.warning || '';
      const what = slot === 'image' ? 'AI 图标' : 'AI 模型';
      toast(result.note || result.warning || ('已应用' + what + '：' + asset.name));
      if(cur === 'pipeline' && PIPELINE.assetId === assetId) refreshExportNode(assetId, kind);
      else render();
      return result;
    }, function(error){
      PIPELINE.applyStatus[assetId] = '应用失败';
      PIPELINE.applyErrors[assetId] = error.message || String(error);
      if(typeof syncLog === 'function') syncLog('自动应用失败：' + PIPELINE.applyErrors[assetId], 'warn');
      toast('应用失败：' + PIPELINE.applyErrors[assetId]);
      if(cur === 'pipeline' && PIPELINE.assetId === assetId) renderPipelineView();
      return {ok:false, error:PIPELINE.applyErrors[assetId]};
    });

    PIPELINE.applyQueue[key] = next;
    next.finally(function(){
      if(PIPELINE.applyQueue[key] === next) delete PIPELINE.applyQueue[key];
    });
    return next;
  }

  window.pipelineAdoptTask = pipelineAdoptTask;
})();
```

- [ ] **Step 7: 接入脚本**

在 `index.html` 中 `js/pipeline.js` 的 `<script>` 之前加入：

```html
<script src="js/pipeline-adopt.js?v=20261024a1"></script>
```

在 `tests/smoke.html` 中 `../js/pipeline.js` 的 `<script>` 之前加入：

```html
<script src="../js/pipeline-adopt.js?v=20261024a1"></script>
```

- [ ] **Step 8: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 两个新 check 通过，`summary.fail == 0`。

- [ ] **Step 9: 提交**

```bash
git add js/pipeline-adopt.js js/pipeline.js index.html tests/smoke.html
git commit -m "feat(pipeline): 生成成功后自动回填资产并导出

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: 管线卡片展示应用/导出结果与手动回填

**Files:**
- Modify: `js/pipeline.js`（`pipelineNodeCard`、`pipelineWireCard`、`pipelineOpenAsset`）
- Modify: `js/pipeline-adopt.js`（导出 `pipelineFindAsset` 供卡片复用）
- Test: `tests/smoke.html`

**Interfaces:**
- Consumes: Task 11 的 `pipelineAdoptTask` / `PIPELINE.applyStatus` / `PIPELINE.applyErrors`；Task 3 的 export 节点 `result.output`；Task 4 的 `asset.generated.*.taskId`。
- Produces: `pipelineFindAsset(kind, assetId) -> asset|undefined`（全局）；成功任务卡片显示“应用结果 / 重新应用”“查看资产”，导出节点显示 `sourceDir`，失败原因显示在卡片内。

- [ ] **Step 1: 写失败 smoke check**

在 `tests/smoke.html` 的 `runSync()` 中追加：

```js
    check('管线卡片为成功任务提供应用按钮', function(){
      var prev = PIPELINE.assetId;
      PIPELINE.assetId = S.machines[0].id;
      try{
        var node = {id:'n1', type:'textToImage', x:0, y:0, params:{},
          result:{providerTask:{state:'success', taskId:'t1',
                  output:{imagePath:'a.png'}}}};
        var html = pipelineNodeCard(node);
        return html.indexOf('data-apply="n1"') >= 0 ? 'ok' : '未提供应用按钮';
      }finally{ PIPELINE.assetId = prev; }
    });
    check('导出节点展示 manifest 结果', function(){
      var node = {id:'export', type:'export', x:0, y:0, params:{},
        result:{state:'done', output:{sourceDir:'_Source/机器/M1'}}};
      var html = pipelineNodeCard(node);
      return html.indexOf('_Source/机器/M1') >= 0 ? 'ok' : '未展示导出目录';
    });
    check('管线可跳转到资产编辑器', function(){
      return typeof pipelineOpenAsset === 'function' ? 'ok' : '未定义';
    });
```

- [ ] **Step 2: 运行 smoke 确认失败**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 三个 check FAIL。

- [ ] **Step 3: 暴露资产查找函数**

在 `js/pipeline-adopt.js` 末尾：

```js
  window.pipelineAdoptTask = pipelineAdoptTask;
```

改为：

```js
  window.pipelineFindAsset = pipelineFindAsset;
  window.pipelineAdoptTask = pipelineAdoptTask;
```

- [ ] **Step 4: 卡片加入应用状态与按钮**

在 `pipelineNodeCard` 中 `const task = node.result && node.result.providerTask;` 之后加入：

```js
  const currentAsset = pipelineFindAsset(PIPELINE.kind, PIPELINE.assetId);
  const applySlot = node.type === 'textToImage' ? 'image'
    : (node.type === 'imageTo3D' && PIPELINE.kind !== 'element' ? 'model' : '');
  const generated = (currentAsset && currentAsset.generated) || {};
  const applied = !!(applySlot && task && task.taskId
    && generated[applySlot] && generated[applySlot].taskId === task.taskId);
  const applyStatus = applySlot ? (PIPELINE.applyStatus[PIPELINE.assetId] || '') : '';
  const applyError = applySlot ? (PIPELINE.applyErrors[PIPELINE.assetId] || '') : '';
  const exportOutput = node.type === 'export' && node.result && node.result.output;
```

把模板中的：

```js
<button data-delete-node="${pipelineEscape(node.id)}">删除</button></div>${outputLink}
```

改为（应用按钮留在 `pipeline-node-actions` 内）：

```js
<button data-delete-node="${pipelineEscape(node.id)}">删除</button>${applySlot && task && task.state === 'success' ? `<button data-apply="${pipelineEscape(node.id)}">${applied ? '重新应用' : '应用结果'}</button>` : ''}${applied ? `<button data-open-asset="${pipelineEscape(node.id)}">打开资产</button>` : ''}</div>${outputLink}
```

在 `</div>${outputLink}${historyHTML}` 之后加入：

```js
    ${exportOutput ? `<small class="pipeline-stage">已导出：${pipelineEscape(exportOutput.sourceDir || '')}</small>` : ''}
    ${applied
      ? `<small class="pipeline-stage">已应用到 ${pipelineEscape((currentAsset && currentAsset.name) || '资产')}${generated[applySlot].at ? ' · ' + pipelineEscape(new Date(generated[applySlot].at).toLocaleString('zh-CN')) : ''}</small>`
      : (applyStatus ? `<small class="pipeline-stage">${pipelineEscape(applyStatus)}</small>` : '')}
    ${applyError ? `<small class="pipeline-error">${pipelineEscape(applyError)}</small>` : ''}
```

- [ ] **Step 5: 绑定应用/查看按钮**

在 `pipelineWireCard` 的 `[data-preview-model]` 绑定之后加入：

```js
  card.querySelectorAll('[data-apply]').forEach(button=>button.onclick=event=>{
    event.stopPropagation();
    const node=PIPELINE.graph.nodes.find(item=>item.id===button.dataset.apply);
    const task=node&&node.result&&node.result.providerTask;
    if(task) pipelineAdoptTask(PIPELINE.assetId,PIPELINE.kind,node.id,node.type,task,true);
  });
  card.querySelectorAll('[data-open-asset]').forEach(button=>button.onclick=event=>{
    event.stopPropagation();
    pipelineOpenAsset(PIPELINE.assetId,PIPELINE.kind);
  });
```

- [ ] **Step 6: 加入资产跳转函数**

在 `pipelineReturn` 之后加入：

```js
function pipelineOpenAsset(assetId, kind){
  const coll = kind === 'machine' ? 'machines' : (kind === 'item' ? 'items' : 'elements');
  const targetView = kind === 'machine' ? 'machines' : 'assets';
  cur = targetView;
  render();
  syncHash(targetView);
  openEditor(coll, assetId);
}
```

- [ ] **Step 7: 运行 smoke 确认通过**

Run: Task 4 Step 2 的 smoke 命令。
Expected: 三个新 check 通过，`summary.fail == 0`。

- [ ] **Step 8: 提交**

```bash
git add js/pipeline.js js/pipeline-adopt.js tests/smoke.html
git commit -m "feat(pipeline): 卡片展示回填与导出结果并支持手动应用

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: 全量验证与 60 秒验收

**Files:**
- Test: `tests/test_bridge_projects.py` / `tests/test_fw_project.py` / `tests/test_fw_pipeline.py` / `tests/smoke.html`
- Verify: `tools/bridge.py`、`tools/fw_project.py`、`tools/fw_pipeline.py`、全部前端改动

**Interfaces:**
- Consumes: Task 0-12 的全部产物。
- Produces: 可复现的回归结果与人工验收记录；不再修改功能代码（除非验证暴露缺陷，回到对应任务修复）。

- [ ] **Step 0: 统一版本戳**

Task 6 之后又改了多个 JS 文件；把 `index.html` 与 `tests/smoke.html` 中所有 `?v=20261024a1` 替换为 `?v=20261024a2`，确保浏览器不会用旧缓存。

```bash
git add index.html tests/smoke.html
git commit -m "chore(web): 统一自动回填功能的前端版本戳

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 1: 跑 Python 全量测试**

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: 全部 PASS，包含 `BridgeExportMergeTest`、`PipelineExportNodeTest`、`PublishToUETest` 中新增的物品 mesh 用例。

- [ ] **Step 2: 跑前端 smoke**

```bash
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless --no-sandbox \
  --use-gl=swiftshader --enable-unsafe-swiftshader --virtual-time-budget=8000 --dump-dom \
  "file:///F:/workspace/ue/Forgeworks/tests/smoke.html" > /tmp/smoke.html
sed -n '/SELFTEST_JSON_START/,/SELFTEST_JSON_END/p' /tmp/smoke.html
```

Expected: `summary.fail == 0`。

- [ ] **Step 3: 人工验收（60 秒 SLA）**

启动 Bridge 并打开浏览器：

```bash
python tools/bridge.py
```

逐项执行：

1. 新建或打开项目，给机器配置 Ark/Tripo key，进入机器 `M1` 的管线，运行“概念图生成”。
2. 任务成功后**不离开管线页**，观察卡片出现“已应用到资产”，并在 60 秒内：
   - 机器列表图标变成概念图；
   - `_Source/机器/<中文名>/M1_icon.png` 存在，manifest 的 `files.icon` 非空；
   - 若配置了 UE 目标，`<UE>/Forgeworks/` 下对应图标随之更新。
3. 同一机器运行“图生 3D”成功：
   - 卡片显示“已应用”，机器列表出现 `AI` 徽标；
   - 编辑机器 → “变换模型”打开 3D 编辑器，只显示 9 个整体变换输入；
   - 调整位置/旋转/缩放并保存，`machine.model.autoFit == false`，再次手动导出后 manifest `meta.modelHash` 变化；
   - “适配占地”重新计算自动缩放；“重置变换”回到打开编辑器时的已应用变换；“恢复程序化几何”删除 `machine.model` 且列表回到程序化几何。
4. 物品：概念图生成后 `_Source/物品/图标/<中文名>/<ID>.png` 更新；图生 3D 后 `<ID>.glb` 存在，manifest 同时保留 `icon` 与 `mesh`，发布 UE 后两者都复制。
5. 元素：概念图生成后 `<ID>.png` 更新，元素不支持“图生 3D”按钮或应用时提示明确错误。
6. 同一任务重复轮询/手动点“重新应用”不会产生重复任务，也不会把已有 `mesh` 或 `icon` 覆盖成空。
7. 重启浏览器后，资产图标、AI 模型、整体变换仍从 `content.json` / localStorage 恢复；已应用任务不再自动重复导出。
8. 上传自定义图标后运行机器“图生 3D”：`iconSource == 'upload'`，模型应用后图标保持上传图，不被缩略图替换。

- [ ] **Step 4: 检查工作区与提交边界**

```bash
git status --short
```

Expected: 仅包含本计划的提交；`?? tests/test_bridge_picker.py` 仍然存在且未被 `git add`。若出现该文件被暂存，执行：

```bash
git restore --staged tests/test_bridge_picker.py
```

- [ ] **Step 5: 记录验收结果**

在 `docs/superpowers/plans/2026-10-24-pipeline-auto-adopt-export.md` 末尾追加：

```markdown
## 验收记录

- 日期：2026-10-24
- Python：<通过数> 项通过
- Smoke：<通过数> 项通过，0 失败
- 60 秒 SLA：机器图标 / 物品图标 / 元素图标 / 机器模型 / 物品模型 <逐项打勾>
- 备注：<未覆盖的设备或 Provider 情况>
```

```bash
git add docs/superpowers/plans/2026-10-24-pipeline-auto-adopt-export.md
git commit -m "docs(pipeline): 记录自动回填与导出验收结果

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

## 验收记录

- 日期：2026-10-24
- Python：运行 122 项，119 项通过，3 项失败（既有 Windows 路径/分隔符/平台断言，与本分支无关，未改代码）
  - `test_fw_pipeline.PipelineGraphTest.test_manifest_source_dir_wins_over_kind_fallback`
  - `test_ue_pipeline.UEPipelineTest.test_import_plan_uses_project_content_path_and_meter_scale`
  - `test_bridge_providers.CcSwitchImportTest.test_import_writes_key_endpoint_and_model`（POSIX 文件模式 0o600 断言在 Windows 上得到 0o666）
- Smoke：95 项通过，0 失败（`summary.total == 95`、`summary.fail == 0`、`runtimeErrors == 0`）
- 60 秒 SLA：机器图标 未执行（待人工验收） / 物品图标 未执行（待人工验收） / 元素图标 未执行（待人工验收） / 机器模型 未执行（待人工验收） / 物品模型 未执行（待人工验收）
- 备注：本环境未启动 Bridge、未接入真实 Ark/Tripo Provider 与 UE，60 秒 SLA 及依赖实机链路的项目均未验证；上述 3 项 Python 失败为既有环境断言。

