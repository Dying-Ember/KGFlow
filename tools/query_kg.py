#!/usr/bin/env python3
"""CLI tool for querying the Neo4j knowledge graph for KG-assisted development.

Subcommands:
  resolve-changes  Map git diff file changes to KG Method nodes
  check-parallel   Gate 2 parallel safety check
  impact           Find everything affected by changing methods
  call-chain       Trace call chain up/down

Security: No bare Cypher input accepted. All queries use fixed templates with
parameterized injection. Driver configured with read-only sessions.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from neo4j import GraphDatabase, READ_ACCESS
except ImportError:
    print("需要安装 neo4j driver: uv add neo4j", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "tply7620"
_DEFAULT_TIMEOUT = 10  # seconds
_DEFAULT_ROW_LIMIT = 500

# Runtime overrides (set by CLI --timeout-ms)
TIMEOUT_SEC = _DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Neo4j query helper
# ---------------------------------------------------------------------------

class QueryKG:
    """Read-only Neo4j query runner with timeout and row limit."""

    def __init__(self, uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def _run(self, query, params=None, timeout=None,
             limit=None):
        if timeout is None:
            timeout = TIMEOUT_SEC
        if limit is None:
            limit = _DEFAULT_ROW_LIMIT
        params = params or {}
        if "LIMIT" not in query.upper():
            query = query.rstrip().rstrip(";") + f" LIMIT {limit}"
        with self.driver.session(database="neo4j",
                                 default_access_mode=READ_ACCESS) as session:
            result = session.run(query, params, timeout=timeout)
            return [dict(record) for record in result]

    def fetch_kg_metadata(self):
        """Return the latest KGMetadata as a dict, or empty dict."""
        rows = self._run(
            "MATCH (m:KGMetadata) RETURN m ORDER BY m.generated_at DESC LIMIT 1"
        )
        if rows:
            data = rows[0].get("m", {})
            if hasattr(data, "_properties"):
                return dict(data._properties)
            return dict(data) if data else {}
        return {}

    # ---- resolve-changes helpers --------------------------------------------

    def methods_in_file(self, file_path):
        """Return all Method nodes in *file_path* (repo-relative, POSIX sep)."""
        return self._run(
            "MATCH (m:Method) WHERE m.file_path = $fp "
            "RETURN m.name, m.line, m.end_line ORDER BY m.line",
            {"fp": file_path},
        )

    # ---- check-parallel helpers ---------------------------------------------

    def check_directed_calls(self, from_list, to_list):
        """Return paths where any method in *from_list* calls into *to_list*."""
        return self._run(
            "MATCH path = (a:Method)-[r:CALLS_METHOD*1..5]->(b:Method) "
            "WHERE a.name IN $from_list AND b.name IN $to_list "
            "AND ALL(rel IN r WHERE rel.confidence = 'high') "
            "RETURN [n IN nodes(path) | n.name] AS chain, "
            "       [rel IN r | type(rel)] AS edge_types "
            "LIMIT 50",
            {"from_list": from_list, "to_list": to_list},
        )

    def check_shared_config(self, task_a, task_b):
        """Find shared config files via method -> class -> module -> READS_CONFIG."""
        return self._run(
            "MATCH (m1:Method) WHERE m1.name IN $task_a "
            "MATCH (mod1:Module)-[:DEFINES_CLASS]->(:Class {name: m1.owner_class}) "
            "MATCH (m2:Method) WHERE m2.name IN $task_b "
            "MATCH (mod2:Module)-[:DEFINES_CLASS]->(:Class {name: m2.owner_class}) "
            "MATCH (mod1)-[:READS_CONFIG]->(cf:ConfigFile)<-[:READS_CONFIG]-(mod2:Module) "
            "RETURN DISTINCT cf.path AS shared_config, m1.name AS method_a, "
            "       m2.name AS method_b "
            "LIMIT 50",
            {"task_a": task_a, "task_b": task_b},
        )

    # ---- impact helpers -----------------------------------------------------

    def upstream_callers(self, method_list, depth=3):
        return self._run(
            "MATCH path = (caller:Method)-[:CALLS_METHOD*1.."
            + str(depth) + "]->(m:Method) "
            "WHERE m.name IN $method_list "
            "RETURN [n IN nodes(path) | n.name] AS chain, "
            "       length(path) AS distance "
            "ORDER BY distance",
            {"method_list": method_list},
        )

    def downstream_callees(self, method_list, depth=3):
        return self._run(
            "MATCH path = (m:Method)-[:CALLS_METHOD*1.."
            + str(depth) + "]->(callee:Method) "
            "WHERE m.name IN $method_list "
            "RETURN [n IN nodes(path) | n.name] AS chain, "
            "       length(path) AS distance "
            "ORDER BY distance",
            {"method_list": method_list},
        )

    def parent_classes(self, method_list):
        return self._run(
            "MATCH (m:Method) WHERE m.name IN $method_list "
            "MATCH (c:Class)-[:OWNS_METHOD]->(m) "
            "RETURN DISTINCT c.name AS class_fqn, c.short_name AS class_name, "
            "       c.module AS module",
            {"method_list": method_list},
        )

    def config_files_for_methods(self, method_list):
        return self._run(
            "MATCH (m:Method) WHERE m.name IN $method_list "
            "MATCH (mod:Module)-[:DEFINES_CLASS]->(:Class {name: m.owner_class}) "
            "MATCH (mod)-[:READS_CONFIG]->(cf:ConfigFile) "
            "RETURN DISTINCT cf.path AS config_file, cf.format AS format",
            {"method_list": method_list},
        )

    # ---- call-chain helpers -------------------------------------------------

    def call_chain_down(self, method_fqn, depth=3):
        return self._run(
            "MATCH path = (m:Method {name: $fqn})-[:CALLS_METHOD*1.."
            + str(depth) + "]->(target:Method) "
            "RETURN [n IN nodes(path) | n.name] AS chain, "
            "       [rel IN relationships(path) | type(rel)] AS edge_types, "
            "       length(path) AS distance "
            "ORDER BY distance",
            {"fqn": method_fqn},
        )

    def call_chain_up(self, method_fqn, depth=3):
        return self._run(
            "MATCH path = (caller:Method)-[:CALLS_METHOD*1.."
            + str(depth) + "]->(m:Method {name: $fqn}) "
            "RETURN [n IN nodes(path) | n.name] AS chain, "
            "       [rel IN relationships(path) | type(rel)] AS edge_types, "
            "       length(path) AS distance "
            "ORDER BY distance",
            {"fqn": method_fqn},
        )

    # ---- config-readers helpers ----

    def config_readers(self, config_file):
        """Return Module nodes that read a given ConfigFile."""
        return self._run(
            "MATCH (m:Module)-[:READS_CONFIG]->(cf:ConfigFile) "
            "WHERE cf.path CONTAINS $cf "
            "RETURN m.name AS module, cf.path AS config_file "
            "ORDER BY m.name",
            {"cf": config_file},
            limit=100,
        )

    # ---- orphans helpers ----

    def orphans_all(self):
        return self._run(
            "MATCH (n) WHERE NOT (n)--() "
            "RETURN labels(n)[0] AS label, n.name AS name "
            "ORDER BY label, name",
            limit=200,
        )

    def orphans_by_label(self, label):
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", label):
            raise ValueError(f"无效的 label: {label}")
        return self._run(
            f"MATCH (n:{label}) WHERE NOT (n)--() "
            "RETURN n.name AS name, n.file_path AS file_path "
            "ORDER BY name",
            limit=200,
        )

    # ---- cross-layer helpers ----

    def cross_layer_imports(self, from_prefix=None, to_prefix=None):
        conditions = []
        params = {}
        if from_prefix:
            conditions.append("a.name STARTS WITH $fp")
            params["fp"] = from_prefix
        if to_prefix:
            conditions.append("b.name STARTS WITH $tp")
            params["tp"] = to_prefix
        if not conditions:
            raise ValueError("至少需要 --from-layer 或 --to-layer")
        where = " AND ".join(conditions)
        return self._run(
            "MATCH (a:Module)-[:IMPORTS]->(b:Module) "
            f"WHERE {where} "
            'RETURN a.name AS from_module, b.name AS to_module, "IMPORTS" AS edge_type '
            "ORDER BY a.name, b.name",
            params,
            limit=100,
        )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args, cwd):
    """Run a git command, return stdout as text.  Returns None on failure."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _git_commit_sha(project_root):
    out = _run_git(["rev-parse", "HEAD"], project_root)
    return out.strip() if out else "unknown"


