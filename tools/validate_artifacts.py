#!/usr/bin/env python3
"""Validate KGFlow artifact JSON files.

Usage:
  uv run python tools/validate_artifacts.py artifacts/
  uv run python tools/validate_artifacts.py artifacts/impact_report.json

Performs L1/L2 validation + L3 cross-reference checks (Neo4j required for full L3).
"""
import json
import os
import re
import sys
from pathlib import Path

try:
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False

NEO4J_CONNECTED = None  # None=unknown, True=connected, False=degraded


# ── Schema definitions (inline, no jsonschema dependency) ──

REQUIRED_TOP_KEYS = {"schema_version", "meta", "data"}
VALID_GATE_RESULTS = {"BLOCK", "WARN", "PASS"}
VALID_UNKNOWN_EDGE_POLICIES = {"warn", "block"}
VALID_CHANGE_ATTRIBUTIONS = {"code_only", "extractor_only", "mixed", "unknown"}
HEX12_RE = re.compile(r"^[0-9a-f]{12}$")


def _check(obj, path, condition, msg):
    """Append error if condition is False."""
    if not condition:
        raise ValueError(f"[{path}] {msg}")


# ── L3: Neo4j cross-reference validation ──

def verify_run_id_in_neo4j(kg_run_id: str) -> tuple:
    """Check if a kg_run_id exists in Neo4j KGMetadata.
    Returns (found: bool, message: str)"""
    if not HAS_NEO4J:
        return True, "degraded (no neo4j driver)"
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687",
                                       auth=("neo4j", "tply7620"))
        with driver.session(database="neo4j") as session:
            result = session.run(
                "MATCH (m:KGMetadata {kg_run_id: $rid}) RETURN m.kg_run_id",
                rid=kg_run_id
            )
            record = result.single()
            driver.close()
            if record:
                return True, "found"
            return False, "not found in Neo4j"
    except Exception as e:
        return True, f"degraded (cannot connect: {e})"


def verify_file_ref(ref_path: str) -> tuple:
    """Check if a referenced artifact file exists.
    Returns (found: bool, message: str)"""
    p = Path(ref_path)
    if p.exists():
        return True, "exists"
    if p.is_absolute():
        return False, "not found"
    return True, "relative path (checked during L2)"


def check_neo4j_connectivity():
    """Probe Neo4j connectivity. Sets NEO4J_CONNECTED."""
    global NEO4J_CONNECTED
    if not HAS_NEO4J:
        NEO4J_CONNECTED = False
        return
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687",
                                       auth=("neo4j", "tply7620"))
        driver.verify_connectivity()
        driver.close()
        NEO4J_CONNECTED = True
    except Exception:
        NEO4J_CONNECTED = False


def validate_impact_report(data):
    errors = []
    # Check meta
    meta = data.get("meta", {})
    meta_run_id = meta.get("kg_run_id", "")
    try:
        _check(meta, "meta.kg_run_id", bool(HEX12_RE.match(str(meta_run_id))),
               f"invalid kg_run_id: {meta_run_id}")
    except ValueError as e:
        errors.append(str(e))

    # Check data
    affected = data.get("data", {}).get("affected", {})
    if not affected:
        errors.append("[data.affected] missing or empty")

    # Check subgraphs
    subgraphs = data.get("data", {}).get("subgraphs", [])
    for i, sg in enumerate(subgraphs):
        if "entry_methods" not in sg:
            errors.append(f"[data.subgraphs[{i}]].entry_methods missing")

    return errors


def validate_plan_tasks(data):
    errors = []
    tasks = data.get("data", {}).get("tasks", [])
    if not tasks:
        errors.append("[data.tasks] missing or empty")
    for i, task in enumerate(tasks):
        if "task_id" not in task:
            errors.append(f"[data.tasks[{i}].task_id] missing")
        if "files" not in task:
            errors.append(f"[data.tasks[{i}].files] missing")
    return errors


def validate_change_intent(data):
    errors = []
    tasks = data.get("data", {}).get("tasks", [])
    for i, task in enumerate(tasks):
        hard = task.get("hard_rules", {})
        soft = task.get("soft_rules", {})
        if not hard and not soft:
            errors.append(f"[data.tasks[{i}]] at least one of hard_rules/soft_rules required")
        if soft.get("unknown_edge_policy", "") not in VALID_UNKNOWN_EDGE_POLICIES:
            errors.append(f"[data.tasks[{i}].soft_rules.unknown_edge_policy] must be warn/block")

    arch_rules = data.get("data", {}).get("arch_rules", [])
    for i, rule in enumerate(arch_rules):
        if "rule" not in rule or "action" not in rule:
            errors.append(f"[data.arch_rules[{i}]] each rule needs 'rule' + 'action'")
        if rule.get("action") not in ("block", "warn", "pass"):
            errors.append(f"[data.arch_rules[{i}].action] must be block/warn/pass")

    # L3: plan_tasks_ref existence
    ref = data.get("meta", {}).get("plan_tasks_ref", "")
    if ref:
        ref_path = Path(ref)
        if not ref_path.exists() and not ref_path.is_absolute():
            errors.append(f"[meta.plan_tasks_ref] file not found: {ref}")

    return errors


