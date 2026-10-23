# AI 接入：MCP 与安全写入

> 2026-10-23 · 让 AI 通过 MCP 直接读取和编辑 Forgeworks 项目内容。

## 概览

```
AI 客户端 ──stdio JSON-RPC──▶ tools/mcp_forgeworks.py ──HTTP──▶ Bridge (127.0.0.1:8787)
                                                              │
                                              project.json + _Source/_Sync
```

- MCP 服务器零第三方依赖（Python 标准库），只连本机 Bridge。
- Bridge 继续负责文件系统、manifest、Blender、UE 发布；MCP 只是另一层入口。
- 浏览器与 AI 改同一份 `project.json`：写入带 revision 乐观锁，改动通过 SSE 实时广播。

## 启动

1. 启动 Bridge（界面与 API 一起）：

   ```bash
   python3 tools/bridge.py          # 默认 8787
   ```

2. `.mcp.json` 已注册项目级 MCP，Claude Code 重启会话后自动加载：

   ```json
   {
     "mcpServers": {
       "forgeworks": {
         "type": "stdio",
         "command": "python3",
         "args": ["tools/mcp_forgeworks.py"],
         "env": { "FORGEWORKS_BRIDGE": "http://127.0.0.1:8787" }
       }
     }
   }
   ```

   端口不是 8787 时，改 `FORGEWORKS_BRIDGE` 即可。

## 工具清单

| 工具 | 作用 |
| --- | --- |
| `forgeworks_status` | 当前项目、UE 目标、Blender 状态 |
| `forgeworks_get_content` | 读取整份 `project.json` 与 `revision` |
| `forgeworks_list_entities` | 列出集合概要（可指定 `coll`） |
| `forgeworks_get_entity` | 读取单个实体 |
| `forgeworks_upsert_entity` | 新增/整体替换实体（可带 `baseRevision`） |
| `forgeworks_delete_entity` | 删除实体（可带 `baseRevision`） |
| `forgeworks_scan` | 扫描 `_Source` 核对 manifest |
| `forgeworks_publish_to_ue` | 发布资产到 UE（可传 `ids`） |
| `forgeworks_open_project` | 打开/绑定项目目录 |
| `forgeworks_create_project` | 新建项目 |
| `forgeworks_conflicts` | 查看待裁决文件冲突 |
| `forgeworks_pipeline_get` | 读取生成管线图 |
| `forgeworks_pipeline_save` | 保存生成管线图 |
| `forgeworks_pipeline_run` | 运行管线节点 |

集合 `coll` 取值：`elements`、`items`、`machines`、`recipes`、`techs`。

## 安全写入

### revision 乐观锁

`project.json` 的字节 sha256 就是 `revision`。读取内容时一并返回；写入时可选传 `baseRevision`：

- 与磁盘当前 revision 一致 → 写入成功，返回新 `revision`。
- 不一致 → HTTP 409，**不覆盖**，返回 `{conflict:true, revision}`；调用方需重新读取后重试。

实体接口在进程内用一把锁串行化 read-modify-write，避免并发插入丢数据。

### 实体级写入

`POST /api/content/entity`、`POST /api/content/entity/delete` 只改目标集合中的一行，
不必整包回传，冲突面更小：

```json
{ "coll": "elements", "entity": { "id": "Fe", "name": "铁" }, "baseRevision": "…" }
```

### 浏览器侧合并

界面自动保存同样带 `baseRevision`。撞上 409 时前端做三方合并：

- 以最后载入的内容为基线，逐实体判断「本地改 / 远端改 / 双方都改」。
- 单方修改直接采用；双方都改时保留本地版本，并提示冲突数量。
- 合并后用新 revision 重试保存一次。

### SSE 实时更新

任何写入成功后 Bridge 广播：

```json
{ "kind": "content.changed", "data": { "revision": "…", "source": "mcp", "clientId": null, "entity": {…} } }
```

页面收到后：

- 自己的写入（`clientId` 相同）忽略。
- 编辑器打开或本地还有待保存改动时，标记为待同步，关闭编辑器后再载入。
- 其余情况立即重载内容并重绘。

## 边界

- 仅监听 `127.0.0.1`，MCP 不暴露到网络。
- 不改 UE 内容浏览器导入行为；发布仍是磁盘镜像。
- 整包替换接口 `POST /api/project/content` 保留，但界面与 MCP 都优先走实体接口。

## 自测

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile tools/mcp_forgeworks.py
node --check js/sync.js
```
