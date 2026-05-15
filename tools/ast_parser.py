"""AST-based parser that extracts structured data from Python source files.

Produces a dict with modules, classes, methods, functions, imports,
compositions, and signals ready for Neo4j knowledge-graph generation.

V2 adds BodyAnalyzer for deep method-body analysis: call sites,
error handlers, raises, conditions, returns, with blocks,
attr assignments, and signal emits.
"""

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_project(base_dir: str | Path) -> dict:
    """Walk the project directories and return the full structured data dict."""
    base = Path(base_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"Not a directory: {base}")

    modules: list[dict] = []
    classes: list[dict] = []
    methods: list[dict] = []
    functions: list[dict] = []
    imports: list[dict] = []
    compositions: list[dict] = []
    signals: list[dict] = []

    # V2 new collections
    call_sites: list[dict] = []
    error_handlers: list[dict] = []
    raises: list[dict] = []
    conditions: list[dict] = []
    returns: list[dict] = []
    withs: list[dict] = []
    signal_emits: list[dict] = []
    attr_assignments: list[dict] = []

    # Collect all known project class FQNs for V2 resolution
    known_class_fqns: set[str] = set()

    # --- 1. Scan file tree ---------------------------------------------------
    for scan_dir in ("engine", "app", "tools", "tests"):
        dir_path = base / scan_dir
        if not dir_path.is_dir():
            continue
        for py_file in dir_path.rglob("*.py"):
            # Skip excluded directories
            if _is_excluded(py_file):
                continue
            rel = py_file.relative_to(base)
            mod_name = _module_name(rel)

            source = _read_file(py_file)
            if source is None:
                continue

            tree = _parse_source(source, py_file)
            if tree is None:
                continue

            line_count = source.count("\n") + 1
            file_path = str(rel).replace("\\", "/")
            modules.append({"name": mod_name, "path": file_path, "lines": line_count})

            # Build up context for this module (V1 + V2)
            _extract_module(
                tree, mod_name, file_path, classes, methods,
                functions, imports, compositions, signals,
                call_sites, error_handlers, raises, conditions,
                returns, withs, signal_emits, attr_assignments,
            )

    # --- 2. Second pass — resolve compositions against known class names -----
    # Build known FQNs for V2 resolution
    known_class_fqns.update(c["fqn"] for c in classes)

    # Filter compositions: keep only those matching a known project class
    all_simple_names: set[str] = set()
    all_simple_names.update(c["name"] for c in classes)

    resolved_compositions: list[dict] = []
    for comp in compositions:
        if comp["composes"] in all_simple_names:
            resolved_compositions.append(comp)

    # --- 3. V2 second pass — resolve call targets against known FQNs ---------
    for cs in call_sites:
        if cs["_self_attr"] is not None:
            _resolve_call_target(cs, known_class_fqns)

    # Strip internal _self_attr key and set confidence before returning
    for cs in call_sites:
        cs.pop("_self_attr", None)
        cs["confidence"] = "high" if cs.get("resolved_target") is not None else "medium"

    return {
        "modules": modules,
        "classes": classes,
        "methods": methods,
        "functions": functions,
        "imports": imports,
        "compositions": resolved_compositions,
        "signals": signals,
        # V2 fields
        "call_sites": call_sites,
        "error_handlers": error_handlers,
        "raises": raises,
        "conditions": conditions,
        "returns": returns,
        "withs": withs,
        "signal_emits": signal_emits,
        "attr_assignments": attr_assignments,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXCLUDED_DIRS = {"__pycache__", ".venv", ".git", "dist", "build", ".pytest_cache"}
_EXCLUDED_PATTERNS = (".egg-info",)
_PROJECT_PREFIXES = ("engine", "app", "tools", "tests", "config")


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & _EXCLUDED_DIRS:
        return True
    return any(pat in parts for pat in _EXCLUDED_PATTERNS)


def _module_name(rel_path: Path) -> str:
    return str(rel_path.with_suffix("")).replace("\\", "/").replace("/", ".")


def _read_file(filepath: Path) -> str | None:
    """Read file content, returning None on failure."""
    try:
        return filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        try:
            return filepath.read_text(encoding="latin-1")
        except (UnicodeDecodeError, PermissionError, OSError):
            return None


def _parse_source(source: str, filepath: Path) -> ast.Module | None:
    try:
        return ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return None


def _is_project_module(module_name: str) -> bool:
    return module_name.startswith(_PROJECT_PREFIXES)


# ---------------------------------------------------------------------------
# Extraction — single module
# ---------------------------------------------------------------------------

def _extract_module(
    tree: ast.Module,
    mod_name: str,
    file_path: str,
    classes: list,
    methods: list,
    functions: list,
    imports: list,
    compositions: list,
    signals: list,
    call_sites: list,
    error_handlers: list,
    raises: list,
    conditions: list,
    returns: list,
    withs: list,
    signal_emits: list,
    attr_assignments: list,
):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            _handle_import(node, mod_name, imports)
        elif isinstance(node, ast.ImportFrom):
            _handle_import_from(node, mod_name, imports)
        elif isinstance(node, ast.ClassDef):
            _handle_class(
                node, mod_name, file_path, classes, methods, compositions, signals,
                call_sites, error_handlers, raises, conditions,
                returns, withs, signal_emits, attr_assignments,
            )
        elif isinstance(node, ast.FunctionDef):
            fqn = f"{mod_name}.{node.name}"
            func = {
                "name": node.name,
                "fqn": fqn,
                "module": mod_name,
                "file_path": file_path,
                "end_line": node.end_lineno,
                "params": _extract_params(node.args),
                "line": node.lineno,
                "decorators": _decorator_names(node),
            }
            functions.append(func)

            # V2: body analysis for module-level functions
            _analyze_function_body(
                node, fqn, mod_name, {},
                call_sites, error_handlers, raises, conditions,
                returns, withs, signal_emits, attr_assignments,
            )


# ---------------------------------------------------------------------------
# Import handlers
# ---------------------------------------------------------------------------

def _handle_import(node: ast.Import, mod_name: str, imports: list):
    for alias in node.names:
        to_mod = alias.name
        if not _is_project_module(to_mod):
            continue
        name = alias.asname or to_mod
        imports.append({
            "from_module": mod_name,
            "to_module": to_mod,
            "what": name,
            "line": node.lineno,
        })


def _handle_import_from(node: ast.ImportFrom, mod_name: str, imports: list):
    base_mod = node.module or ""
    # Resolve relative imports
    if node.level > 0:
        parts = mod_name.split(".")
        if node.level > len(parts):
            return  # e.g. "from ....foo import bar" when module is only 2 parts deep
        # Remove `node.level` trailing parts, then append module if present
        resolved_parts = parts[:-node.level] if node.level else parts
        if base_mod:
            resolved_parts = resolved_parts + [base_mod] if resolved_parts else [base_mod]
        base_mod = ".".join(resolved_parts)
    if not _is_project_module(base_mod):
        return
    for alias in node.names:
        name = alias.asname or alias.name
        imports.append({
            "from_module": mod_name,
            "to_module": base_mod,
            "what": name,
            "line": node.lineno,
        })


# ---------------------------------------------------------------------------
# Class handler
# ---------------------------------------------------------------------------

def _handle_class(
    node: ast.ClassDef,
    mod_name: str,
    file_path: str,
    classes: list,
    methods: list,
    compositions: list,
    signals: list,
    call_sites: list,
    error_handlers: list,
    raises: list,
    conditions: list,
    returns: list,
    withs: list,
    signal_emits: list,
    attr_assignments: list,
):
    fqn = f"{mod_name}.{node.name}"
    bases = [_base_name(b) for b in node.bases]
    cls = {
        "name": node.name,
        "fqn": fqn,
        "module": mod_name,
        "bases": bases or ["object"],
        "line": node.lineno,
    }
    classes.append(cls)

    # V1: handle methods and signals (original logic unchanged)
    method_nodes: list[ast.FunctionDef] = []
    for body_node in node.body:
        if isinstance(body_node, ast.FunctionDef):
            _handle_method(body_node, mod_name, node.name, file_path, methods, compositions)
            method_nodes.append(body_node)
        elif isinstance(body_node, ast.Assign):
            _handle_signal(body_node, mod_name, node.name, signals)

    # --- V2: Phase A — build self-attr → type map from ALL methods ----------
    attr_map: dict[str, str] = {}
    for mnode in method_nodes:
        _phase_a_collect_attrs(mnode, attr_map)

    # --- V2: Phase B — deep body analysis for each method -------------------
    for mnode in method_nodes:
        owner_fqn = f"{fqn}.{mnode.name}"
        _analyze_function_body(
            mnode, owner_fqn, fqn, attr_map,
            call_sites, error_handlers, raises, conditions,
            returns, withs, signal_emits, attr_assignments,
        )


def _base_name(base_node: ast.expr) -> str:
    if isinstance(base_node, ast.Name):
        return base_node.id
    if isinstance(base_node, ast.Attribute):
        return base_node.attr
    if isinstance(base_node, ast.Subscript):
        # e.g. Generic[T] → "Generic"
        return _base_name(base_node.value)
    return "unknown"


# ---------------------------------------------------------------------------
# Method / Function helpers
# ---------------------------------------------------------------------------

def _handle_method(
    node: ast.FunctionDef,
    mod_name: str,
    class_name: str,
    file_path: str,
    methods: list,
    compositions: list,
):
    owner_fqn = f"{mod_name}.{class_name}"
    fqn = f"{owner_fqn}.{node.name}"
    method = {
        "name": node.name,
        "fqn": fqn,
        "owner_class": owner_fqn,
        "file_path": file_path,
        "end_line": node.end_lineno,
        "params": _extract_params(node.args),
        "decorators": _decorator_names(node),
        "line": node.lineno,
    }
    methods.append(method)

    # Composition detection — only in __init__
    if node.name == "__init__":
        _detect_composition(node, mod_name, class_name, compositions)


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


def _decorator_names(node: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.append(dec.attr)
        elif isinstance(dec, ast.Call):
            # e.g. @retry_api(max_retries=3)
            if isinstance(dec.func, ast.Name):
                names.append(dec.func.id)
            elif isinstance(dec.func, ast.Attribute):
                names.append(dec.func.attr)
    return names


# ---------------------------------------------------------------------------
# Composition detection
# ---------------------------------------------------------------------------

def _detect_composition(
    node: ast.FunctionDef,
    mod_name: str,
    class_name: str,
    compositions: list,
):
    for stmt in node.body:
        # Pattern: self.X = SomeClass(...)
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                comp = _match_self_assign(target, stmt.value)
                if comp:
                    compositions.append({
                        "class": f"{mod_name}.{class_name}",
                        "composes": comp,
                        "attr": _target_attr(target),
                        "line": stmt.lineno,
                    })
        # Pattern: self.X: SomeClass (AnnAssign with type hint)
        elif isinstance(stmt, ast.AnnAssign):
            comp = _match_self_ann_assign(stmt)
            if comp:
                compositions.append({
                    "class": f"{mod_name}.{class_name}",
                    "composes": comp,
                    "attr": _target_attr(stmt.target),
                    "line": stmt.lineno,
                })


def _match_self_assign(target: ast.expr, value: ast.expr) -> str | None:
    """If value is ``ClassName(...)`` and target is ``self.xxx``, return ClassName."""
    if not isinstance(value, ast.Call):
        return None
    if not _is_self_attr(target):
        return None
    if isinstance(value.func, ast.Name):
        return value.func.id
    if isinstance(value.func, ast.Attribute):
        return value.func.attr
    return None


def _match_self_ann_assign(stmt: ast.AnnAssign) -> str | None:
    """If annotation is a ClassName and target is ``self.xxx``, return ClassName."""
    if not _is_self_attr(stmt.target):
        return None
    ann = stmt.annotation
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    return None


def _is_self_attr(expr: ast.expr) -> bool:
    """Check if expr is ``self.something``."""
    return (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "self"
    )


def _target_attr(target: ast.expr) -> str:
    if isinstance(target, ast.Attribute):
        return target.attr
    return "?"


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------

_SIGNAL_NAMES = {"Signal", "pyqtSignal", "Slot", "pyqtSlot"}


def _handle_signal(
    node: ast.Assign,
    mod_name: str,
    class_name: str,
    signals: list,
):
    value = node.value
    if not isinstance(value, ast.Call):
        return

    # Determine if the call is a Signal() / pyqtSignal() variant
    signal_name = None
    if isinstance(value.func, ast.Name):
        if value.func.id in _SIGNAL_NAMES:
            signal_name = value.func.id
    elif isinstance(value.func, ast.Attribute):
        # QtCore.Signal, PySide6.QtCore.Signal, etc.
        if value.func.attr in _SIGNAL_NAMES:
            signal_name = value.func.attr

    if signal_name is None:
        return

    params = [_sig_param(a) for a in value.args]

    # Determine the attribute name (the left-hand side targets)
    for target in node.targets:
        if isinstance(target, ast.Name):
            signals.append({
                "class": f"{mod_name}.{class_name}",
                "name": target.id,
                "params": params,
                "line": node.lineno,
            })


def _sig_param(arg: ast.expr) -> str:
    """Convert a Signal argument to a string representation."""
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


# ===========================================================================
# V2: BodyAnalyzer — deep recursive method/function body analysis
# ===========================================================================

class BodyAnalyzer:
    """Recursively traverses method/function bodies to extract call-graph and
    structural data: call sites, error handlers, raises, conditions, returns,
    with blocks, attribute assignments, and signal emits.
    """

    # ------------------------------------------------------------------
    # Phase A: build self-attr → class-name map from all class methods
    # ------------------------------------------------------------------

    @staticmethod
    def phase_a_collect_attrs(method_node: ast.FunctionDef) -> dict[str, str]:
        """Scan a single method body for ``self.attr = ClassName()`` and
        ``self.attr: ClassName`` patterns.  Returns {attr_name: class_name}.
        """
        return _phase_a_collect_attrs(method_node)

    # ------------------------------------------------------------------
    # Phase B: analyze a single function/method body
    # ------------------------------------------------------------------

    @staticmethod
    def analyze(
        node: ast.FunctionDef,
        owner_fqn: str,
        owner_class_fqn: str,
        attr_map: dict[str, str],
        call_sites: list,
        error_handlers: list,
        raises: list,
        conditions: list,
        returns: list,
        withs: list,
        signal_emits: list,
        attr_assignments: list,
    ):
        """Run all V2 collectors against *node* body and append to lists."""
        _analyze_function_body(
            node, owner_fqn, owner_class_fqn, attr_map,
            call_sites, error_handlers, raises, conditions,
            returns, withs, signal_emits, attr_assignments,
        )


# ---------------------------------------------------------------------------
# V2 internal helpers
# ---------------------------------------------------------------------------

def _phase_a_collect_attrs(method_node: ast.FunctionDef, attr_map: dict[str, str]):
    """Scan *method_node* body for self.attr = ClassName() / self.attr: ClassName."""
    for child in ast.walk(method_node):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if _is_self_attr(target) and isinstance(child.value, ast.Call):
                    cls_name = _call_class_name(child.value)
                    if cls_name:
                        attr_map[target.attr] = cls_name
        elif isinstance(child, ast.AnnAssign):
            if _is_self_attr(child.target) and child.annotation is not None:
                cls_name = _annotation_class_name(child.annotation)
                if cls_name:
                    attr_map[child.target.attr] = cls_name


def _call_class_name(call_node: ast.Call) -> str | None:
    """Return the class name from a Call node like ``ClassName(...)``."""
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    if isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return None


def _annotation_class_name(ann: ast.expr) -> str | None:
    """Return the class name from an annotation like ``ClassName`` or ``mod.ClassName``."""
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Subscript):
        return _annotation_class_name(ann.value)
    return None


def _analyze_function_body(
    fn_node: ast.FunctionDef,
    owner_fqn: str,
    owner_class_fqn: str,
    attr_map: dict[str, str],
    call_sites: list,
    error_handlers: list,
    raises: list,
    conditions: list,
    returns: list,
    withs: list,
    signal_emits: list,
    attr_assignments: list,
):
    """Walk *fn_node* body and dispatch every relevant AST node to its collector."""
    for child in ast.walk(fn_node):
        if isinstance(child, ast.Call):
            _collect_call(child, owner_fqn, attr_map, call_sites, signal_emits)
        elif isinstance(child, ast.Try):
            _collect_try(child, owner_fqn, error_handlers)
        elif isinstance(child, ast.Raise):
            _collect_raise(child, owner_fqn, raises)
        elif isinstance(child, (ast.If, ast.While)):
            _collect_condition(child, owner_fqn, conditions)
        elif isinstance(child, ast.For):
            _collect_for(child, owner_fqn, conditions)
        elif isinstance(child, ast.Return):
            _collect_return(child, owner_fqn, returns)
        elif isinstance(child, ast.With):
            _collect_with(child, owner_fqn, withs)
        elif isinstance(child, ast.Assign):
            _collect_assign(child, owner_fqn, owner_class_fqn, attr_assignments)
        elif isinstance(child, ast.AnnAssign):
            _collect_ann_assign(child, owner_fqn, owner_class_fqn, attr_assignments)


# ---------------------------------------------------------------------------
# V2 individual collectors
# ---------------------------------------------------------------------------

def _collect_call(
    node: ast.Call,
    owner_fqn: str,
    attr_map: dict[str, str],
    call_sites: list,
    signal_emits: list,
):
    """Record one call site.  Also detect ``self.signal.emit(...)``."""
    call_expr = ast.unparse(node.func)

    # Detect self.X.method() or self.X.emit() patterns
    is_self_call = False
    resolved_target = None
    self_attr: str | None = None
    method_name: str | None = None

    if isinstance(node.func, ast.Attribute):
        method_name = node.func.attr

        # Case 1: self.method() directly
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
            is_self_call = True
            # self_attr stays None — no intermediate attribute to track

        # Case 2: self.attr.method() — nested attribute access
        elif _is_self_attr(node.func.value):
            is_self_call = True
            self_attr = node.func.value.attr

            # Signal emit: self.signal_name.emit(...)
            if method_name == "emit":
                signal_emits.append({
                    "owner_fqn": owner_fqn,
                    "signal_name": self_attr,
                    "args_count": len(node.args),
                    "line": node.lineno,
                })

            # Try resolution via attr_map (deferred to second pass for FQN expansion)
            if self_attr in attr_map:
                resolved_target = attr_map[self_attr] + "." + method_name

    call_sites.append({
        "caller_fqn": owner_fqn,
        "call_expr": call_expr,
        "resolved_target": resolved_target,
        "is_self_call": is_self_call,
        "line": node.lineno,
        "_self_attr": self_attr,  # temporary, used in second-pass resolution
    })


def _resolve_call_target(cs: dict, known_class_fqns: set[str]):
    """Second-pass: resolve ``_self_attr`` to a full FQN using known class names."""
    attr_name = cs.get("_self_attr")
    if not attr_name:
        cs["resolved_target"] = None
        return

    # attr_map resolution already produced "ClassName.method" — try to expand
    raw_target = cs["resolved_target"]
    if not raw_target:
        return

    # raw_target is "ClassName.method" — extract ClassName part
    parts = raw_target.rsplit(".", 1)
    if len(parts) != 2:
        cs["resolved_target"] = None
        return
    cls_simple, method = parts

    # Find matching known FQN
    for fqn in known_class_fqns:
        if fqn.endswith("." + cls_simple) or fqn == cls_simple:
            cs["resolved_target"] = fqn + "." + method
            return

    # No matching FQN — clear the preliminary resolution
    cs["resolved_target"] = None


def _collect_try(node: ast.Try, owner_fqn: str, error_handlers: list):
    """Record a try/except block."""
    exception_types: list[str] = []
    for handler in node.handlers:
        _extract_exception_names(handler.type, exception_types)

    if not exception_types:
        exception_types.append("Exception")  # bare except:

    error_handlers.append({
        "owner_fqn": owner_fqn,
        "exception_types": exception_types,
        "has_finally": bool(node.finalbody),
        "line": node.lineno,
    })


def _extract_exception_names(exc_node: ast.expr | None, into: list[str]):
    """Recursively extract exception class names from except handler type."""
    if exc_node is None:
        return
    if isinstance(exc_node, ast.Name):
        into.append(exc_node.id)
    elif isinstance(exc_node, ast.Tuple):
        for elt in exc_node.elts:
            _extract_exception_names(elt, into)
    elif isinstance(exc_node, ast.Attribute):
        into.append(exc_node.attr)


def _collect_raise(node: ast.Raise, owner_fqn: str, raises: list):
    """Record a raise statement."""
    exc_name = "Exception"
    if node.exc is not None:
        if isinstance(node.exc, ast.Call):
            exc_name = _call_class_name(node.exc) or "Exception"
        elif isinstance(node.exc, ast.Name):
            exc_name = node.exc.id
        elif isinstance(node.exc, ast.Attribute):
            exc_name = node.exc.attr

    raises.append({
        "owner_fqn": owner_fqn,
        "exception_name": exc_name,
        "line": node.lineno,
    })


def _collect_condition(node: ast.If | ast.While, owner_fqn: str, conditions: list):
    """Record an if/while condition."""
    cond_type = "if" if isinstance(node, ast.If) else "while"
    cond_expr = ast.unparse(node.test)

    conditions.append({
        "owner_fqn": owner_fqn,
        "condition": cond_expr,
        "type": cond_type,
        "line": node.lineno,
    })


def _collect_for(node: ast.For, owner_fqn: str, conditions: list):
    """Record a for-loop condition."""
    cond_expr = ast.unparse(node.iter)

    conditions.append({
        "owner_fqn": owner_fqn,
        "condition": cond_expr,
        "type": "for",
        "line": node.lineno,
    })


def _collect_return(node: ast.Return, owner_fqn: str, returns: list):
    """Record a return statement with its value type."""
    if node.value is None:
        returns.append({
            "owner_fqn": owner_fqn,
            "return_type": "None",
            "is_none": True,
            "line": node.lineno,
        })
    else:
        type_name = type(node.value).__name__
        is_none = isinstance(node.value, ast.Constant) and node.value.value is None
        returns.append({
            "owner_fqn": owner_fqn,
            "return_type": type_name,
            "is_none": is_none,
            "line": node.lineno,
        })


def _collect_with(node: ast.With, owner_fqn: str, withs: list):
    """Record a with-statement for each context manager."""
    for item in node.items:
        ctx_expr = ast.unparse(item.context_expr)
        withs.append({
            "owner_fqn": owner_fqn,
            "context_expr": ctx_expr,
            "line": node.lineno,
        })


def _collect_assign(
    node: ast.Assign,
    owner_fqn: str,
    owner_class_fqn: str,
    attr_assignments: list,
):
    """Record an assignment inside a method/function body."""
    assigned_type = _value_type_name(node.value)

    for target in node.targets:
        target_name = _target_attr_name(target)
        attr_assignments.append({
            "owner_class": owner_class_fqn,
            "attr": target_name,
            "assigned_type": assigned_type,
            "method_fqn": owner_fqn,
            "line": node.lineno,
        })


def _collect_ann_assign(
    node: ast.AnnAssign,
    owner_fqn: str,
    owner_class_fqn: str,
    attr_assignments: list,
):
    """Record an annotated assignment inside a method/function body."""
    assigned_type = _annotation_class_name(node.annotation) if node.annotation else None
    target_name = _target_attr_name(node.target)

    attr_assignments.append({
        "owner_class": owner_class_fqn,
        "attr": target_name,
        "assigned_type": assigned_type,
        "method_fqn": owner_fqn,
        "line": node.lineno,
    })


def _value_type_name(value: ast.expr) -> str | None:
    """Return a human-readable type/source name for an assignment value."""
    if isinstance(value, ast.Call):
        return _call_class_name(value)
    if isinstance(value, ast.Constant):
        return type(value.value).__name__
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return _unparse_safe(value)
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


def _target_attr_name(target: ast.expr) -> str:
    """Return the leaf attribute name for an assignment target.

    ``self.x`` → ``x``,  ``self.foo.bar`` → ``bar``,  ``x`` → ``x``.
    """
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Subscript):
        return _target_attr_name(target.value)
    try:
        return ast.unparse(target)
    except Exception:
        return "?"


def _unparse_safe(node: ast.expr) -> str:
    """Unparse an AST node, falling back to a simple representation."""
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{_unparse_safe(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{_unparse_safe(node.value)}[...]"
        return "?"


# ---------------------------------------------------------------------------
# Standalone entry point (for debugging / verification)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    project_root = Path(__file__).resolve().parents[1]
    data = parse_project(project_root)
    summary = {k: len(v) for k, v in data.items()}
    print(f"Parsed {project_root}")
    print(json.dumps(summary, indent=2))
    # Uncomment to dump full data:
    # print(json.dumps(data, indent=2, ensure_ascii=False))
