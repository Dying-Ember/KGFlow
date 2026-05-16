# KGFlow — Knowledge Graph Assisted Development Workflow

将项目代码转换 Neo4j 知识图谱，并通过多 Agent 协作实现 Code Review、影响分析、并行开发安全判定和架构门禁的 CLI 工具链。

## 核心能力

```
git diff  →  changed_methods  →  Gate 并行判定  →  审计门禁 → 结论
                                      │
项目源码 ─→ AST 解析 ─→ Neo4j 图谱     │
                ↑                      │
            代码变更 ──────────────────┘
```

| 能力 | 工具 | 说明 |
|------|------|------|
| 图谱生成 | `generate_knowledge_graph.py` | 用 Python `ast` 模块解析源码，生成 Cypher 导入脚本 |
| 增量对比 | `diff_kg.py` | 比较两次生成结果，输出节点/边增量 + 变更归因 |
| 影响分析 | `query_kg.py impact` | 输入方法，输出调用链、配置引用、测试覆盖 |
| 并发判定 | `query_kg.py check-parallel` | 两层 Gate 判断两个子任务能否并行开发 |
| 调用链 | `query_kg.py call-chain` | 上溯调用者/下追被调用者 |
| 架构检查 | `query_kg.py cross-layer` | 检测层间依赖违规（如 engine → app）|
| 变更映射 | `query_kg.py resolve-changes` | git diff → KG Method 节点映射 |
| 工件校验 | `validate_artifacts.py` | L1 结构 + L2 枚举 + L3 Neo4j 交叉引用 |

## 快速开始

### 依赖

- Python >= 3.10
- Neo4j Desktop（已运行，bolt://localhost:7687）
- 被分析项目（默认: `D:\PythonProgramming\1\Automation-Inspection`）

### 安装

```bash
cd D:\PythonProgramming\1\Automation-Insight-KGFlow
uv sync
```

### 使用

**1. 一键生成 + 导入**

```bash
# 生成图谱 → 自动存档上一次结果 → 写入 output/knowledge_graph.cypher
uv run python tools/generate_knowledge_graph.py

# 导入 Neo4j
uv run python tools/import_neo4j.py
```

**2. 查询**

```bash
# 影响分析
uv run python tools/query_kg.py impact --methods '["FeishuClient._get_token"]' --depth 3

# 调用链
uv run python tools/query_kg.py call-chain \
  --method "engine.feishu_client.FeishuClient._get_token" \
  --direction down --depth 3

# 并发安全判定
uv run python tools/query_kg.py check-parallel \
  --task-a-methods '["InnoShareEngine.run"]' \
  --task-b-methods '["normalize_field_value"]'

# 架构违规检查
uv run python tools/query_kg.py cross-layer --from-layer engine --to-layer app

# 配置引用查询
uv run python tools/query_kg.py config-readers --config-key feishu

# git diff → 方法映射
uv run python tools/query_kg.py resolve-changes \
  --project-root "D:/PythonProgramming/1/Automation-Inspection"
```

**3. 代码变更后更新**

```bash
uv run python tools/generate_knowledge_graph.py   # 自动存档旧版本
uv run python tools/diff_kg.py --from-latest 2 --to-latest 1
uv run python tools/import_neo4j.py
uv run python tools/validate_artifacts.py artifacts/
```

## 项目结构

```
Automation-Insight-KGFlow/
├── tools/
│   ├── ast_parser.py                ← AST 解析引擎
│   ├── cypher_generator.py          ← Cypher 格式化 + KGMetadata 元信息
│   ├── generate_knowledge_graph.py  ← 主入口：解析 + 生成 + 存档
│   ├── query_kg.py                  ← 7 个子命令的 Neo4j 查询工具
│   ├── diff_kg.py                   ← Run-to-run 增量对比 + 变更归因
│   ├── validate_artifacts.py        ← L1+L2+L3 工件校验
│   └── import_neo4j.py              ← Cypher 文件导入 Neo4j
├── .claude/agents/
│   ├── impact-analyst.md            ← 影响分析 Agent prompt
│   ├── lead-dev.md                  ← 开发编排 Agent prompt
│   ├── sub-dev.md                   ← 子任务实现 Agent prompt
│   ├── auditor.md                   ← 审计 Agent prompt
│   └── kg-ops.md                    ← 图谱维护 Agent prompt
├── artifacts/schemas/               ← 6 种工件 JSON Schema
├── output/                          ← 生成的 .cypher 文件 + 存档
├── pyproject.toml
└── README.md
```

