"""Tests for extractors/base.py — BaseExtractor and OneFileResult.

Uses FakeExtractor to test the shared pipeline without real parsing.
"""

from pathlib import Path

from extractors.base import BaseExtractor, OneFileResult


class FakeExtractor(BaseExtractor):
    """Concrete subclass for testing the BaseExtractor pipeline."""

    def __init__(self, project_root, file_results=None):
        super().__init__(project_root, language="fake")
        self.file_suffixes = {".fake"}
        self._file_results = file_results or {}
        self._walk_return = None

    def extract_file(self, source, file_path, mod_name):
        return self._file_results.get(file_path, OneFileResult())


# ── _is_excluded ──────────────────────────────────────────────────────

def _make_extractor(tmp_path):
    return FakeExtractor(tmp_path)


def test_is_excluded_venv(tmp_path):
    ex = _make_extractor(tmp_path)
    assert ex._is_excluded(tmp_path / ".venv" / "lib" / "site-packages" / "foo.py")


def test_is_excluded_pycache(tmp_path):
    ex = _make_extractor(tmp_path)
    assert ex._is_excluded(tmp_path / "__pycache__" / "foo.py")


def test_is_excluded_normal_path(tmp_path):
    ex = _make_extractor(tmp_path)
    assert not ex._is_excluded(tmp_path / "engine" / "foo.py")


def test_is_excluded_init_file(tmp_path):
    ex = _make_extractor(tmp_path)
    assert ex._is_excluded(tmp_path / "engine" / "__init__.py")


def test_is_excluded_setup_file(tmp_path):
    ex = _make_extractor(tmp_path)
    assert ex._is_excluded(tmp_path / "setup.py")


# ── _compute_module_name ──────────────────────────────────────────────


def test_compute_module_name_python():
    """虽然 FakeExtractor 使用 .fake 后缀，但 `_compute_module_name` 逻辑一致。"""
    ex = FakeExtractor(Path("/tmp"))
    # 模拟一个 .fake 文件
    ex.file_suffixes = {".fake"}
    name = ex._compute_module_name("engine/foo.fake")
    assert name == "engine.foo"


def test_compute_module_name_windows_path():
    ex = FakeExtractor(Path("/tmp"))
    ex.file_suffixes = {".py"}
    name = ex._compute_module_name("engine\\foo.py")
    assert name == "engine.foo"


# ── _relative_path ────────────────────────────────────────────────────


def test_relative_path(tmp_path):
    ex = FakeExtractor(tmp_path)
    file_path = tmp_path / "engine" / "foo.fake"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("")
    rel = ex._relative_path(file_path)
    assert rel == "engine/foo.fake"
    assert "\\" not in rel


# ── _filter_compositions ──────────────────────────────────────────────


def test_filter_compositions_match():
    ex = FakeExtractor(Path("/tmp"))
    comps = [{"class": "mod.A", "composes": "B", "attr": "b"}]
    all_classes = {"B"}
    result = ex._filter_compositions(comps, all_classes)
    assert result == comps


def test_filter_compositions_no_match():
    ex = FakeExtractor(Path("/tmp"))
    comps = [{"class": "mod.A", "composes": "B", "attr": "b"}]
    result = ex._filter_compositions(comps, set())
    assert result == []


# ── _resolve_calls ────────────────────────────────────────────────────


def test_resolve_calls_exact():
    ex = FakeExtractor(Path("/tmp"))
    calls = [{"caller_fqn": "mod.f", "call_expr": "g()", "line": 1,
              "resolved_target": "mod.A.method", "is_self_call": False}]
    methods = [{"fqn": "mod.A.method"}]
    resolved = ex._resolve_calls(calls, methods, {"mod.A"})
    assert resolved[0]["confidence"] == "high"
    assert resolved[0]["resolution"] == "exact"


def test_resolve_calls_heuristic():
    ex = FakeExtractor(Path("/tmp"))
    calls = [{"caller_fqn": "mod.f", "call_expr": "g()", "line": 1,
              "resolved_target": "mod.A.method", "is_self_call": False}]
    resolved = ex._resolve_calls(calls, [], {"mod.A"})
    assert resolved[0]["resolution"] == "heuristic"


def test_resolve_calls_unresolved():
    ex = FakeExtractor(Path("/tmp"))
    calls = [{"caller_fqn": "mod.f", "call_expr": "g()", "line": 1,
              "resolved_target": None, "is_self_call": False}]
    resolved = ex._resolve_calls(calls, [], set())
    assert resolved[0]["confidence"] == "low"
    assert resolved[0]["resolution"] == "unresolved"


# ── OneFileResult ─────────────────────────────────────────────────────


def test_one_file_result_defaults():
    r = OneFileResult()
    assert r.modules == []
    assert r.classes == []
    assert r.methods == []
    assert r.functions == []
    assert r.imports == []
    assert r.compositions == []
    assert r.signals == []
    assert r.call_sites == []
    assert r.error_handlers == []
    assert r.raises == []
    assert r.conditions == []
    assert r.returns == []
    assert r.withs == []
    assert r.signal_emits == []
    assert r.attr_assignments == []
    assert r.errors == []


# ── extract() pipeline ────────────────────────────────────────────────


def test_extract_basic_pipeline(tmp_path):
    """extract() 返回 dict 包含 schema_version, language, data, coverage。"""
    (tmp_path / "mod.fake").write_text("")
    ex = FakeExtractor(tmp_path, file_results={
        "mod.fake": OneFileResult(),
    })
    result = ex.extract()
    assert result["schema_version"] == "1.0.0"
    assert result["language"] == "fake"
    assert "data" in result
    assert "coverage" in result


def test_extract_coverage_counts(tmp_path):
    """extract() 正确统计 files_scanned / parsed_ok / errors。"""
    (tmp_path / "ok.fake").write_text("")
    (tmp_path / "err.fake").write_text("")

    ok_result = OneFileResult()
    err_result = OneFileResult()
    err_result.errors.append("syntax error")

    ex = FakeExtractor(tmp_path, file_results={
        "ok.fake": ok_result,
        "err.fake": err_result,
    })
    result = ex.extract()
    cov = result["coverage"]
    assert cov["files_scanned"] == 2
    assert cov["files_parsed_ok"] == 1
    assert cov["parse_errors"] == 1


def test_walk_project_skips_excluded(tmp_path):
    """_walk_project 跳过 .venv 内文件。"""
    (tmp_path / "engine" / "main.fake").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "engine" / "main.fake").write_text("")
    (tmp_path / ".venv" / "lib" / "pkg.fake").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".venv" / "lib" / "pkg.fake").write_text("")

    ex = FakeExtractor(tmp_path)
    walked = list(ex._walk_project())
    rel_paths = [ex._relative_path(p) for p in walked]
    assert any("engine/main.fake" in r for r in rel_paths)
    assert not any(".venv" in r for r in rel_paths)
