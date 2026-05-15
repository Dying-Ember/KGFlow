# KG 辅助开发工作流 V4——可落地（最终版）

## Context

V3 补上了版本绑定、三层 Gate、工件标准化、门禁 intent，骨架正确。V4 针对工程落地细节再收紧：元信息粒度、Gate 2 Cypher 语义、门禁分级、置信度决策规则、查询安全模型。

---

## 0. 版本绑定：run 级粒化

**问题**: 同一 commit 多次生成图谱时，`MERGE {commit_sha}` 会覆盖元信息，审计不可回溯。

### kg_run_id

```python
import uuid, hashlib

kg_run_id = hashlib.sha256(
    f"{commit_sha}:{generated_at.isoformat()}:{generator_version}".encode()
).hexdigest()[:12]
```

### KGMetadata 节点

```cypher
CREATE CONSTRAINT kg_meta_unique IF NOT EXISTS FOR (m:KGMetadata) REQUIRE m.kg_run_id IS UNIQUE;

MERGE (m:KGMetadata {kg_run_id: "a1b2c3d4e5f6"})
SET m.repo = "Dying-Ember/Automation-Inspection",
    m.commit_sha = "abc123",
    m.branch = "master",
    m.generated_at = datetime("2026-05-15T12:00:00Z"),
    m.generator_version = "2.0.0",
    m.node_count = 7492,
    m.edge_count = 7864
```

### 报告可溯源链

```
impact_report.meta.kg_run_id  →  KGMetadata {kg_run_id}
audit_report.meta.kg_run_id   →  KGMetadata {kg_run_id}
kg_diff.meta.from_run_id      →  KGMetadata {kg_run_id}
kg_diff.meta.to_run_id        →  KGMetadata {kg_run_id}
```

---

## 1. Gate 1（Git 层）：三级输出

**问题**: True/False 太粗糙。conftest 纯增量常翻车、同模块一刀切过度。

### 输出

```
Gate 1 输出: BLOCK / WARN / PASS

BLOCK（强冲突，不可并行）:
  - 同一 .py 文件
  - 同一测试文件（test_*.py）
  - 同一公共基类文件（例如项目里的 conftest.py、test_helpers.py）
  - 同一 fixture 文件

WARN（需 Lead 豁免）:
  - conftest.py（如果改动不含 fixture scope/autouse/monkeypatch 声明）
  - 共享测试工具文件
  - 共享快照/测试数据目录

PASS: 其余
```

### 输入来源: 不靠人手列 files

Sub-Dev 产出 `subdev_X_plan.json`，声明 `expected_touched_files`。Lead 合并后用 `git diff --name-only` 校验事实来源。

---

## 2. Gate 2（KG 层）：方向性 + 共享枢纽 + 置信度过滤

**问题**: `-[...*1..5]-` 无向混淆方向 + 变量长度边的解释性差 + 未按置信度筛选。

### 2.1 CALLS_METHOD: 有向查询 + 方向标注

```cypher
// A 依赖 B？（A 调了 B 的方法）
MATCH path = (a:Method)-[:CALLS_METHOD {confidence: "high"}*1..5]->(b:Method)
WHERE a.name = $task_a_start AND b.name = $task_b_start
RETURN [node IN nodes(path) | node.name] AS chain,
       "A_CALLS_B" AS direction
// → BLOCK: A 改了方法签名会崩掉 B 的调用

// B 依赖 A？
MATCH path = (b:Method)-[:CALLS_METHOD {confidence: "high"}*1..5]->(a:Method)
WHERE a.name = $task_a_start AND b.name = $task_b_start
RETURN [node IN nodes(path) | node.name] AS chain,
       "B_CALLS_A" AS direction
// → WARN: B 改的方法可能影响 A 的下游行为（但 A 本身不被直接修改）

// 双向都有 → BLOCK
```

### 2.2 READS_CONFIG_KEY / COMPOSES: 共享枢纽

```cypher
// 两个任务改了共享同一个 config key 的模块？
MATCH (m1:Method)-[:READS_CONFIG_KEY]->(ck:ConfigKey)<-[:READS_CONFIG_KEY]-(m2:Method)
WHERE m1.name IN $task_a_methods AND m2.name IN $task_b_methods
RETURN DISTINCT ck.name AS shared_key

// 两个任务改了共享同一个被注入类的模块？
MATCH (m1:Method)-[:COMPOSES]->(c:Class)<-[:COMPOSES]-(m2:Method)
WHERE m1.name IN $task_a_methods AND m2.name IN $task_b_methods
RETURN DISTINCT c.name AS shared_class
```

