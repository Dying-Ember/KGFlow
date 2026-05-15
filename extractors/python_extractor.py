"""Python-specific extractor using stdlib ast module.

Ports ALL logic from tools/ast_parser.py into a BaseExtractor subclass.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

from extractors.base import BaseExtractor, OneFileResult
from extractors import register

_SIGNAL_NAMES = {"Signal", "pyqtSignal", "Slot", "pyqtSlot"}

_PROJECT_PREFIXES = ("engine", "app", "tools", "tests", "config")

_SCAN_DIRS = ("engine", "app", "tools", "tests")

_EXCLUDED_DIRS = {"__pycache__", ".venv", ".git", "dist", "build", ".pytest_cache"}

_EXCLUDED_PATTERNS = (".egg-info",)


@register("python")
class PythonAstExtractor(BaseExtractor):
    """Python-specific extractor using stdlib ast module."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root, language="python")
        self.extractor_version = "2.0.0"
        self.file_suffixes = {".py"}
        self._known_class_fqns: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Overrides: match original scan behavior
    # ------------------------------------------------------------------

    def _walk_project(self):
        """Yield only .py files under the project source dirs (engine, app, tools, tests)."""
        for scan_dir in _SCAN_DIRS:
            dir_path = self.project_root / scan_dir
            if not dir_path.is_dir():
                continue
            for py_file in dir_path.rglob("*.py"):
                if self._is_excluded(py_file):
                    continue
                yield py_file

    @staticmethod
    def _is_excluded(path: Path) -> bool:
        parts = set(path.parts)
        if parts & _EXCLUDED_DIRS:
            return True
        return any(pat in parts for pat in _EXCLUDED_PATTERNS)

    # ------------------------------------------------------------------
    # Main entry point per file
    # ------------------------------------------------------------------

    def extract_file(self, source: str, file_path: str, mod_name: str) -> OneFileResult:
        """Parse one .py file, return all constructs."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return OneFileResult(errors=[f"SyntaxError in {file_path}"])

        result = OneFileResult()
        self._extract_module(tree, mod_name, file_path, result)
        return result

    # ------------------------------------------------------------------
    # Top-level module dispatch
    # ------------------------------------------------------------------

    def _extract_module(
        self,
        tree: ast.Module,
        mod_name: str,
        file_path: str,
        result: OneFileResult,
    ) -> None:
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                self._handle_import(node, mod_name, result)
            elif isinstance(node, ast.ImportFrom):
                self._handle_import_from(node, mod_name, result)
            elif isinstance(node, ast.ClassDef):
                self._handle_class(node, mod_name, file_path, result)
            elif isinstance(node, ast.FunctionDef):
                fqn = f"{mod_name}.{node.name}"
                result.functions.append({
                    "name": node.name,
                    "fqn": fqn,
                    "module": mod_name,
                    "file_path": file_path,
                    "line": node.lineno,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno,
                    "start_col": node.col_offset,
                    "end_col": node.end_col_offset,
                    "params": self._extract_params(node.args),
                    "decorators": self._decorator_names(node),
                })
                self._analyze_function_body(
                    node, fqn, mod_name, {},
                    result,
                )

    # ------------------------------------------------------------------
    # Import handlers
    # ------------------------------------------------------------------

    def _handle_import(self, node: ast.Import, mod_name: str, result: OneFileResult) -> None:
        for alias in node.names:
            to_mod = alias.name
            if not self._is_project_module(to_mod):
                continue
            name = alias.asname or to_mod
            result.imports.append({
                "from_module": mod_name,
                "to_module": to_mod,
                "what": name,
                "line": node.lineno,
            })

    def _handle_import_from(
        self, node: ast.ImportFrom, mod_name: str, result: OneFileResult
    ) -> None:
        base_mod = node.module or ""
        if node.level > 0:
            parts = mod_name.split(".")
            if node.level > len(parts):
                return
            resolved_parts = parts[:-node.level] if node.level else parts
            if base_mod:
                resolved_parts = resolved_parts + [base_mod] if resolved_parts else [base_mod]
            base_mod = ".".join(resolved_parts)
        if not self._is_project_module(base_mod):
            return
        for alias in node.names:
            name = alias.asname or alias.name
            result.imports.append({
                "from_module": mod_name,
                "to_module": base_mod,
                "what": name,
                "line": node.lineno,
            })

    # ------------------------------------------------------------------
    # Class handler
    # ------------------------------------------------------------------

    def _handle_class(
        self,
        node: ast.ClassDef,
        mod_name: str,
        file_path: str,
        result: OneFileResult,
    ) -> None:
        fqn = f"{mod_name}.{node.name}"
        bases = [self._base_name(b) for b in node.bases]
        result.classes.append({
            "name": node.name,
            "fqn": fqn,
            "module": mod_name,
            "bases": bases or ["object"],
            "file_path": file_path,
            "line": node.lineno,
            "start_line": node.lineno,
            "end_line": node.end_lineno,
            "start_col": node.col_offset,
            "end_col": node.end_col_offset,
        })

        method_nodes: list[ast.FunctionDef] = []
        for body_node in node.body:
            if isinstance(body_node, ast.FunctionDef):
                self._handle_method(body_node, mod_name, node.name, file_path, result)
                method_nodes.append(body_node)
            elif isinstance(body_node, ast.Assign):
                self._handle_signal(body_node, mod_name, node.name, result)

        # V2 Phase A: build self-attr -> type map from ALL methods
        attr_map: dict[str, str] = {}
        for mnode in method_nodes:
            self._phase_a_collect_attrs(mnode, attr_map)

        # V2 Phase B: deep body analysis for each method
        for mnode in method_nodes:
            owner_fqn = f"{fqn}.{mnode.name}"
            self._analyze_function_body(
                mnode, owner_fqn, fqn, attr_map,
                result,
            )

    # ------------------------------------------------------------------
    # Method / Function helpers
    # ------------------------------------------------------------------

    def _handle_method(
        self,
        node: ast.FunctionDef,
        mod_name: str,
        class_name: str,
        file_path: str,
        result: OneFileResult,
    ) -> None:
        owner_fqn = f"{mod_name}.{class_name}"
        fqn = f"{owner_fqn}.{node.name}"
        result.methods.append({
            "name": node.name,
            "fqn": fqn,
            "owner_class": owner_fqn,
            "file_path": file_path,
            "line": node.lineno,
            "start_line": node.lineno,
            "end_line": node.end_lineno,
            "start_col": node.col_offset,
            "end_col": node.end_col_offset,
            "params": self._extract_params(node.args),
            "decorators": self._decorator_names(node),
        })

        if node.name == "__init__":
            self._detect_composition(node, mod_name, class_name, result)

    @staticmethod
    def _extract_params(args: ast.arguments) -> list[str]:
        params: list[str] = []
        for a in args.args:
            params.append(a.arg)
        if args.vararg:
            params.append(f"*{args.vararg.arg}")
        for a in args.kwonlyargs:
            params.append(a.arg)
        if args.kwarg:
            params.append(f"**{args.kwarg.arg}")
        return params

    @staticmethod
    def _decorator_names(node: ast.FunctionDef) -> list[str]:
        names: list[str] = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                names.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                names.append(dec.attr)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    names.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    names.append(dec.func.attr)
        return names

    @staticmethod
    def _base_name(base_node: ast.expr) -> str:
        if isinstance(base_node, ast.Name):
            return base_node.id
        if isinstance(base_node, ast.Attribute):
            return base_node.attr
        if isinstance(base_node, ast.Subscript):
            return PythonAstExtractor._base_name(base_node.value)
        return "unknown"

    # ------------------------------------------------------------------
    # Composition detection (__init__ body)
    # ------------------------------------------------------------------

    def _detect_composition(
        self,
        node: ast.FunctionDef,
        mod_name: str,
        class_name: str,
        result: OneFileResult,
    ) -> None:
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    comp = self._match_self_assign(target, stmt.value)
                    if comp:
                        result.compositions.append({
                            "class": f"{mod_name}.{class_name}",
                            "composes": comp,
                            "attr": self._target_attr(target),
                            "line": stmt.lineno,
                        })
            elif isinstance(stmt, ast.AnnAssign):
                comp = self._match_self_ann_assign(stmt)
                if comp:
                    result.compositions.append({
                        "class": f"{mod_name}.{class_name}",
                        "composes": comp,
                        "attr": self._target_attr(stmt.target),
                        "line": stmt.lineno,
                    })

    @staticmethod
    def _match_self_assign(target: ast.expr, value: ast.expr) -> str | None:
        if not isinstance(value, ast.Call):
            return None
        if not PythonAstExtractor._is_self_attr(target):
            return None
        if isinstance(value.func, ast.Name):
            return value.func.id
        if isinstance(value.func, ast.Attribute):
            return value.func.attr
        return None

    @staticmethod
    def _match_self_ann_assign(stmt: ast.AnnAssign) -> str | None:
        if not PythonAstExtractor._is_self_attr(stmt.target):
            return None
        ann = stmt.annotation
        if isinstance(ann, ast.Name):
            return ann.id
        if isinstance(ann, ast.Attribute):
            return ann.attr
        return None

    @staticmethod
    def _is_self_attr(expr: ast.expr) -> bool:
        return (
            isinstance(expr, ast.Attribute)
            and isinstance(expr.value, ast.Name)
            and expr.value.id == "self"
        )

    @staticmethod
    def _target_attr(target: ast.expr) -> str:
        if isinstance(target, ast.Attribute):
            return target.attr
        return "?"

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------

    def _handle_signal(
        self,
        node: ast.Assign,
        mod_name: str,
        class_name: str,
        result: OneFileResult,
    ) -> None:
        value = node.value
        if not isinstance(value, ast.Call):
            return

        signal_name = None
        if isinstance(value.func, ast.Name):
            if value.func.id in _SIGNAL_NAMES:
                signal_name = value.func.id
        elif isinstance(value.func, ast.Attribute):
            if value.func.attr in _SIGNAL_NAMES:
                signal_name = value.func.attr

        if signal_name is None:
            return

        params = [self._sig_param(a) for a in value.args]
        for target in node.targets:
            if isinstance(target, ast.Name):
                result.signals.append({
                    "class": f"{mod_name}.{class_name}",
                    "name": target.id,
                    "params": params,
                    "line": node.lineno,
                })

    @staticmethod
    def _sig_param(arg: ast.expr) -> str:
        if isinstance(arg, ast.Name):
            return arg.id
        if isinstance(arg, ast.Attribute):
            return arg.attr
        if isinstance(arg, ast.Constant):
            return str(arg.value)
        try:
            return ast.unparse(arg)
        except Exception:
            return "?"

    # ------------------------------------------------------------------
    # V2 Phase A: collect self-attr -> class-name mappings
    # ------------------------------------------------------------------

    def _phase_a_collect_attrs(
        self, method_node: ast.FunctionDef, attr_map: dict[str, str]
    ) -> None:
        for child in ast.walk(method_node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if self._is_self_attr(target) and isinstance(child.value, ast.Call):
                        cls_name = self._call_class_name(child.value)
                        if cls_name:
                            attr_map[target.attr] = cls_name
            elif isinstance(child, ast.AnnAssign):
                if self._is_self_attr(child.target) and child.annotation is not None:
                    cls_name = self._annotation_class_name(child.annotation)
                    if cls_name:
                        attr_map[child.target.attr] = cls_name

    @staticmethod
    def _call_class_name(call_node: ast.Call) -> str | None:
        if isinstance(call_node.func, ast.Name):
            return call_node.func.id
        if isinstance(call_node.func, ast.Attribute):
            return call_node.func.attr
        return None

    @staticmethod
    def _annotation_class_name(ann: ast.expr) -> str | None:
        if isinstance(ann, ast.Name):
            return ann.id
        if isinstance(ann, ast.Attribute):
            return ann.attr
        if isinstance(ann, ast.Subscript):
            return PythonAstExtractor._annotation_class_name(ann.value)
        return None

    # ------------------------------------------------------------------
    # V2 Phase B: deep body analysis
    # ------------------------------------------------------------------

    def _analyze_function_body(
        self,
        fn_node: ast.FunctionDef,
        owner_fqn: str,
        owner_class_fqn: str,
        attr_map: dict[str, str],
        result: OneFileResult,
    ) -> None:
        for child in ast.walk(fn_node):
            if isinstance(child, ast.Call):
                self._collect_call(child, owner_fqn, attr_map, result)
            elif isinstance(child, ast.Try):
                self._collect_try(child, owner_fqn, result)
            elif isinstance(child, ast.Raise):
                self._collect_raise(child, owner_fqn, result)
            elif isinstance(child, (ast.If, ast.While)):
                self._collect_condition(child, owner_fqn, result)
            elif isinstance(child, ast.For):
                self._collect_for(child, owner_fqn, result)
            elif isinstance(child, ast.Return):
                self._collect_return(child, owner_fqn, result)
            elif isinstance(child, ast.With):
                self._collect_with(child, owner_fqn, result)
            elif isinstance(child, ast.Assign):
                self._collect_assign(child, owner_fqn, owner_class_fqn, result)
            elif isinstance(child, ast.AnnAssign):
                self._collect_ann_assign(child, owner_fqn, owner_class_fqn, result)

    # ------------------------------------------------------------------
    # V2 individual collectors
    # ------------------------------------------------------------------

    def _collect_call(
        self,
        node: ast.Call,
        owner_fqn: str,
        attr_map: dict[str, str],
        result: OneFileResult,
    ) -> None:
        call_expr = ast.unparse(node.func)

        is_self_call = False
        resolved_target = None
        self_attr: str | None = None
        method_name: str | None = None

        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr

            if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
                is_self_call = True
            elif self._is_self_attr(node.func.value):
                is_self_call = True
                self_attr = node.func.value.attr

                if method_name == "emit":
                    result.signal_emits.append({
                        "owner_fqn": owner_fqn,
                        "signal_name": self_attr,
                        "args_count": len(node.args),
                        "line": node.lineno,
                    })

                if self_attr in attr_map:
                    resolved_target = attr_map[self_attr] + "." + method_name

        result.call_sites.append({
            "caller_fqn": owner_fqn,
            "call_expr": call_expr,
            "resolved_target": resolved_target,
            "is_self_call": is_self_call,
            "line": node.lineno,
            "_self_attr": self_attr,
        })

    def _collect_try(
        self, node: ast.Try, owner_fqn: str, result: OneFileResult
    ) -> None:
        exception_types: list[str] = []
        for handler in node.handlers:
            self._extract_exception_names(handler.type, exception_types)

        if not exception_types:
            exception_types.append("Exception")

        result.error_handlers.append({
            "owner_fqn": owner_fqn,
            "exception_types": exception_types,
            "has_finally": bool(node.finalbody),
            "line": node.lineno,
        })

    @staticmethod
    def _extract_exception_names(exc_node: ast.expr | None, into: list[str]) -> None:
        if exc_node is None:
            return
        if isinstance(exc_node, ast.Name):
            into.append(exc_node.id)
        elif isinstance(exc_node, ast.Tuple):
            for elt in exc_node.elts:
                PythonAstExtractor._extract_exception_names(elt, into)
        elif isinstance(exc_node, ast.Attribute):
            into.append(exc_node.attr)

    def _collect_raise(
        self, node: ast.Raise, owner_fqn: str, result: OneFileResult
    ) -> None:
        exc_name = "Exception"
        if node.exc is not None:
            if isinstance(node.exc, ast.Call):
                exc_name = self._call_class_name(node.exc) or "Exception"
            elif isinstance(node.exc, ast.Name):
                exc_name = node.exc.id
            elif isinstance(node.exc, ast.Attribute):
                exc_name = node.exc.attr

        result.raises.append({
            "owner_fqn": owner_fqn,
            "exception_name": exc_name,
            "line": node.lineno,
        })

    @staticmethod
    def _collect_condition(
        node: ast.If | ast.While, owner_fqn: str, result: OneFileResult
    ) -> None:
        cond_type = "if" if isinstance(node, ast.If) else "while"
        cond_expr = ast.unparse(node.test)
        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_expr,
            "type": cond_type,
            "line": node.lineno,
        })

    @staticmethod
    def _collect_for(
        node: ast.For, owner_fqn: str, result: OneFileResult
    ) -> None:
        cond_expr = ast.unparse(node.iter)
        result.conditions.append({
            "owner_fqn": owner_fqn,
            "condition": cond_expr,
            "type": "for",
            "line": node.lineno,
        })

    @staticmethod
    def _collect_return(
        node: ast.Return, owner_fqn: str, result: OneFileResult
    ) -> None:
        if node.value is None:
            result.returns.append({
                "owner_fqn": owner_fqn,
                "return_type": "None",
                "is_none": True,
                "line": node.lineno,
            })
        else:
            type_name = type(node.value).__name__
            is_none = isinstance(node.value, ast.Constant) and node.value.value is None
            result.returns.append({
                "owner_fqn": owner_fqn,
                "return_type": type_name,
                "is_none": is_none,
                "line": node.lineno,
            })

    @staticmethod
    def _collect_with(
        node: ast.With, owner_fqn: str, result: OneFileResult
    ) -> None:
        for item in node.items:
            ctx_expr = ast.unparse(item.context_expr)
            result.withs.append({
                "owner_fqn": owner_fqn,
                "context_expr": ctx_expr,
                "line": node.lineno,
            })

    def _collect_assign(
        self,
        node: ast.Assign,
        owner_fqn: str,
        owner_class_fqn: str,
        result: OneFileResult,
    ) -> None:
        assigned_type = self._value_type_name(node.value)
        for target in node.targets:
            target_name = self._target_attr_name(target)
            result.attr_assignments.append({
                "owner_class": owner_class_fqn,
                "attr": target_name,
                "assigned_type": assigned_type,
                "method_fqn": owner_fqn,
                "line": node.lineno,
            })

    def _collect_ann_assign(
        self,
        node: ast.AnnAssign,
        owner_fqn: str,
        owner_class_fqn: str,
        result: OneFileResult,
    ) -> None:
        assigned_type = (
            self._annotation_class_name(node.annotation) if node.annotation else None
        )
        target_name = self._target_attr_name(node.target)
        result.attr_assignments.append({
            "owner_class": owner_class_fqn,
            "attr": target_name,
            "assigned_type": assigned_type,
            "method_fqn": owner_fqn,
            "line": node.lineno,
        })

    @staticmethod
    def _value_type_name(value: ast.expr) -> str | None:
        if isinstance(value, ast.Call):
            return PythonAstExtractor._call_class_name(value)
        if isinstance(value, ast.Constant):
            return type(value.value).__name__
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            return PythonAstExtractor._unparse_safe(value)
        if isinstance(value, ast.List):
            return "list"
        if isinstance(value, ast.Dict):
            return "dict"
        if isinstance(value, ast.Set):
            return "set"
        if isinstance(value, ast.Tuple):
            return "tuple"
        if isinstance(value, ast.ListComp):
            return "list"
        if isinstance(value, ast.DictComp):
            return "dict"
        if isinstance(value, ast.SetComp):
            return "set"
        if isinstance(value, ast.Lambda):
            return "lambda"
        if isinstance(value, ast.BinOp):
            return "BinOp"
        if isinstance(value, ast.UnaryOp):
            return "UnaryOp"
        if isinstance(value, ast.IfExp):
            return "IfExp"
        return None

    @staticmethod
    def _target_attr_name(target: ast.expr) -> str:
        if isinstance(target, ast.Attribute):
            return target.attr
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.Subscript):
            return PythonAstExtractor._target_attr_name(target.value)
        try:
            return ast.unparse(target)
        except Exception:
            return "?"

    @staticmethod
    def _unparse_safe(node: ast.expr) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                return (
                    f"{PythonAstExtractor._unparse_safe(node.value)}.{node.attr}"
                )
            if isinstance(node, ast.Subscript):
                return f"{PythonAstExtractor._unparse_safe(node.value)}[...]"
            return "?"

    # ------------------------------------------------------------------
    # Module check
    # ------------------------------------------------------------------

    @staticmethod
    def _is_project_module(module_name: str) -> bool:
        return module_name.startswith(_PROJECT_PREFIXES)

    # ------------------------------------------------------------------
    # Override: Python-specific call resolution (second pass)
    # ------------------------------------------------------------------

    def _resolve_calls(
        self,
        call_sites: list[dict],
        methods: list[dict],
        all_class_fqns: set[str],
    ) -> list[dict]:
        """Resolve self-attributed call targets against known class FQNs.

        Ported from tools/ast_parser.py _resolve_call_target + post-processing.
        """
        # Build short_name -> fqn map from the set of all class FQNs
        known: dict[str, str] = {}
        for fqn in all_class_fqns:
            short = fqn.rsplit(".", 1)[-1]
            known[short] = fqn

        for cs in call_sites:
            if cs.get("_self_attr") is not None:
                self._resolve_call_target(cs, known)

        for cs in call_sites:
            cs.pop("_self_attr", None)
            cs["confidence"] = (
                "high" if cs.get("resolved_target") is not None else "medium"
            )
            cs["resolution"] = (
                "exact" if cs.get("resolved_target") is not None else "unresolved"
            )
            cs["evidence"] = (
                "attr_tracking" if cs.get("resolved_target") is not None else ""
            )

        return call_sites

    @staticmethod
    def _resolve_call_target(cs: dict, known_class_fqns: dict[str, str]) -> None:
        attr_name = cs.get("_self_attr")
        if not attr_name:
            cs["resolved_target"] = None
            return

        raw_target = cs.get("resolved_target")
        if not raw_target:
            return

        parts = raw_target.rsplit(".", 1)
        if len(parts) != 2:
            cs["resolved_target"] = None
            return
        cls_simple, method = parts

        fqn = known_class_fqns.get(cls_simple)
        if fqn is not None:
            cs["resolved_target"] = fqn + "." + method
        else:
            cs["resolved_target"] = None
