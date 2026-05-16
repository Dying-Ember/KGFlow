# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

KGFlow (Knowledge Graph Assisted Development Workflow) 是一个 CLI 工具链，将项目源码转换为 Neo4j 知识图谱，并通过多 Agent 协作实现 Code Review、影响分析、并行开发安全判定和架构门禁。

核心流程：项目源码 → AST/tree-sitter 解析 → 统一 dict 契约 → Cypher 生成 → Neo4j 图谱 → 查询工具链。

## 命令速查

```bash
# 图谱生成 + 导入
uv run python tools/generate_knowledge_graph.py              # 普通模式
uv run python tools/generate_knowledge_graph.py --ci          # CI 模式（覆盖阈值检查）
uv run python tools/import_neo4j.py

# 图谱查询 (7个子命令)
uv run python tools/query_kg.py impact --methods '["ClassName.method"]' --depth 3
uv run python tools/query_kg.py call-chain --method "module.ClassName.method" --direction down --depth 3
uv run python tools/query_kg.py check-parallel --task-a-methods '["A.method"]' --task-b-methods '["B.method"]'
uv run python tools/query_kg.py cross-layer --from-layer engine --to-layer app
uv run python tools/query_kg.py resolve-changes --project-root "path/to/project"
uv run python tools/query_kg.py config-readers --config-key feishu
uv run python tools/query_kg.py orphans [--label Method]

# 增量对比
uv run python tools/diff_kg.py --from-latest 2 --to-latest 1

# 工件校验
uv run python tools/validate_artifacts.py artifacts/

# 运行测试
uv run pytest
uv run pytest tests/test_file.py -k "test_name"
```

## MCP Server（Agent 自动调用）

所有工具通过 `tools/mcp_server.py` 暴露为 MCP typed tools。
Sub-agent/teammate 继承父级 session 的 MCP 配置，自动可用。

**10 个 MCP tools：**

| Tool | 功能 |
|------|------|
| `kgflow_generate` | 生成知识图谱 Cypher |
| `kgflow_query_impact` | 影响范围分析（上游调用者 + 下游被调用者 + 配置依赖）|
| `kgflow_query_call_chain` | 调用链追踪（上溯/下追）|
| `kgflow_query_check_parallel` | Gate 2 并行安全判定 |
| `kgflow_query_cross_layer` | 架构层间依赖违规检查 |
| `kgflow_query_resolve_changes` | git diff → Method 节点映射 |
| `kgflow_query_config_readers` | 配置阅读者查询 |
| `kgflow_query_orphans` | 孤立节点发现 |
| `kgflow_diff` | Run-to-run 图谱增量对比 |
| `kgflow_validate` | L1+L2+L3 工件校验 |

## 多 Agent 工作流（Checkpoint 驱动）

架构分三层，每层通过 artifact 文件通信，不传递对话 transcript。

```
你（人类）←→ Lead
   ctx: ~30k，只装对话 + checkpoint 状态
   不读任何技术 artifact

   ↓ artifacts/task_brief.md, artifacts/checkpoint.json

   Tech Lead（技术编排）
     ctx ~80k，每次重生读 checkpoint 决定从哪个 Phase 继续
     每个 Phase 结束时写 checkpoint → 退出 → 释放 ctx

   ├─ Phase 1: spawn Impact Analyst → impact_report + plan_tasks
   │           写 checkpoint，等人类确认
   ├─ Phase 2: Gate 判定 → change_intent.json
   │           写 checkpoint，Lead 开始派 Sub-Dev
   ├─ Phase 3: spawn Sub-Dev × N → 合并 diff
   │           写 checkpoint
   └─ Phase 4: spawn Auditor + KG Ops → 检查结果
               写 checkpoint = 完成

        ↓ artifacts/ 通信

   Specialists（Impact Analyst / Sub-Dev / Auditor / KG Ops）
     ctx 每次重生，隔离干净
```

### 角色列表

| Agent | 职责 | 使用的 MCP tools |
|-------|------|------------------|
| `lead.md` | 人机交互，接收需求，展示方案 | 无（只读 checkpoint，spawn tech-lead）|
| `tech-lead.md` | 技术编排，设计+门禁+派任务 | check-parallel, cross-layer, resolve-changes |
| `impact-analyst.md` | 影响范围分析 | kgflow_query_impact, kgflow_query_call_chain |
| `sub-dev.md` | 实现单个子任务 | kgflow_query_call_chain |
| `auditor.md` | 审计 | kgflow_query_cross_layer, kgflow_query_orphans, kgflow_validate |
| `kg-ops.md` | 图谱维护 | kgflow_generate, kgflow_diff, kgflow_validate |

## Agent Artifact 契约

所有 Specialist（Impact Analyst / Sub-Dev / Auditor / KG Ops）的输出统一格式如下：

```json
{
  "status": "ok",
  "reasoning": [
    { "step": "确定入口方法",
      "approach": "解析任务描述，搜索项目中的 upload 方法",
      "finding": "发现 2 个 upload 方法，根据上下文选择了 FeishuClient.upload_file",
      "confidence": "medium" }
  ],
  ...
}
```