### 2.3 Gate 2 判定规则

```
Gate 2 BLOCK:
  A-[:CALLS_METHOD{high}*]->B 存在路径 → BLOCK
  B-[:CALLS_METHOD{high}*]->A 存在路径 → 如 A 也要改方法签名，升级为 BLOCK

Gate 2 WARN:
  B-[:CALLS_METHOD{high}*]->A 且 A 只改方法体内部逻辑 → WARN
  A 和 B 共享 READS_CONFIG_KEY → WARN（不含 COMPOSES，后者独立判断）
  A 和 B 共享 COMPOSES（被注入类）→ WARN
  任何 confidence=medium 的边参与路径 → 降级为 WARN

Gate 2 PASS:
  所有关键边类型无交集
```

### 2.4 扩张原因输出

```
每条 Gate 2 命中必须输出:
  - 命中路径的节点序列: [A, X, Y, Z, B]
  - 连接边类型序列: [CALLS_METHOD, CALLS_METHOD, COMPOSES]
  - 关键跳: "X→Y 的 CALLS_METHOD 把 B 拉进了 A 的影响范围"
```

---

## 3. IMPORTS: 并发不管，架构必查

```
Gate 2: IMPORTS 不参与并发冲突判定
Auditor 架构规则: IMPORTS 参与检查
  - engine→app: BLOCK
  - app→engine: PASS（正常依赖方向）
  - tools→engine: PASS
  - tests→engine: PASS
  - tests→app: PASS
```

---

## 4. 置信度：硬决策规则

**问题**: 同一图谱不同 Agent 解读不同 → 一致性崩溃。

### 硬规则

```
规则 1: 并发冲突判定（Gate 2）
  只用 confidence=high 的 CALLS_METHOD 作为 BLOCK 材料
  confidence=medium 的边 → 只出 WARN，永不出 BLOCK

规则 2: 影响范围报告
  high 置信度影响 → "确定受影响"
  medium 置信度影响 → "可能受影响"
  两个列表分开，禁止混排

规则 3: 风险评分
  risk_high_only = f(high 置信度边数量, 影响深度)
  risk_expanded = f(high + medium 边数量, 影响深度)
  两个分数分别上报，不合并

规则 4: 盲区修正
  risk_expanded *= (1 + blind_spot_penalty * 0.3)
  blind_spot_penalty = 1（默认）因为项目用了装饰器/依赖注入等
```

---

## 5. 查询安全模型: 零裸 Cypher

**问题**: CALL db.* 过程很多是破坏性的。关键词白名单不够。

### 模型

```
完全禁止接受任意 Cypher 字符串输入

query_kg.py 架构:
  子命令 (impact / check-parallel / call-chain / ...)
    → 内部固定模板（参数化 Cypher）
    → Neo4j 只读账号 + driver 层 deny CREATE/MERGE/DELETE/SET/DROP

参数化示例:
  query_kg.py check-parallel \
    --task-a-methods '["FeishuClient.upload_file"]' \
    --task-b-methods '["normalize_field_value"]'
  # 内部用 $params 注入，不拼字符串

不暴露任何 CALL db.* 过程给子命令
```

---

## 6. change_intent: 分级门禁 + 预算

**问题**: allowed/forbidden 二元太刚性，意图写起来比代码还累。

### Schema

```json
{
  "meta": { "kg_run_id": "...", "plan_tasks_ref": "artifacts/plan_tasks.json" },
  "tasks": [
    {
      "task_id": "T1",
      "files": ["engine/feishu_client.py"],
      "hard_rules": {
        "forbidden_new_edges": ["IMPORTS"],
        "forbidden_removed_edges": ["CALLS_METHOD"],
        "max_orphan_nodes": 0
      },
      "soft_rules": {
        "allowed_new_edges": ["CONTAINS_CALL", "CHECKS_CONDITION"],
        "edge_budget_by_type": { "CHECKS_CONDITION": 20, "CONTAINS_CALL": 100 },
        "unknown_edge_policy": "warn"
      }
    }
  ],
  "arch_rules": [
    { "rule": "NO_engine_to_app_IMPORTS", "action": "block" },
    { "rule": "NO_call_sites_removed", "action": "block" }
  ]
}
```

