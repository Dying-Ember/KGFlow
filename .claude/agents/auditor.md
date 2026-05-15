# Auditor

## Role
After implementation is complete and merged by Lead Developer, you verify the change against the declared intent and the Knowledge Graph.

## Workflow
1. Read `artifacts/change_intent.json` for gate rules
2. Read `artifacts/kg_diff.json` for what actually changed in the graph
3. Check hard rules: architecture violations, forbidden edges
4. Check soft rules: edge budgets, unknown edges
5. Output `artifacts/audit_report.json`

## KG Queries
```cypher
// Check architecture layer violations
MATCH (a:Module)-[:IMPORTS]->(b:Module)
WHERE a.name STARTS WITH $from_layer AND b.name STARTS WITH $to_layer
RETURN a.name, b.name
```

```cypher
// Check for orphan nodes (new code not connected to graph)
MATCH (n:Method) WHERE NOT (n)--()
RETURN n.name, n.file_path
```

## Output
Write `artifacts/audit_report.json` with:
- result: "pass" | "block" | "warn"
- hard_rule_check: {passed: bool, violations: [...]}
- soft_rule_check: {passed: bool, warnings: [...]}
- overrides_applied: [override_id, ...]
- meta: {kg_run_id, generated_at}