def _git_name_status(project_root):
    """Run git diff --name-status -M50% --diff-filter=ACMRD. Returns list of
    (status, old_path, new_path) tuples."""
    out = _run_git(
        ["diff", "--name-status", "-M50%", "--diff-filter=ACMRD", "HEAD"],
        project_root,
    )
    if not out:
        return []
    entries = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            entries.append(("R", parts[1], parts[2]))
        elif len(parts) >= 2:
            entries.append((status, parts[1], None))
    return entries


def _parse_git_name_status_file(filepath):
    """Parse a file containing git diff --name-status output."""
    text = Path(filepath).read_text(encoding="utf-8")
    entries = []
    for line in text.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            entries.append(("R", parts[1], parts[2]))
        elif len(parts) >= 2:
            entries.append((status, parts[1], None))
    return entries


def _git_diff_line_ranges(project_root):
    """Run git diff -U0 and extract per-file changed line ranges in new file.

    Returns dict: {file_path: [(start, end), ...]}  (1-based, inclusive).
    """
    out = _run_git(
        ["diff", "-U0", "--diff-filter=ACMRD", "HEAD"], project_root,
    )
    if not out:
        return {}

    ranges = {}
    current_file = None
    for line in out.split("\n"):
        if line.startswith("diff --git "):
            current_file = None
        elif line.startswith("+++ b/") and current_file is None:
            current_file = line[6:]
        elif line.startswith("@@") and current_file:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                if count > 0:
                    end = start + count - 1
                    ranges.setdefault(current_file, []).append((start, end))
    return ranges