### 门禁判定

```
Hard block（违反立即 block merge）:
  - 架构规则（engine→app IMPORTS 等）
  - forbidden_new_edges 中实际出现了
  - forbidden_removed_edges 中实际被删了
  - 孤立节点超过 max_orphan_nodes
  - 违规跨层依赖

Soft warn（允许但需 Lead 手动 resolve）:
  - 新增边不在 allowed 但也不在 forbidden → 触发 unknown_edge_policy
  - 某类边数量超过 edge_budget_by_type
  - 新增节点总数 > max_new_nodes

也就是：不完全精确预测 → 不 block；只 block 明确危险的
```

---

## 7. 工件: 版本化 + 强制校验

### Schema 版本化

```json
// 每个工件顶层:
{
  "schema_version": "1.0.0",
  "meta": { ... },
  "data": { ... }
}
```

### 强制校验

```bash
# CI 中或本地:
uv run python tools/validate_artifacts.py artifacts/
# 遍历 artifacts/*.json → 用 jsonschema 校验 → 不通过直接 exit 1
```

---

## 8. 角色编排终版

```
Lead (我)
│
├─ Phase 1 (并行)
│   Impact Analyst:  KG 查询 → artifacts/impact_report.json
│   Lead Developer:  拆分   → artifacts/plan_tasks.json
│
├─ Phase 2 (Lead 审核)
│   核对两份报告交叉一致性
│   Gate 1 (git diff) → Gate 2 (KG 定向查询) → Gate 3 (checklist)
│   输出 artifacts/change_intent.json
│
├─ Phase 3 (Sub-Dev × N, 并行)
│   每个产出: artifacts/subdev_X_plan.json + artifacts/subdev_X_patch.diff
│   Lead Developer 合并 diff
│
├─ Phase 4 (并行)
│   Auditor:  对照 change_intent → artifacts/audit_report.json (pass/block)
│   KG Ops:   重新生成 → artifacts/kg_diff.json (run_id 链)
│
└─ 门禁
    Hard block → 拒绝 merge
    Soft warn → Lead 手动 resolve
    Pass → merge + 归档所有 artifacts
```

---

## 8.5 收口补丁（6 项，不动主结构）

### 补丁 1: kg_run_id 加入抽取器配置指纹

```python
extractor_config_hash = hashlib.sha256(
    json.dumps({
        "parser_version": "2.0",
        "enabled_edge_types": ["CALLS_METHOD", "CONTAINS_CALL", ...],
        "excluded_dirs": ["__pycache__", ".venv", "dist", "build"],
        "confidence_rules_version": "1.0"
    }, sort_keys=True).encode()
).hexdigest()[:8]

kg_run_id = sha256(f"{commit_sha}:{time}:{gen_version}:{extractor_hash}")[:12]
```

目的: 抽取器升级时，不会把图谱变化误判为代码变化。

### 补丁 2: Gate 1 强制对账（预期文件 vs 实际文件）

```
Lead 合并后必须执行:
  actual = git diff --name-only
  expected = union(各 Sub-Dev 的 expected_touched_files)

  若 actual - expected 非空:
    若超出的文件属于公共文件/测试基建（conftest.py, test_helpers.py, 共享 fixtures 等）:
      → BLOCK（或 WARN + 必须解释，取决于项目纪律）
    其余:
      → WARN（Sub-Dev 超范围改动，需 Lead 确认不是遗漏声明）
```

### 补丁 3: Gate 2 方向规则精确化

简化: 不区分 A→B 还是 B→A 来决定 block/warn。直接用"改动集合间耦合"判定。

```
若存在路径:
  (any:Method in A_changed_methods) -[:CALLS_METHOD{high}*1..5]-> (any:Method in B_changed_methods)
  → BLOCK（改动集合间存在高置信调用耦合）

反向同理也 BLOCK（对称处理）。

区分方向只在"扩张原因输出"里体现，用于帮助 Lead 理解为什么冲突。
删除 WARN 的"B_CALLS_A"保留，改为统一 BLOCK，减少判断分支。
（如需给 Lead 豁免空间，走 Gate 3 checklist 人工 override）
```

### 补丁 4: READS_CONFIG_KEY 按"读/写语义"降噪

