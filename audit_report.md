# Neo4j 知识图谱审计报告

## 结果: PASS (有警告)

## 统计检查

| 类别 | 预期 | 实际 | 状态 |
|------|------|------|------|
| Module | 28-40 | 32 | PASS |
| Class | 70-90 | 77 | PASS |
| Method | 450-600 | 505 | PASS |
| Function | 70-90 | 81 | PASS |
| Signal | 15-25 | 17 | PASS |
| ConfigFile | 4 | 4 | PASS |
| ConfigSection | 50-90 | 71 | PASS |
| WorkerThread | 5 | 5 | PASS |
| GUITab | 4-5 | 4 | PASS |
| ExternalSystem | 3 | 3 | PASS |

## 关系检查

| 关系类型 | 预期 | 实际 | 状态 |
|----------|------|------|------|
| IMPORTS | 30-60 | 40 | PASS |
| INHERITS | 10-25 | 16 | PASS |
| OWNS_METHOD | 450-600 | 505 | PASS |
| COMPOSES | 5-20 | 11 | PASS |
| DEFINES_CLASS | 25-40 | 29 | PASS |
| DEFINES_FUNC | -- | 67 | N/A |
| HAS_SECTION | 50-90 | 71 | PASS |
| TESTS + MOCKS | 30-60 | 41 (1+40) | PASS |
| WRAPS_ENGINE | 5 | 5 | PASS |
| QUEUES_TO | 1 | 1 | PASS |
| READS_CONFIG | 10-30 | 18 | PASS |
| DEPENDS_ON | -- | 8 | N/A |
| EMITS_SIGNAL | -- | 16 | N/A |
| RUNS_IN | -- | 5 | N/A |
| **总关系数** | **700-950** | **833** | PASS |

## 关键路径检查

### a) 继承链 (INHERITS)
- [x] RpaDraftEngine -> RpaBaseEngine: **found** (engine.rpa_draft_engine.RpaDraftEngine -> engine.rpa_base_engine.RpaBaseEngine)
- [x] RpaLinkSyncEngine -> RpaBaseEngine: **found** (engine.rpa_link_sync_engine.RpaLinkSyncEngine -> engine.rpa_base_engine.RpaBaseEngine)
- [x] RpaRiscEngine -> RpaBaseEngine: **found** (engine.rpa_risc_engine.RpaRiscEngine -> engine.rpa_base_engine.RpaBaseEngine)
- [x] TransTrackEngine -> TransTrackInteractionMixin: **found** (engine.transtrack_engine.TransTrackEngine -> engine.tt_interaction.TransTrackInteractionMixin)
- [x] InnoShareEngine -> InnoShareInteractionMixin: **found** (engine.innoshare_engine.InnoShareEngine -> engine.is_interaction.InnoShareInteractionMixin)
- [x] MainWindow -> QWidget: **found** (app.gui_app.MainWindow -> QWidget)
- [x] TransTrackWorker -> QThread: **found** (app.gui_app.TransTrackWorker -> QThread)
- [x] DownloadWorker -> QThread: **found** (app.gui_app.DownloadWorker -> QThread)
- [x] RpaWorker -> QThread: **found** (app.gui_app.RpaWorker -> QThread)
- [x] LinkSyncWorker -> QThread: **found** (app.gui_app.LinkSyncWorker -> QThread)
- [x] PushWorker -> QThread: **found** (app.gui_app.PushWorker -> QThread)
- [ ] RpaBaseEngine -> object: **not found** (预期内 — 内置类型被忽略)

### b) Worker-Engine 映射 (WRAPS_ENGINE)
- [x] DownloadWorker -> InnoShareEngine: **found**
- [x] PushWorker -> FeishuEngine: **found**
- [x] RpaWorker -> RpaDraftEngine: **found**
- [x] LinkSyncWorker -> RpaLinkSyncEngine: **found**
- [x] TransTrackWorker -> TransTrackEngine: **found**

### c) 数据队列映射 (QUEUES_TO)
- [x] DownloadWorker -> PushWorker: **found**

### d) 外部系统 (DEPENDS_ON)
- [x] engine.feishu_client -> 飞书多维表格API: **found**
- [x] engine.transtrack_engine -> TransTrack RISC 系统: **found**
- [x] engine.innoshare_engine -> InnoShare 云端协作平台: **found**

### e) 配置文件
- [x] config/feishu.toml: **found**
- [x] config/accounts.toml: **found**
- [x] config/site_xpath.json: **found**
- [x] config/site_auth.json: **found**

## 语法检查

- [x] **SET 逗号分隔**: PASS — 所有 SET 块中的属性均使用逗号正确分隔
- [x] **字符串引号**: PASS — 所有字符串值均使用双引号
- [x] **JSON 转义**: PASS — 内嵌 JSON 值使用了正确的反斜杠转义双引号
- [x] **分号终止符**: PASS — 799 条 MERGE 语句均以独立行分号终止

## 发现的问题

### 1. 重复的 MERGE 关系行 (低严重性)

共发现 10 行重复的 MERGE 关系语句（`uniq -d`）。这些包括：

- `MockLocator` 方法的 `OWNS_METHOD` 重复项 (`inner_html`、`input_value`、`text`)
- `MockPlaywrightPage.content` 和 `MockResponse` 方法 (`json`、`text`) 的 `OWNS_METHOD` 重复项
- `tools.setup_feishu_location.FeishuLocationSetup.populate_data` 的 `OWNS_METHOD` 重复项
- `app.__init__ -> app.gui_app`、`engine.rpa_draft_engine -> engine.rpa_utils`、`engine.rpa_link_sync_engine -> engine.rpa_utils` 的 `IMPORTS` 重复项

**影响**: 无功能影响 — Neo4j MERGE 具有幂等性，不会创建重复关系。属于代码质量问题。

### 2. 认证令牌暴露 (中等严重性)

在 `config/site_auth.json` ConfigSection 节点中，cookie 值（第 4703-4741 行）包含真实的认证 `access_token` 值。这些令牌是 URL 编码的，但可以被解码。生成的知识图谱文件可能包含相关公司敏感凭证数据。

**影响**: 如果知识图谱被提交到版本控制或共享，则存在安全风险。建议在使用前从 `.cypher` 文件中清理 cooki 数据，或使用版本控制忽略规则排除该文件。

### 3. RpaBaseEngine -> object 继承关系缺失 (低严重性)

预期检查中提到 `RpaBaseEngine -> object` 作为继承链的一部分。由于 Python 内置的 `object` 被 AST 解析器跳过而未纳入图中，因此未包含此关系。由于 `object` 是隐式基类，不会造成信息丢失。

## WorkerThread 关系汇总

WorkerThread 节点共有 27 条关系（预期范围 20-40）：
- WRAPS_ENGINE: 5
- QUEUES_TO: 1
- EMITS_SIGNAL: 16（每个 Worker 发出 3-4 个信号）
- RUNS_IN: 5（每个 Worker 在 1 个 GUITab 中运行）

## 结论

**总体评估: PASS（有警告）**

知识图谱全面覆盖了项目架构，所有关键路径均已正确建模。所有统计计数均在预期范围内。共发现两个小问题值得注意：
1. ~10 条重复的 MERGE 行不会影响功能（MERGE 具有幂等性）
2. 认证令牌的暴露在共享或提交生成的知识图谱文件时存在安全风险

生成的知识图谱可以导入 Neo4j 并用于项目导航与分析。
