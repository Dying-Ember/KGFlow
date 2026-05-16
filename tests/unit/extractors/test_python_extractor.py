"""Tests for extractors/python_extractor.py — extract_file().

extract_file(source: str, file_path: str, mod_name: str) -> OneFileResult
is a pure function — no mocking needed, just write Python source strings.
"""

from pathlib import Path

from extractors.python_extractor import PythonAstExtractor


def _make_extractor():
    """Return a PythonAstExtractor with the test project root."""
    return PythonAstExtractor(Path("/tmp/test_project"))


def _extract(source, mod_name="test_mod", file_path="test_mod.py"):
    ex = _make_extractor()
    return ex.extract_file(source, file_path, mod_name)


# ── Module ────────────────────────────────────────────────────────────


def test_single_function():
    result = _extract("def foo():\n    return 42\n")
    assert len(result.functions) == 1
    assert result.functions[0]["name"] == "foo"
    assert result.functions[0]["fqn"] == "test_mod.foo"


def test_function_with_params():
    source = "def bar(a, b=1, *args, **kw): pass\n"
    result = _extract(source, mod_name="mod")
    assert len(result.functions) == 1
    params = result.functions[0]["params"]
    assert "a" in params
    assert "b" in params
    assert "*args" in params
    assert "**kw" in params


def test_function_with_decorator():
    source = "@staticmethod\ndef f(): pass\n"
    result = _extract(source)
    assert result.functions[0]["decorators"] == ["staticmethod"]


# ── Class ─────────────────────────────────────────────────────────────


def test_empty_class():
    source = "class Foo:\n    pass\n"
    result = _extract(source)
    assert len(result.classes) == 1
    assert result.classes[0]["name"] == "Foo"
    assert result.classes[0]["fqn"] == "test_mod.Foo"


def test_class_with_inheritance():
    source = "class Bar(Foo):\n    pass\n"
    result = _extract(source)
    assert "Foo" in result.classes[0]["bases"]


def test_class_with_multiple_bases():
    source = "class C(A, B):\n    pass\n"
    result = _extract(source)
    assert "A" in result.classes[0]["bases"]
    assert "B" in result.classes[0]["bases"]


# ── Method ────────────────────────────────────────────────────────────


def test_method():
    source = "class X:\n    def m(self): pass\n"
    result = _extract(source)
    assert len(result.methods) == 1
    assert result.methods[0]["name"] == "m"
    assert result.methods[0]["owner_class"] == "test_mod.X"
    assert result.methods[0]["fqn"] == "test_mod.X.m"


# ── Import ────────────────────────────────────────────────────────────


def test_import_absolute():
    source = "import engine.foo\n"
    result = _extract(source, mod_name="test_mod")
    imports = [i for i in result.imports if i["to_module"] == "engine.foo"]
    assert len(imports) >= 1


def test_non_project_import_skipped():
    source = "import os\nimport sys\n"
    result = _extract(source)
    # os 和 sys 不是项目模块，不应出现在 imports
    for imp in result.imports:
        assert not imp["to_module"].startswith(("os", "sys"))


# ── Composition ────────────────────────────────────────────────────────


def test_composition_self_assign():
    source = "class A:\n    def __init__(self):\n        self.b = B()\n"
    result = _extract(source)
    comps = [c for c in result.compositions if c["attr"] == "b"]
    assert len(comps) >= 1
    assert comps[0]["composes"] == "B"


# ── CallSite ───────────────────────────────────────────────────────────


def test_call_site_self_call():
    source = "class X:\n    def m(self):\n        self.helper()\n"
    result = _extract(source)
    calls = [c for c in result.call_sites if c["caller_fqn"] == "test_mod.X.m"]
    assert len(calls) >= 1
    assert calls[0]["is_self_call"] is True


def test_call_site_external_call():
    source = "def f():\n    other.func()\n"
    result = _extract(source)
    calls = [c for c in result.call_sites if c["caller_fqn"] == "test_mod.f"]
    assert len(calls) >= 1
    assert calls[0]["is_self_call"] is False


# ── ErrorHandler ──────────────────────────────────────────────────────


def test_try_except():
    source = "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n"
    result = _extract(source)
    handlers = [h for h in result.error_handlers if "ValueError" in h["exception_types"]]
    assert len(handlers) >= 1


def test_bare_except():
    source = "def f():\n    try:\n        pass\n    except:\n        pass\n"
    result = _extract(source)
    handlers = [h for h in result.error_handlers if "Exception" in h["exception_types"]]
    assert len(handlers) >= 1


def test_try_finally():
    source = "def f():\n    try:\n        pass\n    finally:\n        pass\n"
    result = _extract(source)
    handlers = [h for h in result.error_handlers if h.get("has_finally")]
    assert len(handlers) >= 1


# ── Raise ──────────────────────────────────────────────────────────────


def test_raise_exception():
    source = "def f():\n    raise RuntimeError('oops')\n"
    result = _extract(source)
    raises = [r for r in result.raises if r["owner_fqn"] == "test_mod.f"]
    assert len(raises) >= 1
    assert "RuntimeError" in raises[0]["exception_name"]


# ── Condition ──────────────────────────────────────────────────────────


def test_if_condition():
    source = "def f():\n    if x > 0:\n        pass\n"
    result = _extract(source)
    conds = [c for c in result.conditions if c["owner_fqn"] == "test_mod.f" and c["type"] == "if"]
    assert len(conds) >= 1


def test_while_condition():
    source = "def f():\n    while True:\n        pass\n"
    result = _extract(source)
    conds = [c for c in result.conditions if c["owner_fqn"] == "test_mod.f" and c["type"] == "while"]
    assert len(conds) >= 1


def test_for_condition():
    source = "def f():\n    for i in items:\n        pass\n"
    result = _extract(source)
    conds = [c for c in result.conditions if c["owner_fqn"] == "test_mod.f" and c["type"] == "for"]
    assert len(conds) >= 1


# ── Return ─────────────────────────────────────────────────────────────


def test_return_value():
    source = "def f():\n    return 42\n"
    result = _extract(source)
    returns = [r for r in result.returns if r["owner_fqn"] == "test_mod.f"]
    assert len(returns) >= 1
    assert returns[0]["is_none"] is False


def test_return_none():
    source = "def f():\n    return\n"
    result = _extract(source)
    returns = [r for r in result.returns if r["owner_fqn"] == "test_mod.f"]
    assert len(returns) >= 1
    assert returns[0]["is_none"] is True


# ── With ───────────────────────────────────────────────────────────────


def test_with_statement():
    source = "def f():\n    with open('f') as fd:\n        pass\n"
    result = _extract(source)
    withs = [w for w in result.withs if w["owner_fqn"] == "test_mod.f"]
    assert len(withs) >= 1
    assert "open" in withs[0]["context_expr"]


# ── AttrAssignment ─────────────────────────────────────────────────────


def test_attr_assignment():
    source = "class X:\n    def m(self):\n        self.x = 1\n"
    result = _extract(source)
    attrs = [a for a in result.attr_assignments if a["attr"] == "x"]
    assert len(attrs) >= 1
