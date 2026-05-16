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

### 1. 环境准备

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | >= 3.13 | 运行环境 |
| [uv](https://docs.astral.sh/uv/) | 最新 | 包管理 |
| [Neo4j](https://neo4j.com/download/) | 5.x | 图数据库（bolt://localhost:7687）|
| 被分析项目 | — | 你的源码（默认: `D:\PythonProgramming\1\Automation-Inspection`）|

### 2. 安装

```bash
git clone https://github.com/Dying-Ember/KGFlow.git
cd KGFlow
uv sync
```

### 3. 验证 CLI

一键验证：生成图谱 → CI 覆盖度检查 → 退出。

```bash
uv run python tools/generate_knowledge_graph.py --ci
```

如果看到 `CI coverage check: PASS`，说明解析引擎正常工作。

### 4. 配置 MCP Server（Agent 工作流）

在 `.claude/settings.local.json` 中写入：

```json
{
  "mcpServers": {
    "kgflow": {
      "command": "uv",
      "args": ["run", "python", "tools/mcp_server.py"],
      "env": {
        "KGFLOW_NEO4J_PASSWORD": "your-neo4j-password"
      }
    }
  }
}
```

完成后重新启动 Claude Code。 spawned 的任何 sub-agent/teammate 会自动继承 `kgflow_*` 这一组 typed tools。

### 5. 上手体验

#### 方式 A — 人手调 CLI（适合调试）

```bash
# 影响范围分析
uv run python tools/query_kg.py impact \
  --methods '["FeishuClient._get_token"]' --depth 3

# 增量对比（需要至少两个存档）
uv run python tools/diff_kg.py --from-latest 2 --to-latest 1

# 工件校验（输出 JSON）
uv run python tools/validate_artifacts.py --json artifacts/
```

#### 方式 B — Agent 自动编排（核心工作流）

在 Claude Code 中 spawn **Lead**，给一个开发需求。全自动执行：

```
你（人类）: @spawn lead
           需求：给 InnoShareEngine.run 加超时重试

Lead → Tech Lead → Impact Analyst（查影响范围）
                 → 拆任务 → 门禁判定 → 你确认
                 → Sub-Dev × N（并行实现）
                 → Auditor + KG Ops（审计 + 更新图谱）
```

详细角色分工见下方[多 Agent 工作流](#多-agent-工作流)和 `.claude/agents/` 下的 prompt。

### 6. 用 `--json` 拿结构化输出

所有工具支持 `--json` 参数，供脚本和 CI 消费：

```bash
uv run python tools/generate_knowledge_graph.py --json
uv run python tools/validate_artifacts.py --json artifacts/
uv run python tools/import_neo4j.py --dry-run --json   # 仅校验，不修改数据库
```

错误输出到 stderr，格式统一：`{"error": true, "code": "...", "detail": "..."}`。
凭据从环境变量注入（`KGFLOW_NEO4J_*`），不硬编码。

## 项目结构

```
Automation-Insight-KGFlow/
├── tools/
│   ├── generate_knowledge_graph.py  ← 主入口：解析 + 生成 + 存档
│   ├── import_neo4j.py              ← Cypher 文件导入 Neo4j
│   ├── query_kg.py                  ← 7 个子命令的 Neo4j 查询工具
│   ├── diff_kg.py                   ← Run-to-run 增量对比 + 变更归因
│   ├── validate_artifacts.py        ← L1+L2+L3 工件校验
│   ├── mcp_server.py                ← FastMCP Server（10 typed tools）
│   ├── config.py                    ← kgflow.toml 配置加载
│   ├── errors.py                    ← 结构化 JSON 错误码
│   ├── neo4j_config.py              ← Neo4j 凭据（环境变量）
│   ├── ast_parser.py                ← AST 解析引擎（legacy）
│   └── cypher_generator.py          ← Cypher 格式化 + 元信息
├── .claude/agents/
│   ├── lead.md                      ← 人机接口 Agent prompt
│   ├── tech-lead.md                 ← 技术编排 Agent prompt（checkpoint 循环）
│   ├── impact-analyst.md            ← 影响分析 Agent prompt
│   ├── sub-dev.md                   ← 子任务实现 Agent prompt
│   ├── auditor.md                   ← 审计 Agent prompt
│   └── kg-ops.md                    ← 图谱维护 Agent prompt
├── artifacts/schemas/               ← 6 种工件 JSON Schema
├── output/                          ← 生成的 .cypher 文件 + 存档
├── pyproject.toml
└── README.md
```

## 图模型（Schema 定义）

**节点类型：** Module, Class, Method, Function, CallSite, Condition, ErrorType, Signal, ConfigFile, ConfigSection, WorkerThread, ExternalSystem, KGMetadata

**关系类型：** IMPORTS, DEFINES_CLASS, OWNS_METHOD, COMPOSES, INHERITS, CALLS_METHOD({confidence}), CONTAINS_CALL, HANDLES_ERROR, RAISES, CHECKS_CONDITION, EMITS_SIGNAL_IN, READS_CONFIG, DEPENDS_ON, TESTS, MOCKS

节点/边的实际数量取决于被分析项目的规模。可通过 `kgflow_diff` 查看不同 run 之间的增量变化。

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

## 版本

- Generator: 2.0.0
- Schema: 1.0.0

## 开发状态

```
Phase                    Status    Items
─────────────────────────────────────────────────────
P0: 核心工具链           ✅ 100%   7 CLI tools + parser + cypher gen
P0: Extractor 框架       ✅ 100%   base.py + registry + python_extractor (regression 0 diff)
P1: tree-sitter 查询     ✅ 100%   12 .scm files (python/javascript/go, 249 lines)
P1: 多语言验证           ✅ 100%   JavaScriptExtractor (JS/TS/JSX, 1056 lines)
P2: kgflow.toml 配置      ✅ 100%   项目级配置 + 多 root 支持
P2: Coverage 指标         ✅ 100%   CI 阈值 + 解析质量统计
P3: CLI 标准化            ✅ 100%   --json, argparse, env var creds, structured errors
P3: 多角色 Agent 编排     ✅ 100%   6 agent prompt + checkpoint 循环 + 失败升级协议
P3: MCP Server            ✅ 100%   10 typed tools via FastMCP
```

## 设计文档

完整设计方案: [kg-workflow-design.md](./kg-workflow-design.md)
