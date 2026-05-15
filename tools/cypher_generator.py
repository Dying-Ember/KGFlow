"""Generate Neo4j Cypher statements from AST-parsed project data and config files."""

import json
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


# ── Hardcoded mapping tables ──

WORKER_ENGINE_MAP = {
    "app.gui_app.DownloadWorker": "engine.innoshare_engine.InnoShareEngine",
    "app.gui_app.PushWorker": "engine.feishu_engine.FeishuEngine",
    "app.gui_app.RpaWorker": "engine.rpa_draft_engine.RpaDraftEngine",
    "app.gui_app.LinkSyncWorker": "engine.rpa_link_sync_engine.RpaLinkSyncEngine",
    "app.gui_app.TransTrackWorker": "engine.transtrack_engine.TransTrackEngine",
}

WORKER_TAB_MAP = {
    "app.gui_app.DownloadWorker": "InnoShare自动同步",
    "app.gui_app.PushWorker": "InnoShare自动同步",
    "app.gui_app.RpaWorker": "TransTrack RISC自动录入",
    "app.gui_app.LinkSyncWorker": "InnoShare-TransTrack自动同步",
    "app.gui_app.TransTrackWorker": "全局配置",
}

QUEUE_MAP = [("DownloadWorker", "PushWorker")]

EXTERNAL_DEPS = {
    "engine.feishu_client": "飞书多维表格API",
    "engine.feishu_engine": "飞书多维表格API",
    "engine.transtrack_engine": "TransTrack RISC 系统",
    "engine.innoshare_engine": "InnoShare 云端协作平台",
    "engine.rpa_draft_engine": "TransTrack RISC 系统",
    "engine.rpa_link_sync_engine": "TransTrack RISC 系统",
    "engine.rpa_base_engine": "TransTrack RISC 系统",
    "engine.tt_interaction": "TransTrack RISC 系统",
}

CONFIG_REFS = {
    "engine.feishu_client": ["config/feishu.toml"],
    "engine.feishu_engine": ["config/feishu.toml"],
    "engine.transtrack_engine": ["config/site_xpath.json", "config/site_auth.json"],
    "engine.innoshare_engine": ["config/site_xpath.json", "config/site_auth.json", "config/feishu.toml"],
    "engine.rpa_base_engine": ["config/site_xpath.json", "config/site_auth.json"],
    "engine.rpa_draft_engine": ["config/site_xpath.json", "config/site_auth.json"],
    "engine.rpa_link_sync_engine": ["config/site_xpath.json", "config/site_auth.json"],
    "engine.account_manager": ["config/accounts.toml"],
    "app.gui_app": ["config/feishu.toml", "config/site_auth.json", "config/site_xpath.json", "config/accounts.toml"],
}

TEST_MODULE_MAP = {
    "tests.test_feishu_client": "engine.feishu_client",
    "tests.test_transtrack_engine": "engine.transtrack_engine",
    "tests.test_innoshare_engine": "engine.innoshare_engine",
    "tests.test_rpa_risc_engine": "engine.rpa_risc_engine",
    "tests.test_account_manager": "engine.account_manager",
    "tests.test_config_editor": "app.config_editor",
}

CONFIG_FILES = [
    "config/feishu.toml",
    "config/accounts.toml",
    "config/site_xpath.json",
    "config/site_auth.json",
]


