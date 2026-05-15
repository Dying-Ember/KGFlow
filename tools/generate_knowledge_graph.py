#!/usr/bin/env python3
"""Generate Neo4j knowledge graph Cypher script using auto-detected language extractor.

Run from KGFlow project root:
  uv run python tools/generate_knowledge_graph.py [--project-dir PATH]
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

KGFLOW_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KGFLOW_ROOT))

from extractors import detect_language, create_extractor
from tools.cypher_generator import generate_cypher

DEFAULT_PROJECT = Path(r"D:\PythonProgramming\1\Automation-Inspection")
GENERATOR_VERSION = "2.0.0"
KGFLOW_REPO = "Dying-Ember/automation-insight-kgflow"


def _get_git_info(project_dir: Path):
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_dir), text=True, stderr=subprocess.DEVNULL
        ).strip()[:12]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(project_dir), text=True, stderr=subprocess.DEVNULL
        ).strip()
        return sha, branch
    except Exception:
        return "unknown", "unknown"


def _build_kg_run_id(commit_sha: str, generated_at: datetime, extractor_hash: str) -> str:
    raw = f"{commit_sha}:{generated_at.isoformat()}:{GENERATOR_VERSION}:{extractor_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _build_extractor_hash() -> str:
    return hashlib.sha256(json.dumps({
        "generator_version": GENERATOR_VERSION,
        "confidence_rules_version": "1.0",
        "excluded_dirs": [
            "__pycache__", ".venv", "venv", "dist", "build",
            ".git", ".pytest_cache", "node_modules",
        ],
    }, sort_keys=True).encode()).hexdigest()[:8]


def main():
    parser = argparse.ArgumentParser(description="Generate KGFlow knowledge graph")
    parser.add_argument("--project-dir", default=str(DEFAULT_PROJECT),
                        help="Path to the source code project to analyze")
    parser.add_argument("--language", default=None,
                        help="Force language (skip auto-detection)")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    commit_sha, branch = _get_git_info(project_dir)
    generated_at = datetime.now(timezone.utc)
    extractor_hash = _build_extractor_hash()

    print(f"Target project: {project_dir}")

    # Auto-detect language or use override
    if args.language:
        lang = args.language
    else:
        lang = detect_language(project_dir)
    print(f"  language: {lang}")

    # Create extractor and run
    extractor = create_extractor(lang, project_dir)
    result = extractor.extract()

    data = result["data"]
    coverage = result["coverage"]
    kg_run_id = _build_kg_run_id(commit_sha, generated_at, extractor_hash)

    print(f"  commit: {commit_sha}")
    print(f"  branch: {branch}")
    print(f"  kg_run_id: {kg_run_id}")
    print(f"  coverage: {coverage['files_parsed_ok']}/{coverage['files_scanned']} files OK, "
          f"{coverage['functions_found']} functions, "
          f"{coverage['calls_found']} calls, "
          f"{coverage['classes_found']} classes")

    metadata = {
        "kg_run_id": kg_run_id,
        "commit_sha": commit_sha,
        "branch": branch,
        "generated_at": generated_at.isoformat(),
        "generator_version": GENERATOR_VERSION,
        "extractor_config_hash": extractor_hash,
        "language": lang,
        "extractor_version": extractor.extractor_version,
        "repo": KGFLOW_REPO,
    }

    cypher = generate_cypher(data, project_dir, metadata=metadata)

    # Archive previous output
    output_dir = KGFLOW_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    current_cypher = output_dir / "knowledge_graph.cypher"
    if current_cypher.exists():
        old_text = current_cypher.read_text(encoding="utf-8")
        m = re.search(r'kg_run_id:\s*"([a-f0-9]{12})"', old_text)
        if m:
            old_run_id = m.group(1)
            archived = output_dir / f"kg_{old_run_id}.cypher"
            if not archived.exists():
                current_cypher.rename(archived)
                print(f"Archived previous: kg_{old_run_id}.cypher")

    output_path = output_dir / "knowledge_graph.cypher"
    output_path.write_text(cypher, encoding="utf-8")
    lines = cypher.splitlines()
    print(f"Generated: {output_path} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
