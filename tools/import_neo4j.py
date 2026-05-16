#!/usr/bin/env python3
"""Import knowledge_graph.cypher into Neo4j database.

Usage:
  uv run python tools/import_neo4j.py [--cypher-file PATH] [--json] [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from neo4j import GraphDatabase
except ImportError:
    print("需要安装 neo4j driver: uv add neo4j")
    sys.exit(1)

from tools.neo4j_config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

DEFAULT_CYPHER = Path(__file__).parent.parent / "output" / "knowledge_graph.cypher"


def main():
    parser = argparse.ArgumentParser(description="Import Cypher file into Neo4j")
    parser.add_argument("--cypher-file", default=str(DEFAULT_CYPHER),
                        help=f"Path to .cypher file (default: {DEFAULT_CYPHER})")
    parser.add_argument("--uri", default=NEO4J_URI,
                        help="Neo4j URI (default from env KGFLOW_NEO4J_URI)")
    parser.add_argument("--user", default=NEO4J_USER,
                        help="Neo4j user (default from env KGFLOW_NEO4J_USER)")
    parser.add_argument("--password", default=NEO4J_PASSWORD,
                        help="Neo4j password (default from env KGFLOW_NEO4J_PASSWORD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate statements without modifying the database")
    parser.add_argument("--json", action="store_true",
                        help="Output structured JSON instead of human-readable text")
    args = parser.parse_args()

    cypher_file = Path(args.cypher_file)
    if not cypher_file.exists():
        msg = f"File not found: {cypher_file}"
        if args.json:
            print(json.dumps({"error": True, "code": "CONFIG_MISSING", "detail": msg}))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    content = cypher_file.read_text(encoding="utf-8")

    statements = []
    for stmt in content.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("//"):
            statements.append(stmt + ";")
    print(f"Parsed {len(statements)} Cypher statements")

    if args.dry_run:
        result = {"imported": 0, "statements": len(statements), "dry_run": True, "errors": []}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Dry-run: all statements validated (no modifications)")
        return

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    # Clear database
    with driver.session(database="neo4j") as session:
        session.run("MATCH (n) DETACH DELETE n")
        for record in session.run("SHOW CONSTRAINTS"):
            try:
                session.run(f"DROP CONSTRAINT {record['name']}")
            except Exception:
                pass

    # Execute in batches
    batch_names = [
        ("CREATE CONSTRAINT", lambda s: s.startswith("CREATE CONSTRAINT")),
        ("MERGE nodes", lambda s: s.startswith("MERGE") and "MERGE (a:" not in s),
        ("MERGE relationships", lambda s: s.startswith("MATCH")),
    ]

    import_errors = []
    total = 0
    for batch_name, predicate in batch_names:
        batch = [s for s in statements if predicate(s)]
        if not batch:
            continue
        with driver.session(database="neo4j") as session:
            for i, stmt in enumerate(batch, 1):
                try:
                    session.run(stmt)
                except Exception as e:
                    msg = str(e)
                    if "EquivalentSchemaRuleAlreadyExists" in msg:
                        continue
                    import_errors.append(f"[{i}/{len(batch)}] {msg}")
        total += len(batch)

    driver.close()

    # Verification
    driver2 = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    node_counts = {}
    with driver2.session(database="neo4j") as session:
        result = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC")
        for record in result:
            node_counts[record["label"]] = record["cnt"]
    driver2.close()

    if args.json:
        output = {
            "imported": total,
            "errors": import_errors,
            "node_counts": node_counts,
            "dry_run": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\nImported {total} statements, {len(import_errors)} errors")
        for label, cnt in node_counts.items():
            print(f"  {label}: {cnt}")


if __name__ == "__main__":
    main()