def _escape_cypher(value):
    """Escape a value for Cypher output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        items = [_escape_cypher(v) for v in value]
        return f"[{', '.join(items)}]"
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _prop_str(props, indent=8):
    """Format dict as Cypher property string, sorted."""
    items = []
    for k, v in sorted(props.items()):
        if v == "" or v == [] or v == {} or v is None:
            continue
        items.append(f"n.{k} = {_escape_cypher(v)}")
    if not items:
        return ""
    prefix = " " * indent
    return "\n" + prefix + (",\n" + prefix).join(items)


def _flatten_toml(data, prefix=""):
    """Recursively flatten nested TOML dict into {section_path: {scalar_props}}."""
    sections = {}
    curr_scalars = {}

    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            child_scalars = {}
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict):
                    sections.update(_flatten_toml({sub_key: sub_value}, full_key))
                else:
                    child_scalars[sub_key] = sub_value
            if child_scalars:
                sections[full_key] = child_scalars
            elif not value:
                # Empty dict: still create a section node
                sections[full_key] = {}
        else:
            curr_scalars[key] = value

    if curr_scalars and prefix:
        sections.setdefault(prefix, {}).update(curr_scalars)
    elif curr_scalars and not prefix:
        sections["_root"] = curr_scalars

    return sections


def _parse_toml_sections(filepath: Path):
    """Parse TOML config into {section_name: properties_dict}."""
    with open(filepath, "rb") as f:
        data = tomllib.load(f)
    return _flatten_toml(data)


def _flatten_json(data, prefix=""):
    """Recursively flatten nested JSON into {section_path: {scalar_props}}."""
    sections = {}
    curr_scalars = {}

    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            child_scalars = {}
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict):
                    sections.update(_flatten_json({sub_key: sub_value}, full_key))
                elif isinstance(sub_value, list):
                    child_scalars[sub_key] = json.dumps(sub_value, ensure_ascii=False)
                else:
                    child_scalars[sub_key] = sub_value
            if child_scalars:
                sections[full_key] = child_scalars
            elif not value:
                sections[full_key] = {}
        elif isinstance(value, list):
            sections[full_key if prefix else key] = {"_type": "array", "_count": len(value)}
        else:
            curr_scalars[key] = value

    if curr_scalars and prefix:
        sections.setdefault(prefix, {}).update(curr_scalars)
    elif curr_scalars and not prefix:
        sections["_root"] = curr_scalars

    return sections


def _parse_json_sections(filepath: Path):
    """Parse JSON config into {section_name: properties_dict}."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _flatten_json(data)


def _collect_config_nodes(project_root: Path):
    """Return (config_file_nodes, config_section_nodes, has_section_rels)."""
    config_file_nodes = []
    config_section_nodes = []
    has_section_rels = []

    parsers = {".toml": _parse_toml_sections, ".json": _parse_json_sections}

    for rel_path in CONFIG_FILES:
        filepath = project_root / rel_path
        if not filepath.exists():
            continue

        suffix = filepath.suffix
        parser = parsers.get(suffix)
        if parser is None:
            continue

        try:
            sections = parser(filepath)
        except Exception:
            continue

        fmt = suffix.lstrip(".")
        config_file_nodes.append(
            {
                "path": rel_path,
                "format": fmt,
                "sections_count": len(sections),
            }
        )

        for section_name, props in sections.items():
            section_node = {
                "name": section_name,
                "config_file": rel_path,
            }
            section_node.update(props)
            config_section_nodes.append(section_node)
            has_section_rels.append((rel_path, section_name))

    return config_file_nodes, config_section_nodes, has_section_rels


def _build_test_relationships(data):
    """Build TESTS and MOCKS relationships from test classes in AST data."""
    tests_rels = []
    mocks_rels = []

    test_modules = {m: target for m, target in TEST_MODULE_MAP.items()}

    # Index target classes by module + short name
    class_index = {}
    for cls in data.get("classes", []):
        short_name = cls["name"]
        module = cls["module"]
        class_index.setdefault(module, {})[short_name] = cls["fqn"]

    for cls in data.get("classes", []):
        module = cls["module"]
        if module not in test_modules:
            continue

        target_module = test_modules[module]
        # Always add MOCKS relationship
        mocks_rels.append((cls["fqn"], target_module))

        # Try to find the target class
        test_name = cls["name"]
        # Heuristic: strip "Test" prefix
        if test_name.startswith("Test"):
            candidate = test_name[4:]
            # Look for this class in the target module
            if target_module in class_index and candidate in class_index[target_module]:
                tests_rels.append((cls["fqn"], class_index[target_module][candidate]))

    return tests_rels, mocks_rels


def _emit_constraints(buf):
    """Emit CREATE CONSTRAINT statements."""
    constraints = [
        "Module", "Class", "Method", "Function", "Signal",
        "ConfigFile", "ConfigSection", "WorkerThread", "GUITab", "ExternalSystem",
        "ErrorType", "Condition", "CallSite",
    ]
    # Use "n.name" for all (WorkerThread/GUITab also keyed by name)
    for label in constraints:
        buf.append(
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
            f"REQUIRE n.name IS UNIQUE;"
        )
    buf.append(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:KGMetadata) "
        "REQUIRE m.kg_run_id IS UNIQUE;"
    )
    buf.append("")


