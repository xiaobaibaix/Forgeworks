# P1 执行入口（先读这个）

> 这是挖掘机尺寸规格/校准/端口改造 P1 的交接入口。P1 **尚未开始实现**；本分支只包含设计文档、实施计划和可运行基线代码。

## 1. 当前交接状态

- 分支：`feat/dimension-spec-p1`
- 远程：`origin` → `git@github.com:xiaobaibaix/Forgeworks.git`
- 设计文档：`docs/superpowers/specs/2026-10-27-dimension-connector-assembly-design.md`
- 实施计划：`docs/superpowers/plans/2026-10-27-dimension-spec-fit-ports.md`
- 基线代码提交：`d0cb4cf`
- 计划文档提交：`d5dcbfe`
- 入口文档提交：以 `git log -1 --oneline` 为准

P2（三视图/标注）和 P3（层级 mate 装配）目前只在设计文档中定义，不在本入口的执行范围内。

## 2. 获取代码

新机器首次拉取：

```bash
git clone git@github.com:xiaobaibaix/Forgeworks.git
cd Forgeworks
git switch feat/dimension-spec-p1
```

已有仓库：

```bash
git fetch origin
git switch feat/dimension-spec-p1
git pull --ff-only
```

确认当前提交：

```bash
git log -1 --oneline
git status --short
```

工作区应没有已修改的跟踪文件。若有未跟踪的 `tmp_*` 或 `partModel_*`，那是旧机器上的诊断产物，不会随 git 过来，也不影响实施。

## 3. 开工前必读

按顺序读：

1. 本文件：执行方式、环境、边界。
2. `docs/superpowers/plans/2026-10-27-dimension-spec-fit-ports.md`：8 个 TDD 任务，具体到文件、接口、测试代码和实现代码。
3. `docs/superpowers/specs/2026-10-27-dimension-connector-assembly-design.md`：为什么这样设计、JSON schema、错误码、验收标准。

不要只看计划就动手。计划里的接口已按基线代码核对过，但实施时仍以仓库真实代码为准。

## 4. 环境要求

- Python 用 `python` 或 `py`，**不要用 `python3`**（Windows Store 别名可能直接失败）。
- 测试框架是标准库 `unittest`，本机没有 pytest，也不要安装 pytest 来跑计划。
- Blender 集成测试使用 Blender 5.2.3 LTS。默认路径：

  ```text
  E:\SteamLibrary\steamapps\common\Blender\blender.exe
  ```

  路径不同时用 `FW_BLENDER` 指向实际可执行文件；找不到 Blender 时相关测试会跳过，但不算代码失败。
- 前端是零构建静态文件，改完 JS 用 `node --check` 做语法检查即可，不需要 npm build。

## 5. 开工前基线测试

在仓库根目录运行：

```bash
python -m unittest tests.test_fw_pipeline tests.test_fw_providers tests.test_bridge_providers tests.test_fw_parts -v

FW_BLENDER='E:\SteamLibrary\steamapps\common\Blender\blender.exe' \
  python -m unittest tests.test_fw_blender -v

node --check js/pipeline.js
node --check js/data/prompts.js
```

2026-10-27 在交接机器上的基线：

- 非 Blender：139 个测试，138 通过。
- 唯一失败：`tests.test_bridge_providers.CcSwitchImportTest.test_import_writes_key_endpoint_and_model`。
  原因：Windows 不保留 `0o600` 权限，断言 `438 != 384`；这是环境问题，不是代码逻辑问题。
- Blender：8 个测试全过。
- 两个 JS 文件语法检查通过。

如果新机器上出现**其他**基线失败，先停下来报告失败用例和完整错误，不要带着未知失败开始改代码。

## 6. 执行方式

从 Task 1 开始，按计划顺序执行，不要跳任务。

推荐入口：

```text
superpowers:subagent-driven-development
```

备选：

```text
superpowers:executing-plans
```

执行要求：

- 每个任务先写失败测试，再写最小实现，再跑该任务测试。
- 每个任务结束时跑到计划指定的测试命令；计划里的 `- [ ]` 步骤逐项完成。
- 计划默认在测试检查点停下，不自动 `git commit`；是否提交由你或用户决定。
- 遇到计划与实际代码不一致时，先读真实代码确认接口，不要静默改成另一种设计；无法判断时停下来报告。
- 不要把 P2/P3 的内容提前塞进 P1。

## 7. 任务顺序与检查点

| 任务 | 产物 | 主要检查点 |
|---|---|---|
| Task 1 | `tools/fw_spec.py` + `tests/test_fw_spec.py` | spec schema、模板、校验、读写、角色、端口锚点 |
| Task 2 | 24 个正交朝向、fit 选择、端口解析、mate 树 | `tests.test_fw_spec` 全部通过 |
| Task 3 | `fw_providers.analyze_spec` | `tests.test_fw_providers`，含 mock Ark 视觉响应 |
| Task 4 | Blender `fit` 模式 | `tests.test_fw_blender`，含真实 GLB 校准 |
| Task 5 | `fw_pipeline` 节点类型与 spec 读取 | `tests.test_fw_pipeline` 的 spec 读取测试 |
| Task 6 | `execute_local` 的 blueprint/ports/fit 接线与缓存 | `tests.test_fw_pipeline` 的执行测试 |
| Task 7 | Bridge blueprint 门禁、spec 落盘、partImage 端口注入 | `tests.test_bridge_providers` |
| Task 8 | JS 节点/端口/参数/面板、CSS、静态镜像测试 | 前端测试 + `node --check` + 全量回归 |

具体测试类名和断言以计划文件为准；上表只是导航，不替代计划。

## 8. 安全与兼容边界

- **不发起真实付费 Provider 请求。** 所有新测试必须 mock `fw_providers._ark_request` 或 `fw_providers.analyze_spec`。
- **不打印、不提交 `tools/bridge_config.json`。** 该文件含 Ark key，已在 `.gitignore` 中；错误信息里也不能回显 key。
- 新增远程节点（`blueprint`）必须要求 `confirmRemote: true` 并通过 loopback 同源校验。
- `schemaVersion` 保持 `1`；旧 `assemble`、KDTree snap、无 spec 时的 `partModel` 行为不能改变。
- 新 JSON 路径使用相对资产目录的 POSIX 斜杠；spec 放在 `<asset>/pipeline/spec.json`。
- 错误信息以错误码开头：`SPEC_MISSING`、`SPEC_INVALID`、`SPEC_UNANCHORED`、`PART_ROLE_MISSING`、`FIT_ASPECT_MISMATCH`、`FIT_ORIENTATION_AMBIGUOUS`、`PORT_MISSING`。

## 9. 完成定义

P1 完成需要同时满足：

1. 计划中的 8 个任务全部完成，所有 `- [ ]` 步骤已执行。
2. 新测试全部通过，旧测试除已知 Windows 权限失败外没有回归。
3. Blender `fit` 测试在配置了 `FW_BLENDER` 的机器上通过。
4. `node --check js/pipeline.js` 和 `node --check js/data/prompts.js` 通过。
5. `git diff --check` 通过。
6. 没有真实 Provider 调用，没有 key 泄漏。
7. 汇总改动文件、测试命令和测试结果，交给用户复核。

P1 不要求真实调用 Provider 跑通整条业务链；用 mock 的单元/集成测试验收即可。需要真实调用时，必须先得到用户明确确认。

## 10. 遇到阻塞时

停下来并报告：

- 哪个任务、哪条命令
- 完整失败输出
- 你确认到的真实接口与计划不一致之处
- 你建议的最小修正方案

不要在未确认的情况下改设计、改 schema 或扩大范围。