## 图模型

| 节点类型 | 数量 | 说明 |
|----------|------|------|
| `Module` | 33 | Python 模块 |
| `Class` | 78 | 类定义 |
| `Method` | 500 | 方法（含 file_path / line / end_line）|
| `Function` | 111 | 独立函数 |
| `CallSite` | ~4,900 | 方法体内的函数调用点 |
| `Condition` | ~1,700 | if/while 分支条件 |
| `ErrorType` | 16 | 捕获/抛出的异常类型 |
| `Signal` | 17 | Qt 信号 |
| `ConfigFile` | 4 | TOML/JSON 配置文件 |
| `WorkerThread` | 5 | QThread 工作线程 |
| `ExternalSystem` | 3 | 飞书 / TransTrack / InnoShare |
| `KGMetadata` | 每 run | 版本元信息 |

| 关系类型 | 数量 | 说明 |
|----------|------|------|
| `CALLS_METHOD` | ~50 | 方法间调用链（含 confidence 置信度）|
| `CONTAINS_CALL` | ~3,900 | 方法包含的调用点 |
| `HANDLES_ERROR` | ~100 | 异常处理关联 |
| `CHECKS_CONDITION` | ~1,200 | 分支条件关联 |
| `OWNS_METHOD` | ~500 | 类拥有方法 |
| `DEFINES_CLASS` | ~30 | 模块定义类 |
| `READS_CONFIG` | ~18 | 模块读取配置文件 |
| `IMPORTS` | ~31 | 模块间导入 |
| `INHERITS` | ~6 | 类继承 |
| `COMPOSES` | ~11 | 类组合 |
| `DEPENDS_ON` | ~8 | 外部系统依赖 |
| `EMITS_SIGNAL_IN` | ~27 | 方法发射信号 |

## 多 Agent 工作流

```
Phase 1 (Tech Lead 编排)
  Tech Lead → spawn Impact Analyst → artifacts/impact_report.json
           → 拆任务 → artifacts/plan_tasks.json
           → checkpoint 退出，等待人类确认

Phase 2 (Tech Lead 重生)
  读 checkpoint → Gate 1/2/3 判定 → artifacts/change_intent.json
  → checkpoint 退出

Phase 3 (Tech Lead 重生)
  读 checkpoint → spawn Sub-Dev × N → 合并 diff
  → checkpoint 退出

Phase 4 (Tech Lead 重生)
  读 checkpoint → spawn Auditor + KG Ops → 检查结果
  → checkpoint 退出 → Lead 汇报给人类
```

## 设计文档

完整设计方案: [kg-workflow-design.md](./kg-workflow-design.md)

## 版本

- Generator: 2.0.0
- Schema: 1.0.0

## 开发状态

```
Phase                    Status    Items
─────────────────────────────────────────────────────
P0: 核心工具链           ✅ 100%   7 tools + parser + gen
P0: Extractor 框架       ✅ 100%   base.py + registry + python_extractor (regression 0 diff)
P1: tree-sitter 查询     ✅ 100%   12 .scm files (python/javascript/go, 249 lines)
P1: 多语言验证           ✅ 100%   JavaScriptExtractor (JS/TS/JSX, 1056 lines)
P2: kgflow.toml 配置      ✅ 100%   项目级配置 + 多 root 支持
P2: Coverage 指标         ✅ 100%   CI 阈值 + 解析质量统计
P3: 多角色 Agent 编排     ✅ 100%   6 agent prompt + 6 artifact schema + Gate 1/2/3 + checkpoint 循环
```

## 设计文档

完整设计方案: [kg-workflow-design.md](./kg-workflow-design.md)
