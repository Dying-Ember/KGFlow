"""KGFlow MCP Server — exposes all tools to AI agents via typed protocol.

Run:
  uv run python tools/mcp_server.py

Or via Claude Code settings.json:
  "mcpServers": {
    "kgflow": {
      "command": "uv",
      "args": ["run", "kgflow-mcp"],
      "env": {"KGFLOW_NEO4J_PASSWORD": "your-password"}
    }
  }
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

KGFLOW_ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> dict[str, Any]:
    """Run a kgflow CLI tool with --json and return parsed output."""
    cmd = ["uv", "run", "python"] + list(args)
    result = subprocess.run(
        cmd,
        cwd=str(KGFLOW_ROOT),
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        # Try to parse structured error from stderr
        try:
            err = json.loads(result.stderr)
            return {"error": True, "code": err.get("code", "UNKNOWN"), "detail": err.get("detail", result.stderr)}
        except (json.JSONDecodeError, ValueError):
            return {"error": True, "code": "CLI_ERROR", "detail": result.stderr}
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": True, "code": "PARSE_ERROR", "detail": str(e), "raw": result.stdout}


mcp = FastMCP(
    "KGFlow",
    instructions="Knowledge Graph Assisted Development workflow — analyze code structure, "
                "check parallel safety, trace call chains, and validate architecture rules.",
)


# ── Generate ──────────────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_generate",
    description="Generate knowledge graph Cypher from source code. "
                "Optionally run CI coverage checks with --ci-only.",
)
async def kgflow_generate(
    project_dir: str | None = None,
    language: str | None = None,
    ci: bool = False,
) -> dict[str, Any]:
    """Generate Neo4j knowledge graph from source code.

    Args:
        project_dir: Path to the source project (default: from kgflow.toml)
        language: Force language (skip auto-detection)
        ci: CI mode — only check coverage thresholds, don't generate cypher
    """
    args = [str(KGFLOW_ROOT / "tools" / "generate_knowledge_graph.py"), "--json"]
    if project_dir:
        args += ["--project-dir", project_dir]
    if language:
        args += ["--language", language]
    if ci:
        args += ["--ci"]
    return _run(*args)


# ── Query: impact ─────────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_impact",
    description="Find all methods/classes/config affected by changing given methods.",
)
async def kgflow_query_impact(
    methods: list[str],
    depth: int = 3,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "impact",
            "--methods", json.dumps(methods),
            "--depth", str(depth),
            "--timeout-ms", str(timeout_ms)]
    return _run(*args)


# ── Query: call-chain ─────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_call_chain",
    description="Trace call chain up (callers) or down (callees) from a method.",
)
async def kgflow_query_call_chain(
    method: str,
    direction: str = "down",
    depth: int = 3,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "call-chain",
            "--method", method,
            "--direction", direction,
            "--depth", str(depth),
            "--timeout-ms", str(timeout_ms)]
    return _run(*args)


# ── Query: check-parallel ─────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_check_parallel",
    description="Gate 2 parallel safety check — determine if two tasks can run concurrently.",
)
async def kgflow_query_check_parallel(
    task_a_methods: list[str],
    task_b_methods: list[str],
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "check-parallel",
            "--task-a-methods", json.dumps(task_a_methods),
            "--task-b-methods", json.dumps(task_b_methods),
            "--timeout-ms", str(timeout_ms)]
    return _run(*args)


# ── Query: cross-layer ────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_cross_layer",
    description="Check architecture layer dependency violations (e.g. engine importing app).",
)
async def kgflow_query_cross_layer(
    from_layer: str | None = None,
    to_layer: str | None = None,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "cross-layer",
            "--timeout-ms", str(timeout_ms)]
    if from_layer:
        args += ["--from-layer", from_layer]
    if to_layer:
        args += ["--to-layer", to_layer]
    return _run(*args)


# ── Query: resolve-changes ────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_resolve_changes",
    description="Map git diff file changes to KG Method nodes with line-level confidence.",
)
async def kgflow_query_resolve_changes(
    project_root: str,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "resolve-changes",
            "--project-root", project_root,
            "--timeout-ms", str(timeout_ms)]
    return _run(*args)


# ── Query: config-readers ─────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_config_readers",
    description="Find which modules read a given configuration file.",
)
async def kgflow_query_config_readers(
    config_key: str,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "config-readers",
            "--config-key", config_key,
            "--timeout-ms", str(timeout_ms)]
    return _run(*args)


# ── Query: orphans ────────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_query_orphans",
    description="Find nodes with no relationships (potential dead code or incorrect extraction).",
)
async def kgflow_query_orphans(
    label: str | None = None,
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "query_kg.py"), "orphans",
            "--timeout-ms", str(timeout_ms)]
    if label:
        args += ["--label", label]
    return _run(*args)


# ── Diff ──────────────────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_diff",
    description="Compare two knowledge graph runs and output node/edge diffs.",
)
async def kgflow_diff(
    from_latest: int | None = None,
    to_latest: int | None = None,
    from_run: str | None = None,
    to_run: str | None = None,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "diff_kg.py")]
    if from_latest:
        args += ["--from-latest", str(from_latest)]
    if to_latest:
        args += ["--to-latest", str(to_latest)]
    if from_run:
        args += ["--from-run", from_run]
    if to_run:
        args += ["--to-run", to_run]
    return _run(*args)


# ── Validate ──────────────────────────────────────────────────────────────

@mcp.tool(
    name="kgflow_validate",
    description="Validate KGFlow artifact JSON files (L1/L2/L3 cross-reference checks).",
)
async def kgflow_validate(
    paths: list[str],
    ci: bool = False,
) -> dict[str, Any]:
    args = [str(KGFLOW_ROOT / "tools" / "validate_artifacts.py"), "--json"]
    if ci:
        args += ["--ci"]
    args.extend(paths)
    return _run(*args)


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    mcp.run()

if __name__ == "__main__":
    mcp.run()