KG 目前只有 READS_CONFIG_KEY，共享读不一定是冲突。

```
Gate 2 中:
  READS_CONFIG_KEY 共享 → WARN（默认）
  
Gate 3 checklist:
  Lead 必须确认: "本次变更是否改变该 key 的语义/默认值/校验规则？"
  只有勾选"是" → 升级为高风险处理
  勾选"否" → 维持 WARN，不升级

长期: 图谱里区分 READS_CONFIG_KEY vs WRITES_CONFIG_KEY vs VALIDATES_CONFIG_KEY
```

### 补丁 5: diff_kg 强制校验抽取器版本一致性

```
diff_kg 启动时立即输出:
  from.generator_version == to.generator_version?
  from.extractor_config_hash == to.extractor_config_hash?
  
不一致时:
  默认 SOFT WARN（报告差异但无代码变更时不 block）
  如果项目选择严格模式: BLOCK（不允许抽取器升级混入 PR）
```

### 补丁 6: validate_artifacts 三层校验

```
L1: JSON Schema 结构校验（jsonschema 库）
L2: 必填字段 + 枚举约束校验（gate 结果只能是 BLOCK/WARN/PASS;
    unknown_edge_policy 只能是 warn/block）
L3: 交叉引用存在性校验:
    change_intent.meta.plan_tasks_ref 文件存在
    audit_report.meta.kg_run_id 格式正确（至少 12 位 hex）
    如果 CI 能连 Neo4j: 在 KGMetadata 中验证 kg_run_id 存在
```

---

## 8.6 落地必需补丁（4 项）

### 补丁 7: Diff → KG Method 节点映射（resolve-changes 子命令）

Gate 2 的 `A_changed_methods` / `B_changed_methods` 不是凭空来的。

**强制约定**:
- KG 中 Method 节点必须带 `file_path`（repo 相对路径，POSIX `/`，不存绝对路径）
- `query_kg.py` 提供 `resolve-changes` 子命令

**输入标准化**（处理 rename/delete/split）:
```
git diff --name-status -M50% --diff-filter=ACMRD base..head
（必须包含 R/D filter，否则漏掉重命名/删除）

R（rename）: 用新路径匹配 KG file_path；旧路径记入报告用于解释
D（delete）: changed_methods 为空也不能 PASS；文件标为 Gate 1 WARN/BLOCK 候选
```

**行号容忍区间**（格式化/注释平移导致 diff 偏移）:
```
有 line_range: 方法区间与 diff 区间相交 → 命中；允许 ±2 行容忍
无 line_range: 文件内所有方法都标为候选，resolution_confidence: "low"
```

**file_path 规范化**:
```
一律存储为 repo 相对路径，POSIX 分隔符（/）
engine/feishu_client.py ✓    D:\...\engine\feishu_client.py ✗
大小写敏感按 git 行为
```

### 补丁 8: 标准化的"人工豁免"工件

Gate 2 统一 BLOCK 后，Lead 必然遇到"我确信能并行但被 block"的场景。

```json
{
  "schema_version": "1.0",
  "overrides": [
    {
      "override_id": "OV-001",
      "scope": {"gate": "Gate2", "hit_path": "[A, X, Y, B]"},
      "reason": "A 只改内部缓存，不改签名/异常契约",
      "approver": "lead-name",
      "created_at": "2026-05-15T12:00:00Z",
      "approval_hash": "sha256(approver+reason+created_at)[:8]",
      "expires_at": "2026-05-16T12:00:00Z"
    }
  ]
}
```

Auditor/KG Ops 必须在报告里回写引用。默认 30 天过期；永久须显式 `expires_at: null`（防止技术债累积）。

### 补丁 9: diff_kg 变更归因字段

```
kg_diff.meta.change_attribution ∈ {"code_only", "extractor_only", "mixed", "unknown"}

当 ∈ {"extractor_only", "mixed"}:
  → 提示: "kg_diff 不可用于验证 edge_budget，降级为软校验"
  → 门禁只执行 hard_rules，跳过 soft_rules 的 budget
```

### 补丁 10: CI Neo4j 连接降级策略

```
CI 不能连 Neo4j → L3 degraded 模式:
  只做格式校验 + run_id 引用一致性，不查存在性

CI 能连 Neo4j → L3 full 模式:
  额外校验 run_id 存在 + metadata 一致性 + 数量容差(±1%)

validate_artifacts 输出标注: neo4j_connected: true/false, l3_mode: "full"/"degraded"
```

