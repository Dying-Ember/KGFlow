"""Tests for pure functions in tools/diff_kg.py.

Tests: Cypher parsers, node/edge identity, compute_diff, compute_change_attribution.
"""

from tools.diff_kg import (
    _parse_single_value,
    _parse_array_elements,
    _parse_props_string,
    _split_statements,
    _parse_node,
    _parse_edge,
    _node_identity,
    _edge_identity,
    compute_diff,
    compute_change_attribution,
)


# ── _parse_single_value ───────────────────────────────────────────────


def test_parse_single_value_string():
    assert _parse_single_value('"hello"') == "hello"


def test_parse_single_value_int():
    assert _parse_single_value("42") == 42


def test_parse_single_value_bool_true():
    assert _parse_single_value("true") is True


def test_parse_single_value_bool_false():
    assert _parse_single_value("false") is False


def test_parse_single_value_null():
    assert _parse_single_value("null") is None


def test_parse_single_value_float():
    assert _parse_single_value("3.14") == 3.14


def test_parse_single_value_escaped_string():
    assert _parse_single_value(r'"say \"hi\""') == 'say "hi"'


# ── _parse_array_elements ─────────────────────────────────────────────


def test_parse_array_elements_mixed():
    result = _parse_array_elements('"a", 1, true, null')
    assert result == ["a", 1, True, None]


# ── _parse_props_string ───────────────────────────────────────────────


def test_parse_props_string():
    result = _parse_props_string('name: "Foo", line: 10')
    assert result == {"name": "Foo", "line": 10}


def test_parse_props_string_multiline():
    result = _parse_props_string('name: "Foo"\nline: 10')
    assert result.get("name") == "Foo"
    assert result.get("line") == 10


# ── _split_statements ─────────────────────────────────────────────────


def test_split_statements():
    text = 'MERGE (n:Module {name: "a"});\nMERGE (n:Module {name: "b"});\n'
    stmts = _split_statements(text)
    assert len(stmts) == 2
    assert all(s.endswith(";") for s in stmts)


def test_split_statements_multiline():
    text = 'MERGE (n:Module {name: "a"})\nSET n.line = 10;\n'
    stmts = _split_statements(text)
    assert len(stmts) == 1


# ── _parse_node ───────────────────────────────────────────────────────


def test_parse_node():
    """_parse_node 解析 Cypher MERGE+SET 语句。"""
    stmt = (
        'MERGE (n:Module {name: "foo"})\n'
        'SET\n'
        'n.path = "/foo"\n'
    ) + ";\n"
    result = _parse_node(stmt)
    assert result is not None
    label, merge_props, all_props = result
    assert label == "Module"
    assert merge_props == {"name": "foo"}
    assert all_props.get("path") == "/foo"


# ── _parse_edge (approximate) ─────────────────────────────────────────


def test_parse_edge():
    stmt = (
        'MATCH (a:Module {name: "A"}) '
        'MATCH (b:Module {name: "B"}) '
        'MERGE (a)-[:IMPORTS]->(b);'
    )
    result = _parse_edge(stmt)
    assert result is not None
    assert result["from_label"] == "Module"
    assert result["to_label"] == "Module"
    assert result["rel_type"] == "IMPORTS"
    assert result["from_props"]["name"] == "A"
    assert result["to_props"]["name"] == "B"


# ── _node_identity / _edge_identity ───────────────────────────────────


def test_node_identity():
    identity = _node_identity("Module", {"name": "foo"})
    assert "Module" in identity
    assert "name=foo" in identity


def test_edge_identity():
    edge = {
        "from_label": "Module", "from_props": {"name": "A"},
        "rel_type": "IMPORTS",
        "to_label": "Module", "to_props": {"name": "B"},
    }
    identity = _edge_identity(edge)
    assert identity != ""


# ── compute_diff ─────────────────────────────────────────────────────


def test_compute_diff_added_nodes():
    to_nodes = {"Module::name=foo": {"label": "Module", "merge_props": {"name": "foo"}, "all_props": {"name": "foo"}}}
    diff = compute_diff({}, {}, to_nodes, {})
    assert diff["summary"]["nodes_added"] == 1
    assert diff["summary"]["nodes_removed"] == 0


def test_compute_diff_removed_nodes():
    from_nodes = {"Module::name=foo": {"label": "Module", "merge_props": {"name": "foo"}, "all_props": {"name": "foo"}}}
    diff = compute_diff(from_nodes, {}, {}, {})
    assert diff["summary"]["nodes_removed"] == 1
    assert diff["summary"]["nodes_added"] == 0


def test_compute_diff_added_edges():
    from_edges = {}
    to_edges = {
        "Module::name=A::IMPORTS::Module::name=B": {
            "from_label": "Module", "from_props": {"name": "A"},
            "rel_type": "IMPORTS",
            "to_label": "Module", "to_props": {"name": "B"},
        }
    }
    diff = compute_diff({}, {}, from_edges, to_edges)
    assert diff["summary"]["edges_added"] == 1


def test_compute_diff_unchanged():
    nodes = {"Module::name=foo": {"label": "Module", "merge_props": {"name": "foo"}, "all_props": {"name": "foo"}}}
    diff = compute_diff(nodes, {}, nodes, {})
    assert diff["summary"]["nodes_added"] == 0
    assert diff["summary"]["nodes_removed"] == 0


# ── compute_change_attribution ────────────────────────────────────


def test_change_attribution_code_only():
    from_meta = {"generator_version": "1.0", "extractor_config_hash": "abc"}
    to_meta = {"generator_version": "1.0", "extractor_config_hash": "abc"}
    assert compute_change_attribution(from_meta, to_meta) == "code_only"


def test_change_attribution_extractor_only():
    from_meta = {"generator_version": "1.0", "extractor_config_hash": "abc"}
    to_meta = {"generator_version": "2.0", "extractor_config_hash": "abc"}
    assert compute_change_attribution(from_meta, to_meta) == "extractor_only"


def test_change_attribution_unknown():
    from_meta = {"generator_version": "1.0", "extractor_config_hash": "abc"}
    to_meta = {"generator_version": "1.0", "extractor_config_hash": "def"}
    assert compute_change_attribution(from_meta, to_meta) == "unknown"


def test_change_attribution_missing_keys():
    assert compute_change_attribution({}, {}) == "code_only"
