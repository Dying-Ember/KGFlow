# V2 知识图谱审计报告

## 结果: FAIL

**阻断性问题:** EMITS_SIGNAL_IN 关系数为 0（38 个 `self.X.emit(...)` 调用被检测到但全部未能匹配到 Signal 节点）。

---

## V1 回归检查（V1 关系必须完整保留）

| 关系类型 | 预期 | 实际 | 状态 |
|----------|------|------|------|
| IMPORTS | ~40 | 40 | PASS |
| DEFINES_CLASS | ~30 | 30 | PASS |
| DEFINES_FUNC | ~81 | 96 | PASS (含 tools/* 新增) |
| INHERITS | ~16 | 16 | PASS |
| OWNS_METHOD | ~505 | 507 | PASS |
| COMPOSES | ~11 | 11 | PASS |
| READS_CONFIG | ~18 | 18 | PASS |
| HAS_SECTION | ~71 | 71 | PASS |
| TESTS | ~1 | 1 | PASS (注: 映射表仅覆盖6个测试文件) |
| MOCKS | ~40 | 40 | PASS |
| EMITS_SIGNAL | ~16 | 16 | PASS |
| RUNS_IN | ~5 | 5 | PASS |
| QUEUES_TO | ~1 | 1 | PASS |
| WRAPS_ENGINE | ~5 | 5 | PASS |
| DEPENDS_ON | ~8 | 8 | PASS |

**V1 回归结论:** 所有 V1 节点类型和关系类型完整保留，数量在预期范围内。

### V1 节点数量对比

| 节点类型 | 预期 | 实际 | 状态 |
|----------|------|------|------|
| Module | ~32 | 32 | PASS |
| Class | ~77 | 78 | PASS |
| Method | ~505 | 507 | PASS |
| Function | ~81 | 110 | PASS (增长来自 tools/*.py) |
| Signal | ~17 | 17 | PASS |
| ConfigFile | ~4 | 4 | PASS |
| ConfigSection | ~71 | 71 | PASS |
| WorkerThread | ~5 | 5 | PASS |
| GUITab | ~4 | 4 | PASS |
| ExternalSystem | ~3 | 3 | PASS |

---

## V2 新增统计

### 节点

| 节点类型 | 数量 | 预期范围 | 状态 |
|----------|------|----------|------|
| ErrorType | 16 | 10-20 | PASS |
| Condition | 1715 | 1000-2000 | PASS |
| CallSite | 4930 | 4000-5000 | PASS |

**总节点:** ~7492 (预期 7000+)

### 关系

| 关系类型 | 数量 | 预期范围 | 状态 |
|----------|------|----------|------|
| CONTAINS_CALL | 4930 | 4000-5000 | PASS |
| HANDLES_ERROR | 275 | 200-300 | PASS |
| RAISES | 30 | 20-50 | PASS |
| CHECKS_CONDITION | 1715 | 1000-2000 | PASS |
| CALLS_METHOD | 49 | 30-100 | PASS |
| EMITS_SIGNAL_IN | **0** | 15-40 | **FAIL** |

**总关系:** ~7864 (预期 7000-9000)

---

## 质量抽样

### FeishuClient._get_token

**源文件:** `engine/feishu_client.py:149-180`

| 检查项 | 源代��行号 | 源代�� | Cypher 表现 | 状态 |
|--------|-----------|--------|-------------|------|
| Condition | 151 | `if tok:` | `expr="tok"`, type=if | PASS |
| Condition | 153 | `if self._cached_token and time.time() < self._token_expiry:` | `expr="self._cached_token and time.time() < self._token_expiry"` | PASS |
| Condition | 158 | `if not app_id or not app_secret:` | `expr="not app_id or not app_secret"` | PASS |
| Condition | 166 | `if data.get("code", 0) != 0:` | `expr="data.get('code', 0) != 0"` | PASS |
| Condition | 170 | `if not token:` | `expr="not token"` | PASS |
| CallSite | 150 | `self.cfg.get("auth", {}).get("tenant_access_token")` | `call_expr="self.cfg.get('auth', {}).get"` | PASS |
| CallSite | 163 | `self.session.post(...)` | `call_expr="self.session.post"` | PASS |
| CallSite | 164 | `resp.raise_for_status()` | `call_expr="resp.raise_for_status"` | PASS |
| CallSite | 165 | `resp.json()` | `call_expr="resp.json"` | PASS |
| HANDLES_ERROR | 177 | `except Exception as e:` | → ErrorType(Exception) | PASS |
| RAISES | 159 | `raise ValueError("缺少...")` | → ErrorType(ValueError) | PASS |
| RAISES | 167 | `raise ValueError(f"获取 token...")` | → ErrorType(ValueError) | PASS |
| RAISES | 171 | `raise ValueError("响应中...")` | → ErrorType(ValueError) | PASS |
| RAISES | 180 | `raise RuntimeError(f"获取飞书...")` | → ErrorType(RuntimeError) | PASS |

**CONTAINS_CALL:** 15 个 (全方法调用覆盖)
**CHECKS_CONDITION:** 5 个 (全分支覆盖)
**HANDLES_ERROR:** 1 个 (Exception)
**RAISES:** 4 个 (3x ValueError + 1x RuntimeError)
**评估: PASS** — 精准匹配源代码，无遗漏。

### DownloadWorker.run

**源文件:** `app/gui_app.py:135-147`

| 检查项 | 行号 | 源代码 | Cypher 表现 | 状态 |
|--------|------|--------|-------------|------|
| CONTAINS_CALL | 136 | `self.status_changed.emit("running")` | CallSite, call_expr=`self.status_changed.emit` | PASS |
| CONTAINS_CALL | 139 | `InnoShareEngine(...)` | CallSite, call_expr=`InnoShareEngine` | PASS |
| CONTAINS_CALL | 140 | `self.engine.run()` | CallSite, call_expr=`self.engine.run` | PASS |
| CONTAINS_CALL | 142 | `self.console.print(...)` | CallSite, call_expr=`self.console.print` | PASS |
| CONTAINS_CALL | 145 | `self.queue.put(None)` | CallSite, call_expr=`self.queue.put` | PASS |
| CONTAINS_CALL | 146 | `self.status_changed.emit("finished")` | CallSite, call_expr=`self.status_changed.emit` | PASS |
| CONTAINS_CALL | 147 | `self.finished_signal.emit()` | CallSite, call_expr=`self.finished_signal.emit` | PASS |
| HANDLES_ERROR | 141 | `except Exception as e:` | → ErrorType(Exception) | PASS |
| CALLS_METHOD | 140 | `self.engine.run()` | → `InnoShareEngine.run` | PASS |
| EMITS_SIGNAL_IN | 136,146,147 | 3x `.emit()` calls | **缺失** | FAIL |

**评估: PASS (除 EMITS_SIGNAL_IN 外)** — CONTAINS_CALL 和 CALLS_METHOD 完全正确，Worker→Engine 委派关系准确捕获。

---

## 条件质量 (CHECKS_CONDITION)

### 抽样 10 条条件表达式

| 条件 | 所属方法 | 评估 |
|------|----------|------|
| `tok` | FeishuClient._get_token:151 | 真实分支逻辑 (if tok:) |
| `self._cached_token and time.time() < self._token_expiry` | FeishuClient._get_token:153 | 真实分支逻辑 |
| `not app_id or not app_secret` | FeishuClient._get_token:158 | 真实分支逻辑 |
| `data.get('code', 0) != 0` | FeishuClient._get_token:166 | 真实分支逻辑 |
| `not token` | FeishuClient._get_token:170 | 真实分支逻辑 |
| `signal_name is None` | cypher_generator._emit_v2_signal_emit_rels:425 | 真实分支逻辑 (工具自身代码) |
| `signal_name not in signal_names` | cypher_generator._emit_v2_signal_emit_rels:427 | 真实分支逻辑 |
| `resp.ok or resp.json().get("code") != 0` | FeishuClient.upload_file_chunked:217 | 真实分支逻辑 |

**评估: Good** — 所有条件均捕获真实分支逻辑，未发现无意义的条件表达式（如字面量 `if True:`）。

---

## 调用解析质量 (CALLS_METHOD)

### 抽样 10 条 CALLS_METHOD

| 调用者 | 目标 | 验证 | 状态 |
|--------|------|------|------|
| DownloadWorker.run | InnoShareEngine.run | gui_app.py:140 `self.engine.run()` | PASS |
| DownloadWorker.pause | InnoShareEngine.pause | gui_app.py:157 `self.engine.pause()` | PASS |
| DownloadWorker.resume | InnoShareEngine.resume | gui_app.py:162 `self.engine.resume()` | PASS |
| DownloadWorker.stop | InnoShareEngine.stop | gui_app.py:167 `self.engine.stop()` | PASS |
| TransTrackWorker.run | TransTrackEngine.login | Worker 委派 | PASS |
| TransTrackWorker.run | TransTrackEngine.select_project | Worker 委派 | PASS |
| TransTrackWorker.run | TransTrackEngine.open_risc_list | Worker 委派 | PASS |
| TransTrackWorker.run | TransTrackEngine.close | Worker 委派 | PASS |
| MainWindow._get_sync_accounts | AccountManager.get_active_accounts | 业务调用 | PASS |
| MainWindow._pause_download | DownloadWorker.pause | UI→Worker委派 | PASS |

**评估: Good** — Worker→Engine 委派模式、MainWindow→Worker 控制模式、跨模块方法调用均正确解析。解析目标利用了 `attr_map` 中的赋值信息（如 `self.engine = InnoShareEngine(...)`）。

---

## EMITS_SIGNAL_IN

### 状态: Not found (0 条关系)

### 根因分析

**问题:** `cypher_generator.py:422-433` 中的 `_emit_v2_signal_emit_rels` 函数有匹配逻辑缺陷。

AST 解析器 (`ast_parser.py:669-674`) 从 `self.X.emit(...)` 提取的信号名为**短名**:
```python
signal_emits.append({
    "owner_fqn": "app.gui_app.DownloadWorker.run",
    "signal_name": "progress",  # ← 短名
    ...
})
```

但 cypher_generator 构建的信号索引 (`cypher_generator.py:450-452`) 是**全限定名**:
```python
signal_names.add(f"{s['class']}.{s['name']}")  
# → "app.gui_app.DownloadWorker.progress"  ← 全限定名
```

匹配逻辑 (`cypher_generator.py:427`):
```python
if signal_name not in signal_names:
    continue  # "progress" not in {"app.gui_app.DownloadWorker.progress", ...} → 全部跳过
```

**结果:** 38 个 `self.X.emit(...)` 调用被正确检测到 (在 CallSite 中以 `call_expr="self.progress.emit"` 等形式存在)，但 EMITS_SIGNAL_IN 关系全部为 0。

### 修复方案

在 `_emit_v2_signal_emit_rels` 中，需要同时使用 `owner_fqn` 推断所属类，构建全限定信号名进行匹配:

```python
# 从 owner_fqn 提取 class FQN (去掉方法名)
# "app.gui_app.DownloadWorker.run" → "app.gui_app.DownloadWorker"
parts = emit["owner_fqn"].rsplit(".", 1)
class_fqn = parts[0] if len(parts) > 1 else ""
full_signal_name = f"{class_fqn}.{emit['signal_name']}"
if full_signal_name in signal_names:
    _emit_rel(...)
```

### 影响范围

- DownloadWorker: `progress`, `task_added`, `status_changed`, `finished_signal` 的 emit
- PushWorker: `progress`, `status_changed`, `finished_signal` 的 emit
- RpaWorker: `progress`, `finished_signal`, `status_changed` 的 emit
- LinkSyncWorker: `progress`, `finished_signal`, `status_changed` 的 emit
- TransTrackWorker: `status_signal`, `finished_signal`, `manual_req_signal` 的 emit
- RichConsole: `log_signal` 的 emit

预计修复后产生 **16-38 条** EMITS_SIGNAL_IN 关系。

---

## 结论

**整体评估: FAIL** — 1 个阻断性 Bug (EMITS_SIGNAL_IN=0)。

### 优点
1. V1 所有节点和关系完整保留，无一遗漏或退化
2. V2 新增节点/关系数量在预期范围内 (CallSite 4930, Condition 1715, ErrorType 16)
3. CONTAINS_CALL 精准捕获方法内所有函数调用
4. CHECKS_CONDITION 捕获真实分支表达式，无垃圾数据
5. CALLS_METHOD 正确解析 Worker→Engine、UI→Worker 委派链
6. HANDLES_ERROR/RAISES 准确捕获异常处理语义

### 缺陷
1. **EMITS_SIGNAL_IN = 0** — 信号名格式不匹配（短名 vs 全限定名），需修复 cypher_generator.py `_emit_v2_signal_emit_rels` 函数中的匹配逻辑
2. TESTS 关系仅 1 条 — TEST_MODULE_MAP 仅覆盖 6 个测试文件，测试类匹配率极低
3. Function 节点 110 个 (vs 预期 81) — 差异来自 tools/*.py 新增工具脚本，非回归问题

### 修复优先级
1. **P0:** 修复 EMITS_SIGNAL_IN 匹配逻辑 (cypher_generator.py:422-433)
2. **P2:** 扩展 TEST_MODULE_MAP 覆盖更多测试文件
