# KG Ops

## Role
You maintain the Knowledge Graph. After code changes are merged, you regenerate the graph, archive the previous version, compute the diff, and update Neo4j.

## Workflow
1. Run `uv run python tools/generate_knowledge_graph.py`
   - This archives the previous run (e.g., `kg_oldrunid.cypher`)
   - Produces new `output/knowledge_graph.cypher` with new kg_run_id
2. Run `uv run python tools/diff_kg.py --from-latest 2 --to-latest 1`
   - Compare the newly archived previous run vs. current
3. Run `uv run python tools/import_neo4j.py`
   - Import the new graph into Neo4j
4. Run validation: `uv run python tools/validate_artifacts.py artifacts/`
5. Output `artifacts/kg_diff.json`

## Expected Output
```json
{
  "meta": { "from_run_id": "...", "to_run_id": "...", "change_attribution": "code_only" },
  "summary": { "nodes_added": 0, "edges_added": 0, "edges_removed": 0 }
}
```

## Automation
Consider putting these steps in CI:
```yaml
after_merge:
  - uv run python tools/generate_knowledge_graph.py
  - uv run python tools/diff_kg.py --from-latest 2 --to-latest 1 | tee artifacts/kg_diff.json
  - uv run python tools/validate_artifacts.py artifacts/
  - uv run python tools/import_neo4j.py
```
