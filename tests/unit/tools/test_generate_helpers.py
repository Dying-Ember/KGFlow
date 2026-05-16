"""Tests for pure helpers in tools/generate_knowledge_graph.py.

Tests: _build_kg_run_id, _build_extractor_hash, check_coverage_thresholds.
"""

import re
from datetime import datetime, timezone

from tools.generate_knowledge_graph import (
    _build_kg_run_id,
    _build_extractor_hash,
    check_coverage_thresholds,
)

# ── check_coverage_thresholds ──────────────────────────────────────────


def test_ci_all_pass():
    """所有阈值达标 → 空 failure 列表。"""
    coverage = {"parse_errors": 0, "parse_error_files": [], "files_parsed_ok": 10, "functions_found": 5}
    assert check_coverage_thresholds(coverage) == []


def test_ci_parse_errors_fails():
    """parse_errors > 0 时应在 failure 列表中。"""
    coverage = {"parse_errors": 3, "parse_error_files": ["a.py", "b.py"], "files_parsed_ok": 7, "functions_found": 5}
    failures = check_coverage_thresholds(coverage)
    assert any("parse_errors=3" in f for f in failures)


def test_ci_zero_files_parsed():
    """files_parsed_ok=0 时应报错。"""
    coverage = {"parse_errors": 0, "parse_error_files": [], "files_parsed_ok": 0, "functions_found": 0}
    failures = check_coverage_thresholds(coverage)
    assert any("files_parsed_ok=0" in f for f in failures)


def test_ci_zero_functions():
    """functions_found=0 时应报错。"""
    coverage = {"parse_errors": 0, "parse_error_files": [], "files_parsed_ok": 5, "functions_found": 0}
    failures = check_coverage_thresholds(coverage)
    assert any("functions_found=0" in f for f in failures)


def test_ci_multiple_failures():
    """多个阈值不达标时返回多个 failure。"""
    coverage = {"parse_errors": 2, "parse_error_files": ["e.py"], "files_parsed_ok": 0, "functions_found": 0}
    failures = check_coverage_thresholds(coverage)
    assert len(failures) >= 3


def test_ci_parse_error_files_truncated():
    """parse_error_files 超过 5 个时只列出前 5 个。"""
    coverage = {"parse_errors": 10, "parse_error_files": [f"e{i}.py" for i in range(20)],
                "files_parsed_ok": 10, "functions_found": 5}
    failures = check_coverage_thresholds(coverage)
    parse_error_lines = [f for f in failures if "parse error in" in f]
    assert len(parse_error_lines) <= 5


# ── _build_kg_run_id ──────────────────────────────────────────────────


def test_kg_run_id_deterministic():
    """相同输入产生相同 12 字符 hex 输出。"""
    dt = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    id1 = _build_kg_run_id("abc123", dt, "hash1234")
    id2 = _build_kg_run_id("abc123", dt, "hash1234")
    assert id1 == id2


def test_kg_run_id_different_commit():
    """不同 commit 产生不同 run_id。"""
    dt = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    id1 = _build_kg_run_id("abc123", dt, "hash1234")
    id2 = _build_kg_run_id("def456", dt, "hash1234")
    assert id1 != id2


def test_kg_run_id_is_12_hex_chars():
    """run_id 是 12 位十六进制小写字符串。"""
    dt = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    run_id = _build_kg_run_id("abc123", dt, "hash1234")
    assert re.match(r"^[0-9a-f]{12}$", run_id)


# ── _build_extractor_hash ─────────────────────────────────────────────


def test_extractor_hash_deterministic():
    """相同环境产生相同 hash。"""
    assert _build_extractor_hash() == _build_extractor_hash()


def test_extractor_hash_is_8_hex_chars():
    """extractor_hash 是 8 位十六进制小写字符串。"""
    h = _build_extractor_hash()
    assert re.match(r"^[0-9a-f]{8}$", h)