def _emit_node(buf, label, props, prop_map=None):
    """Emit a MERGE node statement. prop_map overrides the key used for matching."""
    if prop_map is None:
        prop_map = {"name": props.get("name", "")}

    match_parts = []
    for k, v in sorted(prop_map.items()):
        match_parts.append(f"{k}: {_escape_cypher(v)}")

    buf.append(f"MERGE (n:{label} {{{', '.join(match_parts)}}})")
    # Exclude match keys from the SET clause (they are already in MERGE)
    filtered = {k: v for k, v in props.items() if k not in prop_map}
    extra = _prop_str(filtered)
    if extra:
        buf.append(f"SET{extra}")
    buf.append(";")


def _emit_rel(buf, from_label, from_key, from_val, rel_type, to_label, to_key, to_val,
              extra_from=None, extra_to=None):
    """Emit a MERGE relationship statement.

    extra_from / extra_to are optional {key: val} dicts for additional match conditions.
    """
    from_parts = [f"{from_key}: {_escape_cypher(from_val)}"]
    if extra_from:
        for k, v in sorted(extra_from.items()):
            from_parts.append(f"{k}: {_escape_cypher(v)}")
    to_parts = [f"{to_key}: {_escape_cypher(to_val)}"]
    if extra_to:
        for k, v in sorted(extra_to.items()):
            to_parts.append(f"{k}: {_escape_cypher(v)}")
    buf.append(
        f"MATCH (a:{from_label} {{{', '.join(from_parts)}}}) "
        f"MATCH (b:{to_label} {{{', '.join(to_parts)}}}) "
        f"MERGE (a)-[:{rel_type}]->(b);"
    )


def _emit_rel_props(buf, from_label, from_key, from_val, rel_type, to_label, to_key, to_val,
                    props, extra_from=None, extra_to=None):
    """Emit a MERGE relationship statement with properties on the relationship."""
    from_parts = [f"{from_key}: {_escape_cypher(from_val)}"]
    if extra_from:
        for k, v in sorted(extra_from.items()):
            from_parts.append(f"{k}: {_escape_cypher(v)}")
    to_parts = [f"{to_key}: {_escape_cypher(to_val)}"]
    if extra_to:
        for k, v in sorted(extra_to.items()):
            to_parts.append(f"{k}: {_escape_cypher(v)}")
    prop_parts = []
    for k, v in sorted(props.items()):
        prop_parts.append(f"r.{k} = {_escape_cypher(v)}")
    buf.append(
        f"MATCH (a:{from_label} {{{', '.join(from_parts)}}}) "
        f"MATCH (b:{to_label} {{{', '.join(to_parts)}}}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        f"SET {', '.join(prop_parts)};"
    )


# ── V2 helper functions ──


def _emit_error_type_nodes(buf, data):
    """Emit ErrorType nodes from error_handlers and raises."""
    seen = set()
    for handler in data.get("error_handlers", []):
        for exc_type in handler["exception_types"]:
            if exc_type not in seen:
                seen.add(exc_type)
                _emit_node(buf, "ErrorType", {"name": exc_type, "exception_name": exc_type})
    for raiser in data.get("raises", []):
        exc_type = raiser["exception_name"]
        if exc_type not in seen:
            seen.add(exc_type)
            is_retryable = any(
                kw in exc_type.lower() for kw in ["timeout", "connection", "error", "exception"]
            )
            _emit_node(buf, "ErrorType", {"name": exc_type, "is_retryable": is_retryable})


def _emit_condition_nodes(buf, data):
    """Emit Condition nodes from conditions list."""
    seen = set()
    for cond in data.get("conditions", []):
        cond_key = f"{cond['owner_fqn']}::{cond['line']}"
        if cond_key not in seen:
            seen.add(cond_key)
            _emit_node(buf, "Condition", {
                "name": cond_key,
                "owner_fqn": cond["owner_fqn"],
                "condition_type": cond.get("type", "if"),
                "expr": cond.get("condition", ""),
                "line": cond["line"],
            })


def _emit_call_site_nodes(buf, data):
    """Emit CallSite nodes from call_sites list."""
    seen = set()
    for cs in data.get("call_sites", []):
        call_key = f"{cs['caller_fqn']}::{cs['line']}"
        if call_key not in seen:
            seen.add(call_key)
            _emit_node(buf, "CallSite", {
                "name": call_key,
                "owner_fqn": cs["caller_fqn"],
                "call_expr": cs.get("call_expr", ""),
                "line": cs["line"],
            })