# ---------------------------------------------------------------------------
# Subcommand: resolve-changes
# ---------------------------------------------------------------------------

def cmd_resolve_changes(args):
    """Map git diff file changes to KG Method nodes."""
    project_root = Path(args.project_root).resolve()

    # 1. Get file list from name-status
    if args.git_diff:
        entries = _parse_git_name_status_file(args.git_diff)
    else:
        entries = _git_name_status(project_root)

    # 2. Get line ranges from -U0 diff
    line_ranges = _git_diff_line_ranges(project_root)

    # 3. Connect to Neo4j
    kg = QueryKG()

    changed_high = []
    changed_low = []
    changed_files = []
    unresolved_files = []

    for status, old_path, new_path in entries:
        file_path = (new_path or old_path).replace("\\", "/")
        records = kg.methods_in_file(file_path)

        method_count = len(records)
        file_ranges = line_ranges.get(file_path, [])

        if method_count == 0:
            unresolved_files.append({
                "file": file_path, "status": status,
                "reason": "no matching Method nodes",
            })
            if status == "R":
                unresolved_files[-1]["old_path"] = old_path
            changed_files.append({
                "file": file_path, "status": status,
                "method_count": 0, "unresolved": True,
            })
            continue

        if file_ranges:
            # High confidence: filter methods by line range intersection (±2)
            matched = []
            for rec in records:
                m_line = rec.get("m.line")
                m_end = rec.get("m.end_line") or m_line
                if m_line is None:
                    continue
                for r_start, r_end in file_ranges:
                    # ±2 tolerance
                    if m_line <= r_end + 2 and m_end >= r_start - 2:
                        matched.append(rec["m.name"])
                        break
            if matched:
                changed_high.extend(matched)
            else:
                # File has changes but no method overlaps — all methods are low
                for rec in records:
                    changed_low.append(rec["m.name"])
        else:
            # Low confidence: no line ranges available
            for rec in records:
                changed_low.append(rec["m.name"])

        file_info = {
            "file": file_path, "status": status,
            "method_count": method_count, "unresolved": False,
        }
        if status == "R":
            file_info["old_path"] = old_path
        changed_files.append(file_info)

    commit_sha = _git_commit_sha(project_root)
    meta = kg.fetch_kg_metadata()

    output = {
        "meta": {
            "commit_sha": commit_sha,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kg_run_id": meta.get("kg_run_id"),
        },
        "changed_methods": {
            "high": sorted(set(changed_high)),
            "low": sorted(set(changed_low)),
        },
        "changed_files": changed_files,
        "unresolved_files": unresolved_files,
    }
    kg.close()
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: check-parallel
# ---------------------------------------------------------------------------

