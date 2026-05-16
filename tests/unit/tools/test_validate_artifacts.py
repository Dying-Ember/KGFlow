"""Tests for tools/validate_artifacts.py — all validate_* pure functions."""

from tools.validate_artifacts import (
    validate_impact_report,
    validate_plan_tasks,
    validate_change_intent,
    validate_audit_report,
    validate_kg_diff,
    validate_overrides,
)


def _make_meta(kg_run_id="a1b2c3d4e5f6"):
    return {"meta": {"kg_run_id": kg_run_id}}


def _with_data(**data_kw):
    return {"schema_version": "1.0.0", **_make_meta(), "data": data_kw}


# ── validate_impact_report ────────────────────────────────────────────


def test_impact_report_valid():
    data = _with_data(**{"affected": {"methods": ["mod.Foo.bar"]}})
    assert validate_impact_report(data) == []


def test_impact_report_missing_kg_run_id():
    data = {"schema_version": "1.0.0", "meta": {}, "data": {"affected": {"methods": []}}}
    errors = validate_impact_report(data)
    assert any("kg_run_id" in e for e in errors)


def test_impact_report_empty_affected():
    data = {"schema_version": "1.0.0", **_make_meta(), "data": {}}
    errors = validate_impact_report(data)
    assert any("affected" in e for e in errors)


# ── validate_plan_tasks ───────────────────────────────────────────────


def test_plan_tasks_valid():
    data = _with_data(tasks=[{"task_id": "T1", "files": ["a.py"]}])
    assert validate_plan_tasks(data) == []


def test_plan_tasks_missing_tasks():
    data = _with_data()
    errors = validate_plan_tasks(data)
    assert any("tasks" in e for e in errors)


def test_plan_tasks_missing_task_id():
    data = _with_data(tasks=[{"files": ["a.py"]}])
    errors = validate_plan_tasks(data)
    assert any("task_id" in e for e in errors)


def test_plan_tasks_missing_files():
    data = _with_data(tasks=[{"task_id": "T1"}])
    errors = validate_plan_tasks(data)
    assert any("files" in e for e in errors)


# ── validate_change_intent ────────────────────────────────────────────


def test_change_intent_valid():
    data = _with_data(tasks=[{"task_id": "T1", "hard_rules": {"max_orphan_nodes": 0},
                              "soft_rules": {"unknown_edge_policy": "warn"}}])
    assert validate_change_intent(data) == []


def test_change_intent_no_rules():
    data = _with_data(tasks=[{"task_id": "T1"}])
    errors = validate_change_intent(data)
    assert any("hard_rules" in e or "soft_rules" in e for e in errors)


# ── validate_audit_report ──────────────────────────────────────────────


def test_audit_report_valid():
    data = _with_data(**{"result": "pass"})
    assert validate_audit_report(data) == []


def test_audit_report_invalid_result():
    data = _with_data(**{"result": "invalid"})
    errors = validate_audit_report(data)
    assert any("result" in e for e in errors)


# ── validate_kg_diff ──────────────────────────────────────────────────


def test_kg_diff_valid():
    data = {"schema_version": "1.0.0",
            "meta": {"from_run_id": "a1b2c3d4e5f6", "to_run_id": "f6e5d4c3b2a1"},
            "data": {"change_attribution": "code_only"}}
    assert validate_kg_diff(data) == []


def test_kg_diff_invalid_run_ids():
    data = {"schema_version": "1.0.0",
            "meta": {"from_run_id": "bad", "to_run_id": "also_bad"},
            "data": {"change_attribution": "code_only"}}
    errors = validate_kg_diff(data)
    assert len(errors) >= 1
    assert any("from_run_id" in e or "to_run_id" in e for e in errors)


def test_kg_diff_invalid_attribution():
    data = {"schema_version": "1.0.0",
            "meta": {"from_run_id": "a1b2c3d4e5f6", "to_run_id": "f6e5d4c3b2a1"},
            "data": {"change_attribution": "invalid"}}
    errors = validate_kg_diff(data)
    assert any("change_attribution" in e for e in errors)


# ── validate_overrides ────────────────────────────────────────────────


def test_overrides_valid():
    data = _with_data(overrides=[{
        "override_id": "OV-001", "reason": "safe",
        "approver": "lead", "created_at": "2026-01-01T00:00:00Z",
    }])
    assert validate_overrides(data) == []


def test_overrides_missing_keys():
    data = _with_data(overrides=[{"override_id": "OV-001"}])
    errors = validate_overrides(data)
    assert any("reason" in e for e in errors)
    assert any("approver" in e for e in errors)
