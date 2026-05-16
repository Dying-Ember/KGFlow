# KGFlow — Knowledge Graph Assisted Development Workflow

将项目源码转化为 Neo4j 知识图谱作为 AI Agent 的共享记忆，并通过多角色 Agent 协作（Lead → Architect → Analyst/Developer/Auditor/Curator）自动完成代码分析、变更影响评估和架构门禁的 AI Agent 编排系统。

## 核心能力

```
┌─────────────────────────────────────────────────┐
│  编排层  Agent 工作流                             │
│  claude --agent kgflow-lead                      │
│  Lead → Architect → Analyst/Developer/          │
│         Auditor/Curator                          │
│  通信协议: artifacts/ + checkpoint 循环          │
├─────────────────────────────────────────────────┤
│  接口层  MCP Server (10 typed tools)             │
├─────────────────────────────────────────────────┤
│  数据层  源码 → AST/树解析 → Neo4j 知识图谱      │
└─────────────────────────────────────────────────┘
```

| 能力 | 入口 | 说明 |
|------|------|------|
| 图谱生成 | `generate_knowledge_graph.py` | 用 Python `ast` 模块解析源码，生成 Cypher 导入脚本 |
| 增量对比 | `diff_kg.py` | 比较两次生成结果，输出节点/边增量 + 变更归因 |
| 影响分析 | `kgflow_query_impact` (MCP) | 输入方法，输出调用链、配置引用、测试覆盖 |
| 并发判定 | `kgflow_query_check_parallel` (MCP) | 两层 Gate 判断两个子任务能否并行开发 |
| 调用链 | `kgflow_query_call_chain` (MCP) | 上溯调用者/下追被调用者 |
| 架构检查 | `kgflow_query_cross_layer` (MCP) | 检测层间依赖违规（如 engine → app）|
| 变更映射 | `kgflow_query_resolve_changes` (MCP) | git diff → KG Method 节点映射 |
| 工件校验 | `validate_artifacts.py` | L1 结构 + L2 枚举 + L3 Neo4j 交叉引用 |

## 快速开始

### 1. 安装

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | >= 3.13 | 运行环境 |
| [uv](https://docs.astral.sh/uv/) | 最新 | 包管理 |
| [Neo4j](https://neo4j.com/download/) | 5.x | 图数据库（bolt://localhost:7687）|
| 被分析项目 | — | 你的源码（默认: `D:\PythonProgramming\1\Automation-Inspection`）|

```bash
git clone https://github.com/Dying-Ember/KGFlow.git
cd KGFlow
uv sync
```

### 2. 配置 MCP Server

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

完成后重新启动 Claude Code。

### 3. 给 Lead 派任务（核心工作流）

在终端启动 KGFlow 模式，进入对话后直接说开发需求，全流程自动执行：

```bash
claude --agent kgflow-lead
```

进入对话后直接说：

Lead 会自动编排内部流程，每个阶段完成后等你确认：

```
你给出需求 → Lead 开始处理
          → [Phase 1] 自动分析影响范围 + 拆任务 → 等你看方案
          → [Phase 2] 你确认方案 → 自动运行门禁判定
          → [Phase 3] 自动并行开发 → 合并变更
          → [Phase 4] 自动审计 + 更新知识图谱 → 汇报结果
```

整个过程中你只需要**做两件事**：给需求、确认方案。其余由 Lead 驱动。

> 不需要手动 spawn Architect、Analyst、Developer — Lead 会按需自动 spawn。详见下文[多 Agent 工作流](#多-agent-工作流)和各角色 prompt（`.claude/agents/`）。

### 4. 手动调 CLI（调试用）

直接调底层工具进行单步操作：

```bash
# 一键验证解析引擎是否正常工作
uv run python tools/generate_knowledge_graph.py --ci

# 影响范围分析
uv run python tools/query_kg.py impact \
  --methods '["ClassName.method"]' --depth 3

# 增量对比（需要至少两个存档）
uv run python tools/diff_kg.py --from-latest 2 --to-latest 1

# 工件校验（输出 JSON）
uv run python tools/validate_artifacts.py --json artifacts/
```

所有 CLI 工具支持 `--json` 参数，错误输出到 stderr，格式统一：`{"error": true, "code": "...", "detail": "..."}`。
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
│   ├── kgflow-lead.md               ← 人机接口 Agent prompt
│   ├── kgflow-architect.md          ← 技术编排 Agent prompt（checkpoint 循环）
│   ├── kgflow-analyst.md            ← 影响分析 Agent prompt
│   ├── kgflow-developer.md          ← 子任务实现 Agent prompt
│   ├── kgflow-auditor.md            ← 审计 Agent prompt
│   └── kgflow-curator.md            ← 图谱维护 Agent prompt
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
Phase 1 (Architect 编排)
  Architect → spawn Analyst → artifacts/impact_report.json
           → 拆任务 → artifacts/plan_tasks.json
           → checkpoint 退出，等待人类确认

Phase 2 (Architect 重生)
  读 checkpoint → Gate 1/2/3 判定 → artifacts/change_intent.json
  → checkpoint 退出

Phase 3 (Architect 重生)
  读 checkpoint → spawn Developer × N → 合并 diff
  → checkpoint 退出

Phase 4 (Architect 重生)
  读 checkpoint → spawn Auditor + Curator → 检查结果
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