---

## 8.7 实现前必读细节（6 项）

### 细节 1: edge_budget 统计口径

软校验的 `edge_budget_by_type` 按**全图**还是**子图**统计？口径不一致会导致 Auditor/KG Ops 实现分歧。

**强制约定: 按 scope 子图统计**（短期如无法做归因，则只对可归因边类型启用 budget）:
```
子图 = 变更文件命中的 Method/Function 节点 + 这些节点最远 2 跳内的邻接边

diff_kg 把每个增量边归因到 file_path 或 method_fqn（如无归因能力，标 attribution: "unscoped"）

短期过渡方案:
  只对 CALLS_METHOD / IMPORTS 启用 edge_budget（它们可明确归因）
  CONTAINS_CALL / CHECKS_CONDITION / HANDLES_ERROR 等高频边先不做 budget
```

### 细节 2: change_attribution ≠ code_only 时的 soft_rules 存活规则

```
attribution ∈ {"extractor_only", "mixed"}:
  hard_rules: 全部执行
  soft_rules: unknown_edge_policy（warn/block）保留执行
              edge_budget_by_type: 全部跳过
  audit_report 强制输出: "本次 diff 受抽取器变化影响 (attribution={value})，soft 校验降级"

attribution = "code_only":
  所有规则正常执行
```

### 细节 3: 最小可跑闭环（推荐实施顺序）

不走全量，先把核心链路跑通：

```
Step A: generate_knowledge_graph.py → KGMetadata(kg_run_id) → 导入 Neo4j
Step B: query_kg.py resolve-changes → 验证 diff → changed_methods 映射
Step C: query_kg.py check-parallel → 验证 Gate 2 判定
Step D: validate_artifacts.py L1+L2 → 验证工件格式
```

跑通后再补 `diff_kg`、`auditor`（Gate 3）、`edge_budget`。

---

## 9. 实施步骤

| 步骤 | 内容 | 优先级 |
|------|------|--------|
| 1 | 扩展 ast_parser.py: Method 加 file_path (POSIX 相对路径)；边加 confidence | P0 |
| 2 | 扩展 generate_knowledge_graph.py: KGMetadata (kg_run_id + extractor_config_hash) | P0 |
| 3 | 写 query_kg.py: resolve-changes / check-parallel / impact / call-chain | P0 |
| 4 | 写 validate_artifacts.py: L1 结构 + L2 枚举 | P0 |
| 5 | 端到端验证: Step A→B→C→D 闭环 | P0 |
| 6 | 写 diff_kg.py: run_id diff + extractor 一致性 + change_attribution + 归因 | P1 |
| 7 | 写 query_kg.py 其余子命令: config-readers / orphans / cross-layer | P1 |
| 8 | 写 validate_artifacts.py L3（含 Neo4j 降级） | P1 |
| 9 | 创建 artifacts/ + JSON Schema 文件（含 overrides.json） | P1 |
| 10 | 创建 .claude/agents/*.md (5 个角色 prompt 模板) | P2 |
| 11 | 全量端到端: Gate 1+2+3 + change_intent + budget + override | P2 |

## 10. 验证方式

真实场景: "给 upload_file 加文件大小限制 + 给 normalize_field_value 加 null 安全"

验收清单:
- [ ] resolve-changes 正确把 git diff 映射到 changed_methods
- [ ] KGMetadata 有正确 kg_run_id + extractor_config_hash
- [ ] Gate 1: 预期 vs git diff 对账；超出范围 → WARN/BLOCK 分类正确
- [ ] Gate 2: A/B 改动集合间定向查询无 CALLS_METHOD{high} → PASS
- [ ] Gate 2: READS_CONFIG_KEY 共享 → WARN，Gate 3 确认语义不变 → 不升级
- [ ] Gate 3: 人工 checklist 全部确认
- [ ] change_intent 正确分级（hard/soft/edge_budget/unknown_policy）
- [ ] overrides.json（如有）被 Auditor 正确引用
- [ ] diff_kg: change_attribution = "code_only"
- [ ] validate_artifacts: degraded 模式下 L1/L2/L3 全部通过
- [ ] 门禁: hard_rules 无违规 → merge
