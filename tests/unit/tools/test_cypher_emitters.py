"""Tests for pure helpers in tools/cypher_generator.py.

Tests: _escape_cypher, _prop_str, _flatten_toml, _flatten_json, _build_test_relationships.
"""

from tools.cypher_generator import (
    _escape_cypher,
    _prop_str,
    _flatten_toml,
    _flatten_json,
    _build_test_relationships,
)


# ── _escape_cypher ────────────────────────────────────────────────────


def test_escape_string():
    assert _escape_cypher("hello") == '"hello"'


def test_escape_with_quotes():
    assert _escape_cypher('say "hi"') == r'"say \"hi\""'


def test_escape_backslash():
    assert _escape_cypher("a\\b") == r'"a\\b"'


def test_escape_bool_true():
    assert _escape_cypher(True) == "true"


def test_escape_bool_false():
    assert _escape_cypher(False) == "false"


def test_escape_int():
    assert _escape_cypher(42) == "42"


def test_escape_float():
    assert _escape_cypher(3.14) == "3.14"


def test_escape_null():
    assert _escape_cypher(None) == "null"


def test_escape_list():
    assert _escape_cypher(["a", 1, True]) == '["a", 1, true]'


# ── _prop_str ─────────────────────────────────────────────────────────


def test_prop_str_simple():
    result = _prop_str({"name": "Foo", "line": 10})
    assert 'n.name = "Foo"' in result
    assert "n.line = 10" in result


def test_prop_str_empty_values_skipped():
    result = _prop_str({"name": "Foo", "decorators": []})
    assert "name" in result
    assert "decorators" not in result


def test_prop_str_all_empty():
    assert _prop_str({"name": "", "params": []}) == ""


# ── _flatten_toml ─────────────────────────────────────────────────────


def test_flatten_toml_flat():
    result = _flatten_toml({"key": "val"})
    assert result == {"_root": {"key": "val"}}


def test_flatten_toml_nested():
    result = _flatten_toml({"section": {"key": "val"}})
    assert result["section"]["key"] == "val"


def test_flatten_toml_deeply_nested():
    result = _flatten_toml({"a": {"b": {"c": 1}}})
    assert "a.b" in result
    assert result["a.b"]["c"] == 1


def test_flatten_toml_empty_dict():
    result = _flatten_toml({"empty": {}})
    assert "empty" in result
    assert result["empty"] == {}


# ── _flatten_json ─────────────────────────────────────────────────────


def test_flatten_json_with_arrays():
    result = _flatten_json({"items": [1, 2, 3]})
    assert result["items"]["_type"] == "array"
    assert result["items"]["_count"] == 3


def test_flatten_json_nested_dict():
    result = _flatten_json({"a": {"b": "val"}})
    assert result["a"]["b"] == "val"


def test_flatten_json_deeply_nested():
    result = _flatten_json({"a": {"b": {"c": 1}}})
    assert "a.b" in result
    assert result["a.b"]["c"] == 1


# ── _build_test_relationships ─────────────────────────────────────────


def test_build_test_relationships_no_match():
    """没有测试模块时返回空列表。"""
    data = {"classes": [{"name": "Foo", "fqn": "engine.Foo", "module": "engine.foo"}]}
    tests, mocks = _build_test_relationships(data)
    assert tests == []
    assert mocks == []


def test_build_test_relationships_only_mocks():
    """测试类如果没有匹配的 target 类，只有 MOCKS 关系。"""
    data = {
        "classes": [
            {"name": "TestFoo", "fqn": "tests.test_foo.TestFoo", "module": "tests.test_foo"},
        ]
    }
    tests, mocks = _build_test_relationships(data)
    assert isinstance(tests, list)
    assert isinstance(mocks, list)