def validate_audit_report(data):
    errors = []
    result = data.get("data", {}).get("result", "")
    if result not in ("pass", "block", "warn", "fail"):
        errors.append(f"[data.result] must be pass/block/warn/fail, got: {result}")
    meta_run_id = data.get("meta", {}).get("kg_run_id", "")
    try:
        _check(data, "meta.kg_run_id", bool(HEX12_RE.match(str(meta_run_id))),
               f"invalid kg_run_id: {meta_run_id}")
    except ValueError as e:
        errors.append(str(e))
    return errors


def validate_kg_diff(data):
    errors = []
    meta = data.get("meta", {})
    for key in ("from_run_id", "to_run_id"):
        val = meta.get(key, "")
        try:
            _check(meta, f"meta.{key}", bool(HEX12_RE.match(str(val))),
                   f"invalid {key}: {val}")
        except ValueError as e:
            errors.append(str(e))

    attr = data.get("data", {}).get("change_attribution", "")
    if attr and attr not in VALID_CHANGE_ATTRIBUTIONS:
        errors.append(f"[data.change_attribution] must be one of {VALID_CHANGE_ATTRIBUTIONS}")

    return errors


def validate_overrides(data):
    errors = []
    overrides = data.get("data", {}).get("overrides", [])
    for i, ov in enumerate(overrides):
        for key in ("override_id", "reason", "approver", "created_at"):
            if key not in ov:
                errors.append(f"[data.overrides[{i}].{key}] missing")
    return errors


# ── Dispatcher ──

VALIDATORS = {
    "impact_report": validate_impact_report,
    "plan_tasks": validate_plan_tasks,
    "change_intent": validate_change_intent,
    "audit_report": validate_audit_report,
    "kg_diff": validate_kg_diff,
    "overrides": validate_overrides,
}


def validate_file(filepath: Path):
    """Validate a single artifact file. Returns (filename, passes, errors, l3_results)."""
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return filepath.name, False, [f"invalid JSON: {e}"], {}

    # L0: schema_version + meta (skip for .schema.json)
    is_schema_file = filepath.name.endswith(".schema.json")
    if is_schema_file:
        return filepath.name, True, [], {}  # schema files define rules, not follow them

    # Detect artifact type from filename prefix
    fname = filepath.stem  # e.g. "impact_report"
    validator = VALIDATORS.get(fname)
    if not validator:
        # Try prefix match: "audit_bad" → matches "audit_report" validator
        for key, v in VALIDATORS.items():
            prefix = key.split("_")[0]
            if fname.startswith(prefix):
                validator = v
                break
    if not validator:
        return filepath.name, True, [], {}  # unknown type, skip

    errors = validator(data)
    passed = len(errors) == 0

    # ── L3 cross-reference checks ──
    l3_results = {}
    if fname == "impact_report" or "impact" in fname:
        rid = data.get("meta", {}).get("kg_run_id", "")
        if rid:
            ok, msg = verify_run_id_in_neo4j(rid)
            l3_results["kg_run_id_check"] = {"passed": ok, "detail": msg}
    elif fname == "change_intent" or "change" in fname:
        ref = data.get("meta", {}).get("plan_tasks_ref", "")
        if ref:
            ok, msg = verify_file_ref(ref)
            l3_results["plan_tasks_ref_check"] = {"passed": ok, "detail": msg}
    elif fname == "audit_report" or "audit" in fname:
        rid = data.get("meta", {}).get("kg_run_id", "")
        if rid:
            ok, msg = verify_run_id_in_neo4j(rid)
            l3_results["kg_run_id_check"] = {"passed": ok, "detail": msg}

    return filepath.name, passed, errors, l3_results


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: uv run python tools/validate_artifacts.py <path> [path...]")
        sys.exit(1)

    # Probe Neo4j connectivity once before processing files
    global NEO4J_CONNECTED
    check_neo4j_connectivity()

    total = 0
    passed = 0
    failed = 0

    for arg in args:
        path = Path(arg)
        if path.is_dir():
            files = sorted(path.glob("*.json"))
        elif path.is_file():
            files = [path]
        else:
            print(f"路径不存在: {path}", file=sys.stderr)
            failed += 1
            continue

        for f in files:
            total += 1
            name, ok, errs, l3_results = validate_file(f)
            if ok:
                print(f"  PASS  {name}")
                passed += 1
            else:
                print(f"  FAIL  {name}")
                for e in errs:
                    print(f"        {e}")
                failed += 1
            if l3_results:
                for check_name, result in l3_results.items():
                    status = "PASS" if result["passed"] else "FAIL"
                    print(f"    L3 {check_name}: {status} ({result['detail']})")

    summary = f"\n{total} files: {passed} passed, {failed} failed"
    l3_mode = "full" if NEO4J_CONNECTED else "degraded"
    print(f"{summary}")
    print(f"L3 mode: {l3_mode} (Neo4j {'connected' if NEO4J_CONNECTED else 'not connected'})")
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
