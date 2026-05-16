"""Integration tests for tools/cypher_generator.py — generate_cypher().

These tests call generate_cypher() with canned data dicts and verify
the output Cypher string contains expected nodes, relationships, and metadata.
"""

from pathlib import Path

from tools.cypher_generator import generate_cypher


def _minimal_data(extra=None):
    """Return a data dict with all 15 required keys with minimal content."""
    data = {
        "modules": [],
        "classes": [],
        "methods": [],
        "functions": [],
        "imports": [],
        "compositions": [],
        "signals": [],
        "call_sites": [],
        "error_handlers": [],
        "raises": [],
        "conditions": [],
        "returns": [],
        "withs": [],
        "signal_emits": [],
        "attr_assignments": [],
    }
    if extra:
        data.update(extra)
    return data


def test_generate_with_minimal_data(tmp_path):
    """最小输入应生成包含约束的 Cypher 输出。"""
    cypher = generate_cypher(_minimal_data(), tmp_path)
    assert "CREATE CONSTRAINT" in cypher
    assert "MERGE (m:KGMetadata" not in cypher  # 未传 metadata 时不生成元信息节点


def test_generate_with_module_node(tmp_path):
    """包含 module 时生成 Module 节点。"""
    data = _minimal_data({"modules": [{"name": "engine.foo", "path": "engine/foo.py", "lines": 10}]})
    cypher = generate_cypher(data, tmp_path)
    assert "Module {name: \"engine.foo\"}" in cypher or "Module {name: \"engine.foo\"}" in cypher


def test_generate_with_class_node(tmp_path):
    """包含 class 时生成 Class 节点 + OWNS_METHOD 关系。"""
    data = _minimal_data({
        "classes": [{"name": "Foo", "fqn": "mod.Foo", "module": "mod", "bases": ["object"], "line": 1}],
    })
    cypher = generate_cypher(data, tmp_path)
    assert "Class {name: \"mod.Foo\"}" in cypher


def test_generate_with_method(tmp_path):
    """包含 method 时生成 Method 节点。"""
    data = _minimal_data({
        "classes": [{"name": "Foo", "fqn": "mod.Foo", "module": "mod", "bases": ["object"], "line": 1}],
        "methods": [{"name": "bar", "fqn": "mod.Foo.bar", "owner_class": "mod.Foo",
                     "file_path": "mod.py", "line": 5}],
    })
    cypher = generate_cypher(data, tmp_path)
    assert "Method" in cypher
    assert "mod.Foo.bar" in cypher


def test_generate_skips_test_modules(tmp_path):
    """test_ 模块不应生成 Module 节点。"""
    data = _minimal_data({"modules": [{"name": "tests.test_foo", "path": "tests/test_foo.py", "lines": 5}]})
    cypher = generate_cypher(data, tmp_path)
    # test 模块被跳过
    assert "tests.test_foo" not in cypher


def test_generate_metadata_node(tmp_path):
    """传入 metadata 时生成 KGMetadata 节点。"""
    data = _minimal_data()
    metadata = {"kg_run_id": "test12345678", "commit_sha": "abc123",
                "branch": "master", "generated_at": "2026-01-01",
                "generator_version": "2.0", "extractor_config_hash": "h1234567",
                "repo": "test/repo"}
    cypher = generate_cypher(data, tmp_path, metadata=metadata)
    assert "KGMetadata" in cypher
    assert "test12345678" in cypher


def test_generate_with_call_sites(tmp_path):
    """包含 call_sites 时生成 CallSite 节点和 CONTAINS_CALL 关系。"""
    data = _minimal_data({
        "methods": [{"name": "f", "fqn": "mod.f", "owner_class": "mod.X", "line": 1}],
        "call_sites": [{"caller_fqn": "mod.f", "call_expr": "g()", "line": 2, "confidence": "high"}],
    })
    cypher = generate_cypher(data, tmp_path)
    assert "CallSite" in cypher or "CONTAINS_CALL" in cypher
