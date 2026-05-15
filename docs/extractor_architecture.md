# KGFlow Extractor 架构

## 核心原则

**解析层（语言相关）和生成层（Cypher）之间通过一个固定的 15-key dict 契约解耦。** 每种语言实现一个独立的 Extractor，输出同一格式的 dict。生成层永远不碰 AST/tree-sitter。

```
项目源码 ──→ extractors/<language>.py ──→ 统一 dict ──→ generate_cypher.py ──→ .cypher
                 ↑                              ↑                       ↑
           语言相关：ast/tree-sitter       15 key 契约         完全不动
```

## 如何写一个 Extractor（任何语言）

写一个语言 Extractor 只需要做一件事：

```python
# extractors/go_extractor.py
from extractors.base import BaseExtractor

class GoExtractor(BaseExtractor):
    def __init__(self, project_root: Path):
        super().__init__(project_root, language="go")
        self.file_suffixes = {".go"}

    def extract_file(self, source: str, file_path: str, mod_name: str) -> OneFileResult:
        """解析单个 .go 文件，输出 ExtractorOutput schema 规定的格式。"""
        # 1. 用 tree-sitter 解析
        # 2. 提取 imports / functions / calls / conditions / ...
        # 3. 塞进 OneFileResult
```

`BaseExtractor.extract()` 已经帮你做好了文件遍历、二遍过滤、汇总的逻辑。你只需在 `extract_file()` 里用 tree-sitter 解析语法树，按 schema 填结果。

## 一个 Extractor 必须提取什么

ExtractorOutput 的 `data` 字段包含 15 个 list，每个元素有固定的字段集合：

| 数据 | 必填字段 | 语义 |
|------|---------|------|
| `modules` | name, path, lines | 模块/文件 |
| `classes` | name, fqn, bases, file_path, start_line, end_line | 类/类型定义 |
| `methods` | name, fqn, owner_class, file_path, start_line, end_line | 方法（类内部） |
| `functions` | name, fqn, module, file_path, start_line, end_line | 顶层函数 |
| `imports` | from_module, to_module, what | 导入关系 |
| `compositions` | class, composes, attr | 组合关系（this.x = T(...)）|
| `signals` | class, name, params | Qt/事件信号 |
| `call_sites` | caller_fqn, call_expr, line, confidence, resolution | 函数调用点 |
| `error_handlers` | owner_fqn, exception_types | try/catch 块 |
| `raises` | owner_fqn, exception_name | throw/raise |
| `conditions` | owner_fqn, condition, type | if/while/for |
| `returns` | owner_fqn, return_type, is_none | return |
| `withs` | owner_fqn, context_expr | 资源管理（Python with / Go defer / Java try-with）|
| `signal_emits` | owner_fqn, signal_name, args_count | Qt event emit |
| `attr_assignments` | owner_class, attr, assigned_type, method_fqn | 字段赋值跟踪 |

完整 schema 见 `artifacts/schemas/extractor_output.schema.json`。

## 定位模型（所有实体共用）

```python
{
    "file_path": "engine/foo.py",       # repo 相对路径，POSIX /
    "start_line": 10, "start_col": 4,   # 起止行列
    "end_line": 25, "end_col": 8,
    "name": "Foo",                       # 短名
    "fqn": "pkg.Foo",                    # 全限定名
    "language": "python",                # 来源语言
}
```

tree-sitter 原生提供 start/end row/column，直接用。Python 的 ast 在 >=3.8 也有 `end_lineno`/`end_col_offset`。

## 命名空间/FQN 策略

BaseExtractor 默认实现：基于文件相对路径转 dotted name（`engine/foo.py` → `engine.foo`）。

各语言可覆盖：

| 语言 | FQN 策略 |
|------|---------|
| Python | 路径转 dotted（默认）|
| Go | go.mod module + package xxx + 目录 |
| Java | package a.b.c; 声明 |
| JS/TS | path_based 或 tsconfig paths 映射 |

## 解析质量

所有推断类关系统一带 confidence + resolution 字段：

```python
{
    "confidence": "high" | "medium" | "low",
    "resolution": "exact" | "heuristic" | "unresolved",
    "evidence": "import_match" | "same_file_match" | "type_inference" | ...
}
```

- `high`（exact）：调用目标确定可解析 → Gate 2 BLOCK 材料
- `medium`（heuristic）：启发式匹配 → WARN
- `low`（unresolved）：无法解析 → 跳过

## 覆盖度指标

每个 Extractor 输出 `coverage` 字段：

```python
{
    "files_scanned": 120, "files_parsed_ok": 118, "parse_errors": 2,
    "functions_found": 300, "calls_found": 500, "imports_found": 80,
    "classes_found": 50, "conditions_found": 200,
}
```

CI 设最低阈值（`parse_errors == 0`、`functions_found > 0`），防止悄悄啥也没抽到。

## 以 Python 为例的迁移

现有一个 `tools/ast_parser.py`（~950 行单体函数），需要拆入新架构：

| 逻辑类 | 行数 | 去向 |
|--------|------|------|
| 文件遍历 / 排除 / 模块名计算 | ~100 行 | `base.py`（通用，所有语言共享）|
| 二遍过滤 composition / call_resolve | ~50 行 | `base.py`（通用）|
| ast.parse / isinstance 分发 / unparse / self 模式 | ~650 行 | `python_extractor.py`（Python 特有）|
| Cypher 生成 | ~200 行 | `cypher_generator.py`（不动）|

Python 和其他语言一样，只需实现 `extract_file()`。区别只在于 Python 用 `ast` 模块解析，其他语言用 tree-sitter。

## 注册方式

```python
# extractors/__init__.py
EXTRACTORS = {
    "python": PythonAstExtractor,
    "go": GoExtractor,
    "javascript": JavaScriptExtractor,
    # ...
}
```

`detect_language()` 优先查 `kgflow.toml`，查不到再按文件后缀推测。