Status 字段只有两个值：
- `"ok"` — 正常完成，Tech Lead 如果怀疑静默错误可以调一个工具验证 reasoning 中 confidence 最低的条目
- `"failed"` — 工具报错，附带 `failure_type`、`retryable`、`advice`

Reasoning 字段每个条目记录一个**决策点**，不是每个工具调用。字段说明：

| 字段 | 含义 |
|------|------|
| `step` | 当时要解决的问题 |
| `approach` | 用什么工具/方法来解决 |
| `finding` | 得出的结论 |
| `confidence` | 对自己的结论有多大把握（high / medium / low） |

Failure 时 `reasoning` 最后一条记录出错前的上下文。Tech Lead 据此判断重试 (retry)、追问 (clarify) 还是升级给人类 (escalate)。同一个 Phase 内重试+澄清共享 3 次配额。

## 架构

### 分层设计

```
源码 → extractors/<language>.py → 统一 dict → cypher_generator.py → .cypher → Neo4j
         ↑                            ↑                      ↑
    语言相关 (ast/tree-sitter)     15-key 契约         完全不动
```

**关键解耦：** 解析层（语言相关）和生成层（Cypher）通过一个固定的 15-key dict 契约隔离。生成层不碰任何 AST/tree-sitter 逻辑。

### 目录结构

| 目录/文件 | 作用 |
|-----------|------|
| `tools/` | 9 个工具：图谱生成、导入、查询、对比、校验、配置加载、MCP Server |
| `kgflow.toml` | 项目级配置文件（语言、目标路径等）|
| `extractors/` | 可插拔的 Extractor 框架：`base.py` 提供抽象基类 + 共享管道，`python_extractor.py` / `javascript_extractor.py` 是具体实现 |
| `queries/<lang>/` | tree-sitter .scm 查询文件（defs, imports, calls, control_flow） |
| `artifacts/schemas/` | 6 种工件 JSON Schema + extractor_output schema |
| `.claude/agents/` | 6 个 Agent 角色 prompt（三层编排 + checkpoint 循环 + 失败升级协议）|

### Tools（11个）

| 工具 | 功能 |
|------|------|
| `generate_knowledge_graph.py` | 主入口：自动检测语言 → 调用 Extractor → 生成 Cypher + 存档旧版本（支持 `--ci` 模式）|
| `import_neo4j.py` | 清空数据库 → 分批执行 Cypher（约束→节点→关系）→ 统计验证 |
| `query_kg.py` | 7 个子命令：impact / call-chain / check-parallel / cross-layer / resolve-changes / config-readers / orphans |
| `diff_kg.py` | 解析两个 .cypher 文件 → 计算节点/边增量 → 输出 JSON diff |
| `validate_artifacts.py` | L1 结构校验 + L2 枚举校验 + L3 Neo4j 交叉引用校验 |
| `ast_parser.py` | 遗留 Python AST 解析器（V2 含 BodyAnalyzer 深度分析），被 python_extractor.py 替代中 |
| `cypher_generator.py` | 将结构化数据转为 Cypher MERGE/SET 语句，包含硬编码映射表 |
| `config.py` | `load_kgflow_config()` 配置加载器，`tomllib` 读取 `kgflow.toml` |
| `errors.py` | 结构化 JSON 错误输出（错误码 + 统一格式）|
| `neo4j_config.py` | Neo4j 凭据从 `KGFLOW_NEO4J_*` 环境变量读取 |
| `mcp_server.py` | FastMCP Server，10 个 typed tools 供 Agent 调用 |

### Extractor 框架

`extractors/base.py` 中的 `BaseExtractor` 是抽象基类：
- `extract()` 是共享管道：遍历文件 → 逐个调用 `extract_file()` → 二遍过滤 → 返回统一 dict
- 新增语言只需继承 BaseExtractor，实现 `extract_file()`，用 `@register("lang")` 注册
- `OneFileResult` dataclass 定义了 15 个标准字段（modules, classes, methods, functions, imports, compositions, signals, call_sites, error_handlers, raises, conditions, returns, withs, signal_emits, attr_assignments）

### 图模型（节点 ~7500，关系 ~7900）

12 种节点类型（Module, Class, Method, Function, CallSite, Condition, ErrorType, Signal, ConfigFile, ConfigSection, WorkerThread, ExternalSystem），14 种关系类型（IMPORTS, DEFINES_CLASS, OWNS_METHOD, COMPOSES, INHERITS, CALLS_METHOD, CONTAINS_CALL, HANDLES_ERROR, RAISES, CHECKS_CONDITION, EMITS_SIGNAL_IN, READS_CONFIG, DEPENDS_ON, TESTS/MOCKS 等）。

### 技术栈

- Python >= 3.13（`.python-version`），依赖：neo4j, tree-sitter, tree-sitter-javascript
- 包管理：uv（`uv sync` / `uv run`）
- 代码格式：Ruff（有 `.ruff_cache`）
- Neo4j 运行在 `bolt://localhost:7687`，凭据 `neo4j / tply7620`
- MCP Server: 10 个 typed tools via `tools/mcp_server.py`
- Agent 编排: `.claude/agents/*.md` 6 个角色（lead + tech-lead + 4 specialists）
- 目标项目读取自 `kgflow.toml` 的 `[project.target]`
