# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

KGFlow (Knowledge Graph Assisted Development Workflow) 是一个 CLI 工具链，将项目源码转换为 Neo4j 知识图谱，并通过多 Agent 协作实现 Code Review、影响分析、并行开发安全判定和架构门禁。

核心流程：项目源码 → AST/tree-sitter 解析 → 统一 dict 契约 → Cypher 生成 → Neo4j 图谱 → 查询工具链。

## 命令速查

```bash
# 图谱生成 + 导入
uv run python tools/generate_knowledge_graph.py
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
| `tools/` | 7 个 CLI 工具：图谱生成、导入、查询、对比、校验 |
| `extractors/` | 可插拔的 Extractor 框架：`base.py` 提供抽象基类 + 共享管道，`python_extractor.py` / `javascript_extractor.py` 是具体实现 |
| `queries/<lang>/` | tree-sitter .scm 查询文件（defs, imports, calls, control_flow） |
| `artifacts/schemas/` | 6 种工件 JSON Schema + extractor_output schema |
| `.claude/agents/` | 5 个 Agent 角色 prompt（影响分析/开发编排/子任务/审计/图谱维护）|

### Tools（7个）

| 工具 | 功能 |
|------|------|
| `generate_knowledge_graph.py` | 主入口：自动检测语言 → 调用 Extractor → 生成 Cypher + 存档旧版本 |
| `import_neo4j.py` | 清空数据库 → 分批执行 Cypher（约束→节点→关系）→ 统计验证 |
| `query_kg.py` | 7 个子命令：impact / call-chain / check-parallel / cross-layer / resolve-changes / config-readers / orphans |
| `diff_kg.py` | 解析两个 .cypher 文件 → 计算节点/边增量 → 输出 JSON diff |
| `validate_artifacts.py` | L1 结构校验 + L2 枚举校验 + L3 Neo4j 交叉引用校验 |
| `ast_parser.py` | 遗留 Python AST 解析器（V2 含 BodyAnalyzer 深度分析），被 python_extractor.py 替代中 |
| `cypher_generator.py` | 将结构化数据转为 Cypher MERGE/SET 语句，包含硬编码映射表 |

### Extractor 框架

`extractors/base.py` 中的 `BaseExtractor` 是抽象基类：
- `extract()` 是共享管道：遍历文件 → 逐个调用 `extract_file()` → 二遍过滤 → 返回统一 dict
- 新增语言只需继承 BaseExtractor，实现 `extract_file()`，用 `@register("lang")` 注册
- `OneFileResult` dataclass 定义了 15 个标准字段（modules, classes, methods, functions, imports, compositions, signals, call_sites, error_handlers, raises, conditions, returns, withs, signal_emits, attr_assignments）

### 图模型（节点 ~7500，关系 ~7900）

12 种节点类型（Module, Class, Method, Function, CallSite, Condition, ErrorType, Signal, ConfigFile, ConfigSection, WorkerThread, ExternalSystem），14 种关系类型（IMPORTS, DEFINES_CLASS, OWNS_METHOD, COMPOSES, INHERITS, CALLS_METHOD, CONTAINS_CALL, HANDLES_ERROR, RAISES, CHECKS_CONDITION, EMITS_SIGNAL_IN, READS_CONFIG, DEPENDS_ON, TESTS/MOCKS 等）。

### 多 Agent 工作流

4 阶段：Impact Analyst（并行）→ Lead Developer（门禁审核）→ Sub-Dev × N（并行）→ Auditor + KG Ops（并行）。5 个 Agent prompt 在 `.claude/agents/` 下。

### 技术栈

- Python >= 3.13（`.python-version`），依赖：neo4j, tree-sitter, tree-sitter-javascript
- 包管理：uv（`uv sync` / `uv run`）
- 代码格式：Ruff（有 `.ruff_cache`）
- Neo4j 运行在 `bolt://localhost:7687`，凭据 `neo4j / tply7620`
- 目标项目默认 `D:\PythonProgramming\1\Automation-Inspection`