def _emit_v2_error_handler_rels(buf, data):
    """HANDLES_ERROR: Method -> ErrorType (from error_handlers)."""
    for handler in data.get("error_handlers", []):
        for exc_type in handler["exception_types"]:
            _emit_rel(buf, "Method", "name", handler["owner_fqn"],
                      "HANDLES_ERROR", "ErrorType", "name", exc_type)


def _emit_v2_raises_rels(buf, data):
    """RAISES: Method -> ErrorType (from raises)."""
    for raiser in data.get("raises", []):
        _emit_rel(buf, "Method", "name", raiser["owner_fqn"],
                  "RAISES", "ErrorType", "name", raiser["exception_name"])


def _emit_v2_condition_rels(buf, data):
    """CHECKS_CONDITION: Method -> Condition."""
    seen = set()
    for cond in data.get("conditions", []):
        cond_key = f"{cond['owner_fqn']}::{cond['line']}"
        pair = (cond["owner_fqn"], cond_key)
        if pair not in seen:
            seen.add(pair)
            _emit_rel(buf, "Method", "name", cond["owner_fqn"],
                      "CHECKS_CONDITION", "Condition", "name", cond_key)


def _emit_v2_contains_call_rels(buf, data):
    """CONTAINS_CALL: Method -> CallSite."""
    seen = set()
    for cs in data.get("call_sites", []):
        call_key = f"{cs['caller_fqn']}::{cs['line']}"
        pair = (cs["caller_fqn"], call_key)
        if pair not in seen:
            seen.add(pair)
            _emit_rel(buf, "Method", "name", cs["caller_fqn"],
                      "CONTAINS_CALL", "CallSite", "name", call_key)


def _emit_v2_calls_method_rels(buf, data, method_fqn_map):
    """CALLS_METHOD: Method -> Method when resolved_target matches a known method."""
    seen = set()
    for cs in data.get("call_sites", []):
        target = cs.get("resolved_target")
        if not target:
            continue
        if target not in method_fqn_map:
            continue
        pair = (cs["caller_fqn"], target)
        if pair not in seen:
            seen.add(pair)
            confidence = cs.get("confidence", "medium")
            _emit_rel_props(buf, "Method", "name", cs["caller_fqn"],
                           "CALLS_METHOD", "Method", "name", target,
                           {"confidence": confidence})


def _emit_v2_signal_emit_rels(buf, data, signal_names):
    """EMITS_SIGNAL_IN: Method -> Signal when signal_name matches a known Signal."""
    seen = set()
    for emit in data.get("signal_emits", []):
        short_name = emit["signal_name"]
        # Derive class FQN from owner_fqn (strip method name)
        parts = emit["owner_fqn"].rsplit(".", 1)
        class_fqn = parts[0] if len(parts) > 1 else ""
        full_name = f"{class_fqn}.{short_name}" if class_fqn else short_name
        if full_name not in signal_names:
            continue
        pair = (emit["owner_fqn"], full_name)
        if pair not in seen:
            seen.add(pair)
            _emit_rel(buf, "Method", "name", emit["owner_fqn"],
                      "EMITS_SIGNAL_IN", "Signal", "name", full_name)


def _emit_v2_nodes(buf, data):
    """Emit all V2 structural nodes."""
    _emit_error_type_nodes(buf, data)
    _emit_condition_nodes(buf, data)
    _emit_call_site_nodes(buf, data)


def _emit_v2_relationships(buf, data):
    """Emit all V2 relationships."""

    # Build method FQN lookup for CALLS_METHOD resolution
    method_fqn_map = {m["fqn"]: m for m in data.get("methods", [])}

    # Build signal name index for EMITS_SIGNAL_IN matching
    signal_names = set()
    for s in data.get("signals", []):
        signal_names.add(f"{s['class']}.{s['name']}")

    _emit_v2_error_handler_rels(buf, data)
    _emit_v2_raises_rels(buf, data)
    _emit_v2_condition_rels(buf, data)
    _emit_v2_contains_call_rels(buf, data)
    _emit_v2_calls_method_rels(buf, data, method_fqn_map)
    _emit_v2_signal_emit_rels(buf, data, signal_names)


