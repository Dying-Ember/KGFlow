#!/usr/bin/env python3
"""Compare two Neo4j knowledge graph runs and output an incremental diff.

Usage:
  uv run python tools/diff_kg.py --from-run <run_id> --to-run <run_id>
  uv run python tools/diff_kg.py --from-latest 3 --to-latest 1
  uv run python tools/diff_kg.py --from-commit <sha> --to-commit <sha>
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KGFLOW_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = KGFLOW_ROOT / "output"


# ---------------------------------------------------------------------------
# Cypher property value parsing
# ---------------------------------------------------------------------------

def _parse_array_elements(s: str) -> list:
    """Parse comma-separated array elements from inside [...], handling quoted strings."""
    elements: list = []
    i = 0
    while i < len(s):
        while i < len(s) and s[i] in " \t,":
            i += 1
        if i >= len(s):
            break
        if s[i] == '"':
            i += 1
            chars = []
            while i < len(s):
                if s[i] == "\\" and i + 1 < len(s):
                    chars.append(s[i + 1])
                    i += 2
                elif s[i] == '"':
                    i += 1
                    break
                else:
                    chars.append(s[i])
                    i += 1
            elements.append("".join(chars))
        else:
            j = i
            while j < len(s) and s[j] not in ",":
                j += 1
            elem = s[i:j].strip()
            if elem == "true":
                elements.append(True)
            elif elem == "false":
                elements.append(False)
            elif elem == "null":
                elements.append(None)
            else:
                try:
                    elements.append(int(elem))
                except ValueError:
                    try:
                        elements.append(float(elem))
                    except ValueError:
                        elements.append(elem)
            i = j
    return elements


def _parse_single_value(val_str: str):
    """Parse a single Cypher literal value."""
    val_str = val_str.strip()
    if val_str.startswith('"') and val_str.endswith('"'):
        s = val_str[1:-1]
        return s.replace('\\"', '"').replace("\\\\", "\\")
    if val_str == "true":
        return True
    if val_str == "false":
        return False
    if val_str == "null":
        return None
    if val_str.startswith("["):
        return _parse_array_elements(val_str[1:-1])
    try:
        return int(val_str)
    except ValueError:
        try:
            return float(val_str)
        except ValueError:
            return val_str


def _parse_props_string(s: str) -> dict:
    """Parse a Cypher property block like 'key: "val", key2: true' into a dict."""
    props: dict = {}
    if not s.strip():
        return props

    i = 0
    s = s.strip()
    while i < len(s):
        while i < len(s) and s[i] in " \t\n,;":
            i += 1
        if i >= len(s):
            break

        # Read key
        j = i
        while j < len(s) and s[j] != ":":
            j += 1
        key = s[i:j].strip()
        if not key:
            break
        i = j + 1  # skip ':'

        while i < len(s) and s[i] in " \t\n":
            i += 1
        if i >= len(s):
            break

        # Read value
        if s[i] == '"':
            i += 1
            val_chars = []
            while i < len(s):
                if s[i] == "\\" and i + 1 < len(s):
                    val_chars.append(s[i + 1])
                    i += 2
                elif s[i] == '"':
                    i += 1
                    break
                else:
                    val_chars.append(s[i])
                    i += 1
            props[key] = "".join(val_chars)
        elif s[i] == "[":
            depth = 1
            j = i + 1
            in_string = False
            while j < len(s) and depth > 0:
                if s[j] == "\\" and in_string:
                    j += 2
                    continue
                if s[j] == '"':
                    in_string = not in_string
                if not in_string:
                    if s[j] == "[":
                        depth += 1
                    elif s[j] == "]":
                        depth -= 1
                j += 1
            props[key] = _parse_array_elements(s[i + 1 : j - 1])
            i = j
        elif s[i : i + 4] == "true":
            props[key] = True
            i += 4
        elif s[i : i + 5] == "false":
            props[key] = False
            i += 5
        elif s[i : i + 4] == "null":
            props[key] = None
            i += 4
        elif s[i].isdigit() or (s[i] == "-" and i + 1 < len(s) and s[i + 1].isdigit()):
            j = i
            if s[j] == "-":
                j += 1
            while j < len(s) and s[j].isdigit():
                j += 1
            if j < len(s) and s[j] == ".":
                j += 1
                while j < len(s) and s[j].isdigit():
                    j += 1
                props[key] = float(s[i:j])
            else:
                props[key] = int(s[i:j])
            i = j
        else:
            i += 1

    return props


# ---------------------------------------------------------------------------
# Statement splitter
# ---------------------------------------------------------------------------

def _split_statements(text: str) -> list:
    """Split cypher text into individual statements, handling multi-line nodes."""
    statements = []
    current = []
    for line in text.splitlines():
        current.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
    if current:
        stmt = "\n".join(current).strip()
        if stmt:
            statements.append(stmt)
    return statements


# ---------------------------------------------------------------------------
# Identity key builders
# ---------------------------------------------------------------------------

def _node_identity(label: str, merge_props: dict) -> str:
    """Build a unique identity key for a node using label + all merge properties."""
    parts = [label]
    for k in sorted(merge_props.keys()):
        parts.append(f"{k}={merge_props[k]}")
    return "::".join(parts)


def _edge_identity(edge: dict) -> str:
    """Build a unique identity key for an edge (dedup by from/to/type, ignoring rel props)."""
    fp = "::".join(f"{k}={v}" for k, v in sorted(edge["from_props"].items()))
    tp = "::".join(f"{k}={v}" for k, v in sorted(edge["to_props"].items()))
    return f"{edge['from_label']}:{fp}::{edge['rel_type']}::{edge['to_label']}:{tp}"


# ---------------------------------------------------------------------------
# Statement parsers
# ---------------------------------------------------------------------------

_RE_MERGE_NODE = re.compile(r"MERGE\s+\(n:(\w+)\s+\{([^}]*)\}\)")
_RE_SET_BLOCK = re.compile(r"SET\s*\n(.*?);", re.DOTALL)
_RE_SET_LINE = re.compile(r"[nm]\.(\w+)\s*=\s*(.+)")


def _parse_metadata(stmt: str) -> dict:
    """Parse KGMetadata MERGE + SET into a flat dict."""
    metadata: dict = {}
    m = re.match(r"MERGE\s+\(m:KGMetadata\s+\{([^}]*)\}\)", stmt)
    if m:
        metadata = _parse_props_string(m.group(1))
    set_match = _RE_SET_BLOCK.search(stmt)
    if set_match:
        for line in set_match.group(1).split("\n"):
            line = line.strip().rstrip(",")
            pm = _RE_SET_LINE.match(line)
            if pm:
                metadata[pm.group(1)] = _parse_single_value(pm.group(2).strip().rstrip(","))
    return metadata


def _parse_node(stmt: str):
    """Parse a MERGE (n:Label {...}) SET ... statement.

    Returns (label, merge_props, all_props, node_identity) or None.
    """
    m = _RE_MERGE_NODE.match(stmt)
    if not m:
        return None
    label = m.group(1)
    merge_props = _parse_props_string(m.group(2))

    all_props = dict(merge_props)
    set_match = _RE_SET_BLOCK.search(stmt)
    if set_match:
        for line in set_match.group(1).split("\n"):
            line = line.strip().rstrip(",")
            pm = _RE_SET_LINE.match(line)
            if pm:
                all_props[pm.group(1)] = _parse_single_value(pm.group(2).strip().rstrip(","))

    return (label, merge_props, all_props)


_RE_EDGE = re.compile(
    r"MATCH\s+\(a:(\w+)\s+\{([^}]*)\}\)\s+"
    r"MATCH\s+\(b:(\w+)\s+\{([^}]*)\}\)\s+"
    r"MERGE\s+\(a\)-\s*\[r?:(\w+)\]\s*->\s*\(b\)"
    r"\s*(SET\s+.+)?"
)


def _parse_edge(stmt: str):
    """Parse a MATCH ... MERGE (a)-[:TYPE]->(b) statement.

    Returns dict with from_label, from_props, rel_type, to_label, to_props, rel_props.
    """
    m = _RE_EDGE.match(stmt)
    if not m:
        return None

    rel_props: dict = {}
    set_clause = m.group(6)
    if set_clause:
        set_clause = set_clause.strip()
        if set_clause.startswith("SET"):
            set_text = set_clause[3:].strip().rstrip(";")
            for part in set_text.split(","):
                part = part.strip()
                pm = re.match(r"r\.(\w+)\s*=\s*(.+)", part)
                if pm:
                    rel_props[pm.group(1)] = _parse_single_value(pm.group(2).strip())

    return {
        "from_label": m.group(1),
        "from_props": _parse_props_string(m.group(2)),
        "rel_type": m.group(5),
        "to_label": m.group(3),
        "to_props": _parse_props_string(m.group(4)),
        "rel_props": rel_props,
    }


# ---------------------------------------------------------------------------
# Cypher file loader
# ---------------------------------------------------------------------------

def parse_cypher_file(filepath: Path):
    """Parse a .cypher file and return (nodes, edges, metadata)."""
    text = filepath.read_text(encoding="utf-8")
    statements = _split_statements(text)

    nodes: dict = {}
    edges: dict = {}
    metadata: dict = {}

    for stmt in statements:
        first = stmt.strip()

        if first.startswith("CREATE CONSTRAINT"):
            continue

        if first.startswith("MERGE (m:KGMetadata"):
            metadata = _parse_metadata(stmt)
            continue

        if first.startswith("MERGE (n:"):
            parsed = _parse_node(stmt)
            if parsed is None:
                continue
            label, merge_props, all_props = parsed
            nid = _node_identity(label, merge_props)
            if nid not in nodes:
                nodes[nid] = {"label": label, "merge_props": merge_props, "all_props": all_props}
            continue

        if first.startswith("MATCH (a:"):
            edge = _parse_edge(stmt)
            if edge is None:
                continue
            eid = _edge_identity(edge)
            if eid not in edges:
                edges[eid] = edge
            continue

    return nodes, edges, metadata


# ---------------------------------------------------------------------------
# Run discovery
# ---------------------------------------------------------------------------

def find_archived_runs(output_dir: Path) -> list:
    """Scan output_dir for *.cypher files, sorted by generated_at descending.

    Returns list of (run_id, file_path, metadata) tuples.
    """
    runs = []
    # Only match knowledge_graph.cypher (latest) and kg_{run_id}.cypher (archived)
    cypher_files = (
        list(output_dir.glob("kg_????????????.cypher"))
        + list(output_dir.glob("knowledge_graph.cypher"))
    )
    for cypher_file in sorted(cypher_files):
        name = cypher_file.stem
        try:
            _, _, metadata = parse_cypher_file(cypher_file)
        except Exception:
            continue

        run_id = metadata.get("kg_run_id", "")
        if not run_id and name.startswith("kg_"):
            run_id = name[3:]
        generated_at = metadata.get("generated_at", "")

        runs.append((run_id, cypher_file, metadata, generated_at))

    runs.sort(key=lambda r: r[3], reverse=True)
    return [(r[0], r[1], r[2]) for r in runs]


def resolve_run(runs: list, spec_type: str, spec_value: str):
    """Resolve a run spec to (run_id, file_path, metadata)."""
    if spec_type == "run":
        for run_id, file_path, metadata in runs:
            if run_id == spec_value:
                return run_id, file_path, metadata
        print(f"错误: 未找到 run_id='{spec_value}' 的 Cypher 文件", file=sys.stderr)
        sys.exit(1)

    elif spec_type == "latest":
        n = int(spec_value)
        if n < 1 or n > len(runs):
            print(f"错误: --latest {n} 超出范围 (可用 1-{len(runs)})", file=sys.stderr)
            sys.exit(1)
        return runs[n - 1]

    elif spec_type == "commit":
        for run_id, file_path, metadata in runs:
            commit = metadata.get("commit_sha", "")
            if commit and commit.startswith(spec_value):
                return run_id, file_path, metadata
        print(f"错误: 未找到 commit_sha 匹配 '{spec_value}' 的 run", file=sys.stderr)
        sys.exit(1)

    raise ValueError(f"Unknown spec_type: {spec_type}")


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def _node_summary(label: str, props: dict) -> dict:
    """Build a compact summary dict for a node in diff output."""
    result: dict = {"labels": [label]}
    for key in (
        "name", "file_path", "line", "end_line", "module", "owner_class",
        "path", "short_name", "format", "exception_name",
    ):
        if key in props:
            result[key] = props[key]
    return result


def compute_diff(
    from_nodes: dict, from_edges: dict,
    to_nodes: dict, to_edges: dict,
) -> dict:
    """Compute diff between two sets of nodes and edges."""
    from_nkeys = set(from_nodes.keys())
    to_nkeys = set(to_nodes.keys())
    from_ekeys = set(from_edges.keys())
    to_ekeys = set(to_edges.keys())

    added_nkeys = to_nkeys - from_nkeys
    removed_nkeys = from_nkeys - to_nkeys
    added_ekeys = to_ekeys - from_ekeys
    removed_ekeys = from_ekeys - to_ekeys

    added_nodes = [
        _node_summary(to_nodes[k]["label"], to_nodes[k]["all_props"])
        for k in sorted(added_nkeys)
    ]
    removed_nodes = [
        _node_summary(from_nodes[k]["label"], from_nodes[k]["all_props"])
        for k in sorted(removed_nkeys)
    ]

    added_edges = []
    for k in sorted(added_ekeys):
        e = to_edges[k]
        entry = {
            "type": e["rel_type"],
            "from_label": e["from_label"],
            "from": e["from_props"].get("name") or e["from_props"].get("path", ""),
            "to_label": e["to_label"],
            "to": e["to_props"].get("name") or e["to_props"].get("path", ""),
        }
        if e.get("rel_props"):
            entry.update(e["rel_props"])
        added_edges.append(entry)

    removed_edges = []
    for k in sorted(removed_ekeys):
        e = from_edges[k]
        entry = {
            "type": e["rel_type"],
            "from_label": e["from_label"],
            "from": e["from_props"].get("name") or e["from_props"].get("path", ""),
            "to_label": e["to_label"],
            "to": e["to_props"].get("name") or e["to_props"].get("path", ""),
        }
        if e.get("rel_props"):
            entry.update(e["rel_props"])
        removed_edges.append(entry)

    # Edge delta by type
    from_counts: dict = {}
    to_counts: dict = {}
    for e in from_edges.values():
        t = e["rel_type"]
        from_counts[t] = from_counts.get(t, 0) + 1
    for e in to_edges.values():
        t = e["rel_type"]
        to_counts[t] = to_counts.get(t, 0) + 1

    all_types = sorted(set(from_counts) | set(to_counts))
    edge_delta = {}
    for t in all_types:
        a = max(0, to_counts.get(t, 0) - from_counts.get(t, 0))
        r = max(0, from_counts.get(t, 0) - to_counts.get(t, 0))
        if a > 0 or r > 0:
            edge_delta[t] = {"added": a, "removed": r}

    return {
        "summary": {
            "nodes_added": len(added_nodes),
            "nodes_removed": len(removed_nodes),
            "edges_added": len(added_edges),
            "edges_removed": len(removed_edges),
            "edge_delta_by_type": edge_delta,
        },
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
    }


def compute_change_attribution(from_meta: dict, to_meta: dict) -> str:
    """Determine change attribution from metadata comparison."""
    gen_match = from_meta.get("generator_version") == to_meta.get("generator_version")
    config_match = from_meta.get("extractor_config_hash") == to_meta.get("extractor_config_hash")

    if gen_match and config_match:
        return "code_only"
    elif not gen_match:
        return "extractor_only"
    else:
        return "unknown"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="比较两个 Neo4j 知识图谱 run 并输出增量差异 (JSON)",
    )

    src = parser.add_argument_group("源 run 指定 (from)")
    src.add_argument("--from-run", help="源 run_id (12字符 hex hash)")
    src.add_argument("--from-latest", type=int, help="倒数第 N 个 run (1=最新)")
    src.add_argument("--from-commit", help="源 commit SHA (前缀匹配)")

    dst = parser.add_argument_group("目标 run 指定 (to)")
    dst.add_argument("--to-run", help="目标 run_id")
    dst.add_argument("--to-latest", type=int, default=1, help="倒数第 N 个 run (默认 1=最新)")
    dst.add_argument("--to-commit", help="目标 commit SHA (前缀匹配)")

    parser.add_argument(
        "--output-dir", default=str(DEFAULT_OUTPUT_DIR),
        help=f"存放 .cypher 文件的目录 (默认: {DEFAULT_OUTPUT_DIR})",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"错误: 输出目录不存在: {output_dir}", file=sys.stderr)
        sys.exit(1)

    runs = find_archived_runs(output_dir)
    if not runs:
        print("错误: 在输出目录中未找到任何 .cypher 文件", file=sys.stderr)
        sys.exit(1)

    # Resolve source
    if args.from_run:
        from_spec = ("run", args.from_run)
    elif args.from_latest:
        from_spec = ("latest", str(args.from_latest))
    elif args.from_commit:
        from_spec = ("commit", args.from_commit)
    else:
        if len(runs) < 2:
            print("错误: 需要至少 2 个 run 才能比较 (只找到 1 个)", file=sys.stderr)
            print("提示: 使用 --from-run <id> 指定源 run", file=sys.stderr)
            sys.exit(1)
        from_spec = ("latest", "2")

    # Resolve target
    if args.to_run:
        to_spec = ("run", args.to_run)
    elif args.to_commit:
        to_spec = ("commit", args.to_commit)
    else:
        to_spec = ("latest", str(args.to_latest))

    from_id, from_file, from_meta = resolve_run(runs, *from_spec)
    to_id, to_file, to_meta = resolve_run(runs, *to_spec)

    if from_id == to_id:
        print(f"错误: from 和 to 是同一个 run ({from_id})", file=sys.stderr)
        sys.exit(1)

    print(f"diff: {from_id} -> {to_id}", file=sys.stderr)
    print(f"  源: {from_file}  ({len(from_file.read_text(encoding='utf-8').splitlines())} lines)", file=sys.stderr)
    print(f"  目标: {to_file}", file=sys.stderr)

    from_nodes, from_edges, _ = parse_cypher_file(from_file)
    to_nodes, to_edges, _ = parse_cypher_file(to_file)

    print(f"  from: {len(from_nodes)} nodes, {len(from_edges)} edges", file=sys.stderr)
    print(f"  to:   {len(to_nodes)} nodes, {len(to_edges)} edges", file=sys.stderr)

    diff = compute_diff(from_nodes, from_edges, to_nodes, to_edges)
    attribution = compute_change_attribution(from_meta, to_meta)

    output = {
        "schema_version": "1.0.0",
        "meta": {
            "from_run_id": from_id,
            "to_run_id": to_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "meta_check": {
            "from": {
                "commit_sha": from_meta.get("commit_sha", ""),
                "generator_version": from_meta.get("generator_version", ""),
                "extractor_config_hash": from_meta.get("extractor_config_hash", ""),
            },
            "to": {
                "commit_sha": to_meta.get("commit_sha", ""),
                "generator_version": to_meta.get("generator_version", ""),
                "extractor_config_hash": to_meta.get("extractor_config_hash", ""),
            },
            "generator_version_match": from_meta.get("generator_version")
                == to_meta.get("generator_version"),
            "extractor_config_hash_match": from_meta.get("extractor_config_hash")
                == to_meta.get("extractor_config_hash"),
        },
        "change_attribution": attribution,
        **diff,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