def cmd_check_parallel(args):
    """Gate 2 parallel safety check."""
    try:
        task_a = json.loads(args.task_a_methods)
        task_b = json.loads(args.task_b_methods)
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(task_a, list) or not isinstance(task_b, list):
        print("错误: --task-a-methods 和 --task-b-methods 必须是 JSON 数组",
              file=sys.stderr)
        sys.exit(1)

    kg = QueryKG()
    reasons = []

    # 1. A → B directed calls (high confidence only)
    a_calls_b = kg.check_directed_calls(task_a, task_b)
    for row in a_calls_b:
        reasons.append({
            "direction": "A_CALLS_B",
            "chain": row["chain"],
            "edge_types": row["edge_types"],
            "level": "BLOCK",
        })

    # 2. B → A directed calls (high confidence only)
    b_calls_a = kg.check_directed_calls(task_b, task_a)
    for row in b_calls_a:
        reasons.append({
            "direction": "B_CALLS_A",
            "chain": row["chain"],
            "edge_types": row["edge_types"],
            "level": "BLOCK",
        })

    # 3. Shared config files
    shared_config = kg.check_shared_config(task_a, task_b)
    shared_keys = []
    for row in shared_config:
        shared_keys.append({
            "shared_config": row["shared_config"],
            "method_a": row["method_a"],
            "method_b": row["method_b"],
        })
    if shared_keys:
        reasons.append({
            "direction": "SHARED_CONFIG",
            "shared_config_keys": shared_keys,
            "level": "WARN",
        })

    # Gate decision
    if any(r["level"] == "BLOCK" for r in reasons):
        gate = "BLOCK"
    elif reasons:
        gate = "WARN"
    else:
        gate = "PASS"

    meta = kg.fetch_kg_metadata()
    kg.close()

    output = {
        "meta": {
            "kg_run_id": meta.get("kg_run_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "gate": gate,
        "reasons": reasons,
        "shared_config_keys": shared_keys,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: impact
# ---------------------------------------------------------------------------

def cmd_impact(args):
    """Find all methods/classes/config affected by changing given methods."""
    try:
        entry_methods = json.loads(args.methods)
    except json.JSONDecodeError as e:
        print(f"JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(entry_methods, list):
        print("错误: --methods 必须是 JSON 数组", file=sys.stderr)
        sys.exit(1)

    depth = args.depth
    kg = QueryKG()

    # Upstream: who calls these methods
    upstream_raw = kg.upstream_callers(entry_methods, depth)
    upstream_calls = []
    upstream_called_by = []
    seen = set()
    for row in upstream_raw:
        chain = row["chain"]
        if len(chain) >= 2:
            key = " → ".join(chain)
            if key not in seen:
                seen.add(key)
                upstream_called_by.append({
                    "chain": chain,
                    "distance": row["distance"],
                })

    # Downstream: methods called by these methods
    downstream_raw = kg.downstream_callees(entry_methods, depth)
    downstream_calls_methods = []
    seen = set()
    for row in downstream_raw:
        chain = row["chain"]
        if len(chain) >= 2:
            key = " → ".join(chain)
            if key not in seen:
                seen.add(key)
                downstream_calls_methods.append({
                    "chain": chain,
                    "distance": row["distance"],
                })

    # Classes containing these methods
    classes = kg.parent_classes(entry_methods)

    # Config files read by these methods' modules
    config_files = kg.config_files_for_methods(entry_methods)

    meta = kg.fetch_kg_metadata()
    kg.close()

    output = {
        "meta": {
            "kg_run_id": meta.get("kg_run_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "entry_methods": entry_methods,
        "impacted_methods": {
            "upstream": {
                "called_by": upstream_called_by,
            },
            "downstream": {
                "calls_methods": downstream_calls_methods,
            },
        },
        "impacted_classes": [
            {"fqn": c["class_fqn"], "name": c["class_name"],
             "module": c["module"]}
            for c in classes
        ],
        "impacted_config_keys": [
            {"file": cf["config_file"], "format": cf["format"]}
            for cf in config_files
        ],
        "subgraphs": [],  # reserved for future use
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: call-chain
# ---------------------------------------------------------------------------

def cmd_call_chain(args):
    """Trace call chain up or down from a method."""
    method_fqn = args.method
    direction = args.direction
    depth = args.depth

    kg = QueryKG()

    if direction == "down":
        rows = kg.call_chain_down(method_fqn, depth)
    else:
        rows = kg.call_chain_up(method_fqn, depth)

    chains = []
    seen = set()
    for row in rows:
        chain = row["chain"]
        key = " → ".join(chain)
        if key not in seen:
            seen.add(key)
            chains.append({
                "chain": chain,
                "edge_types": row["edge_types"],
                "distance": row["distance"],
            })

    meta = kg.fetch_kg_metadata()
    kg.close()

    output = {
        "meta": {
            "kg_run_id": meta.get("kg_run_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "method": method_fqn,
        "direction": direction,
        "depth": depth,
        "chains": chains,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: config-readers
# ---------------------------------------------------------------------------

def cmd_config_readers(args):
    """Find which modules read a given config file."""
    kg = QueryKG()
    rows = kg.config_readers(args.config_key)
    readers = [
        {"module": r["module"], "config_file": r["config_file"]}
        for r in rows
    ]
    meta = kg.fetch_kg_metadata()
    kg.close()
    output = {
        "meta": {
            "kg_run_id": meta.get("kg_run_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "config_key": args.config_key,
        "readers": readers,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: orphans
# ---------------------------------------------------------------------------

def cmd_orphans(args):
    """Find nodes with no relationships."""
    kg = QueryKG()
    if args.label:
        rows = kg.orphans_by_label(args.label)
        orphan_dict: dict[str, list] = {args.label: []}
        for r in rows:
            entry = {"name": r["name"]}
            if r.get("file_path"):
                entry["file_path"] = r["file_path"]
            orphan_dict[args.label].append(entry)
    else:
        rows = kg.orphans_all()
        orphan_dict = {}
        for r in rows:
            label = r["label"]
            orphan_dict.setdefault(label, []).append({"name": r["name"]})
    total = sum(len(v) for v in orphan_dict.values())
    meta = kg.fetch_kg_metadata()
    kg.close()
    output = {
        "meta": {
            "kg_run_id": meta.get("kg_run_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "orphans": orphan_dict,
        "total": total,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommand: cross-layer
# ---------------------------------------------------------------------------

def cmd_cross_layer(args):
    """Check for architecture layer violations."""
    from_layer = args.from_layer
    to_layer = args.to_layer
    if not from_layer and not to_layer:
        print("错误: 至少需要 --from-layer 或 --to-layer", file=sys.stderr)
        sys.exit(1)
    kg = QueryKG()
    rows = kg.cross_layer_imports(from_prefix=from_layer, to_prefix=to_layer)
    violations = [
        {"from_module": r["from_module"], "to_module": r["to_module"],
         "edge_type": r["edge_type"]}
        for r in rows
    ]
    if from_layer and to_layer:
        rule = f"{from_layer} should not import {to_layer}"
    elif from_layer:
        rule = f"all imports from {from_layer}"
    else:
        rule = f"all imports to {to_layer}"
    meta = kg.fetch_kg_metadata()
    kg.close()
    output = {
        "meta": {
            "kg_run_id": meta.get("kg_run_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "rule": rule,
        "violations": violations,
        "total_violations": len(violations),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="KG-assisted development — query Neo4j knowledge graph",
    )
    parser.add_argument(
        "--timeout-ms", type=int, default=_DEFAULT_TIMEOUT * 1000,
        help=f"查询超时毫秒 (默认 {_DEFAULT_TIMEOUT * 1000})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- resolve-changes ----
    p_resolve = sub.add_parser(
        "resolve-changes",
        help="映射 git diff 文件变动到 KG Method 节点",
    )
    p_resolve.add_argument(
        "--git-diff",
        help="git diff --name-status 输出文件路径 (不提供则自动运行 git diff)",
    )
    p_resolve.add_argument(
        "--project-root", default=".",
        help="项目根目录 (默认当前目录)",
    )

    # ---- check-parallel ----
    p_check = sub.add_parser(
        "check-parallel",
        help="Gate 2 并行安全检测",
    )
    p_check.add_argument(
        "--task-a-methods", required=True,
        help='任务 A 的 method FQN JSON 数组 (例: \'["fqn1","fqn2"]\')',
    )
    p_check.add_argument(
        "--task-b-methods", required=True,
        help='任务 B 的 method FQN JSON 数组',
    )

    # ---- impact ----
    p_impact = sub.add_parser(
        "impact",
        help="查找变更指定方法后受影响的全部方法/类/配置",
    )
    p_impact.add_argument(
        "--methods", required=True,
        help='入口 method FQN JSON 数组',
    )
    p_impact.add_argument(
        "--depth", type=int, default=3,
        help="遍历深度 (默认 3)",
    )

    # ---- call-chain ----
    p_chain = sub.add_parser(
        "call-chain",
        help="追踪调用链 (上/下游)",
    )
    p_chain.add_argument(
        "--method", required=True,
        help="入口 method FQN",
    )
    p_chain.add_argument(
        "--direction", choices=["up", "down"], default="down",
        help="追踪方向 (默认 down)",
    )
    p_chain.add_argument(
        "--depth", type=int, default=3,
        help="追踪深度 (默认 3)",
    )

    # ---- config-readers ----
    p_config_readers = sub.add_parser(
        "config-readers",
        help="查找读取给定配置键的方法",
    )
    p_config_readers.add_argument(
        "--config-key", required=True,
        help='配置键路径 (例: "feishu.toml.bitable.app_token")',
    )

    # ---- orphans ----
    p_orphans = sub.add_parser(
        "orphans",
        help="查找无关系的孤立节点",
    )
    p_orphans.add_argument(
        "--label",
        help="按标签过滤 (例: Method, Class, Module)",
    )

    # ---- cross-layer ----
    p_cross = sub.add_parser(
        "cross-layer",
        help="检查架构层次依赖违规",
    )
    p_cross.add_argument(
        "--from-layer",
        help="来源层前缀 (例: engine)",
    )
    p_cross.add_argument(
        "--to-layer",
        help="目标层前缀 (例: app)",
    )

    args = parser.parse_args()

    # Apply global timeout (convert ms → s)
    global TIMEOUT_SEC
    TIMEOUT_SEC = max(1, args.timeout_ms // 1000)

    try:
        if args.command == "resolve-changes":
            cmd_resolve_changes(args)
        elif args.command == "check-parallel":
            cmd_check_parallel(args)
        elif args.command == "impact":
            cmd_impact(args)
        elif args.command == "call-chain":
            cmd_call_chain(args)
        elif args.command == "config-readers":
            cmd_config_readers(args)
        elif args.command == "orphans":
            cmd_orphans(args)
        elif args.command == "cross-layer":
            cmd_cross_layer(args)
    except Exception as e:
        msg = str(e)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            print(f"查询超时: {e}\n提示: 使用 --timeout-ms 调整超时值", file=sys.stderr)
        elif "Unable to connect" in msg or "connect" in msg.lower():
            print(f"无法连接 Neo4j: {e}\n"
                  f"请确认 Neo4j 运行在 {NEO4J_URI}", file=sys.stderr)
        else:
            print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