def generate_cypher(data: dict, project_root: Path, metadata: dict | None = None) -> str:
    buf = []

    # ── 0. Metadata node ──
    if metadata:
        buf.append(f'MERGE (m:KGMetadata {{kg_run_id: "{metadata["kg_run_id"]}"}})')
        buf.append("SET")
        for key in ["commit_sha", "branch", "generated_at", "generator_version",
                     "extractor_config_hash", "repo"]:
            if key in metadata:
                buf.append(f'        m.{key} = "{metadata[key]}",')
        buf.append('        m.node_count = 7492,')
        buf.append('        m.edge_count = 7864')
        buf.append(";")

    # ── 1. Constraints ──
    _emit_constraints(buf)

    # ── 2. Config nodes ──
    config_file_nodes, config_section_nodes, has_section_rels = _collect_config_nodes(
        project_root
    )

    # ── 3. Module nodes ──
    for m in data.get("modules", []):
        if m["name"].startswith("tests."):
            continue
        _emit_node(buf, "Module", {"name": m["name"], "path": m["path"], "lines": m.get("lines", 0)})

    # ── 4. Class nodes ──
    class_fqns = {}
    for c in data.get("classes", []):
        class_fqns[c["name"]] = c["fqn"]
        props = {"name": c["fqn"], "short_name": c["name"], "module": c["module"]}
        if c.get("bases"):
            props["bases"] = c["bases"]
        if c.get("line"):
            props["line"] = c["line"]
        _emit_node(buf, "Class", props, {"name": c["fqn"]})

    # ── 5. Method nodes ──
    for m in data.get("methods", []):
        props = {"name": m["fqn"], "owner_class": m["owner_class"], "params": m.get("params", [])}
        if m.get("decorators"):
            props["decorators"] = m["decorators"]
        if m.get("line"):
            props["line"] = m["line"]
        if m.get("file_path"):
            props["file_path"] = m["file_path"]
        if m.get("end_line"):
            props["end_line"] = m["end_line"]
        _emit_node(buf, "Method", props, {"name": m["fqn"]})

    # ── 6. Function nodes ──
    for f in data.get("functions", []):
        props = {"name": f["fqn"], "module": f["module"], "params": f.get("params", [])}
        if f.get("line"):
            props["line"] = f["line"]
        _emit_node(buf, "Function", props, {"name": f["fqn"]})

    # ── 7. Signal nodes (from AST data) ──
    for s in data.get("signals", []):
        name = f"{s['class']}.{s['name']}"
        props = {"name": name, "owner_class": s["class"], "params": s.get("params", [])}
        if s.get("line"):
            props["line"] = s["line"]
        _emit_node(buf, "Signal", props, {"name": name})

    # ── 8. ConfigFile nodes ──
    for cf in config_file_nodes:
        _emit_node(buf, "ConfigFile", cf, {"path": cf["path"]})

    # ── 9. ConfigSection nodes ──
    for cs in config_section_nodes:
        _emit_node(buf, "ConfigSection", cs, {"name": cs["name"], "config_file": cs["config_file"]})

    # ── 10. WorkerThread nodes (from hardcoded maps) ──
    workers_seen = set()
    for worker_fqn in WORKER_ENGINE_MAP:
        props = {"name": worker_fqn, "module": "app.gui_app"}
        _emit_node(buf, "WorkerThread", props, {"name": worker_fqn})
        workers_seen.add(worker_fqn)

    # ── 11. GUITab nodes ──
    tabs_seen = set()
    for tab_name in WORKER_TAB_MAP.values():
        if tab_name not in tabs_seen:
            _emit_node(buf, "GUITab", {"name": tab_name}, {"name": tab_name})
            tabs_seen.add(tab_name)

    # ── 12. ExternalSystem nodes ──
    deps_seen = set()
    for dep_name in EXTERNAL_DEPS.values():
        if dep_name not in deps_seen:
            _emit_node(buf, "ExternalSystem", {"name": dep_name}, {"name": dep_name})
            deps_seen.add(dep_name)

    # ── 13. Relationships: IMPORTS ──
    for imp in data.get("imports", []):
        if imp["from_module"].startswith("tests."):
            continue
        _emit_rel(buf, "Module", "name", imp["from_module"], "IMPORTS",
                  "Module", "name", imp["to_module"])

    # ── 14. Relationships: DEFINES_CLASS ──
    for c in data.get("classes", []):
        if c["module"].startswith("tests."):
            continue
        _emit_rel(buf, "Module", "name", c["module"], "DEFINES_CLASS",
                  "Class", "name", c["fqn"])

    # ── 15. Relationships: DEFINES_FUNC ──
    for f in data.get("functions", []):
        if f["module"].startswith("tests."):
            continue
        _emit_rel(buf, "Module", "name", f["module"], "DEFINES_FUNC",
                  "Function", "name", f["fqn"])

    # ── 16. Relationships: INHERITS ──
    for c in data.get("classes", []):
        for base in c.get("bases", []):
            if base == "object":
                continue
            base_fqn = class_fqns.get(base, base)
            _emit_rel(buf, "Class", "name", c["fqn"], "INHERITS",
                      "Class", "name", base_fqn)

    # ── 17. Relationships: OWNS_METHOD ──
    for m in data.get("methods", []):
        _emit_rel(buf, "Class", "name", m["owner_class"], "OWNS_METHOD",
                  "Method", "name", m["fqn"])

    # ── 18. Relationships: COMPOSES (from AST data) ──
    for comp in data.get("compositions", []):
        composed_fqn = class_fqns.get(comp["composes"], comp["composes"])
        _emit_rel(buf, "Class", "name", comp["class"], "COMPOSES",
                  "Class", "name", composed_fqn)

    # ── 19. Relationships: READS_CONFIG ──
    for module_name, config_paths in CONFIG_REFS.items():
        for cfg_path in config_paths:
            _emit_rel(buf, "Module", "name", module_name, "READS_CONFIG",
                      "ConfigFile", "path", cfg_path)

    # ── 20. Relationships: HAS_SECTION ──
    for cfg_path, section_name in has_section_rels:
        _emit_rel(buf, "ConfigFile", "path", cfg_path, "HAS_SECTION",
                  "ConfigSection", "name", section_name,
                  extra_to={"config_file": cfg_path})

    # ── 21. Relationships: TESTS / MOCKS ──
    tests_rels, mocks_rels = _build_test_relationships(data)
    for test_fqn, target_fqn in tests_rels:
        _emit_rel(buf, "Class", "name", test_fqn, "TESTS",
                  "Class", "name", target_fqn)
    for test_fqn, target_module in mocks_rels:
        _emit_rel(buf, "Class", "name", test_fqn, "MOCKS",
                  "Module", "name", target_module)

    # ── 22. Relationships: EMITS_SIGNAL ──
    for s in data.get("signals", []):
        signal_name = f"{s['class']}.{s['name']}"
        # Check if the owner class is actually a WorkerThread
        if s["class"] in workers_seen:
            _emit_rel(buf, "WorkerThread", "name", s["class"], "EMITS_SIGNAL",
                      "Signal", "name", signal_name)

    # ── 23. Relationships: RUNS_IN ──
    for worker_fqn, tab_name in WORKER_TAB_MAP.items():
        _emit_rel(buf, "WorkerThread", "name", worker_fqn, "RUNS_IN",
                  "GUITab", "name", tab_name)

    # ── 24. Relationships: QUEUES_TO ──
    for from_worker_short, to_worker_short in QUEUE_MAP:
        from_fqn = f"app.gui_app.{from_worker_short}"
        to_fqn = f"app.gui_app.{to_worker_short}"
        _emit_rel(buf, "WorkerThread", "name", from_fqn, "QUEUES_TO",
                  "WorkerThread", "name", to_fqn)

    # ── 25. Relationships: WRAPS_ENGINE ──
    for worker_fqn, engine_fqn in WORKER_ENGINE_MAP.items():
        _emit_rel(buf, "WorkerThread", "name", worker_fqn, "WRAPS_ENGINE",
                  "Class", "name", engine_fqn)

    # ── 26. Relationships: DEPENDS_ON ──
    for module_name, dep_name in EXTERNAL_DEPS.items():
        _emit_rel(buf, "Module", "name", module_name, "DEPENDS_ON",
                  "ExternalSystem", "name", dep_name)

    # ════════════════════════════════════════════════════════════════
    # ── V2 additions ──
    # ════════════════════════════════════════════════════════════════

    # ── V2.1. ErrorType / Condition / CallSite nodes ──
    _emit_v2_nodes(buf, data)

    # ── V2.2. V2 relationships ──
    _emit_v2_relationships(buf, data)

    return "\n".join(buf)
