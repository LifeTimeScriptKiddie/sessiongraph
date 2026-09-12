# Read-only benchmark task

Inspect only these raw JSONL graphs in the current benchmark directory:

- `raw/artifact-lineage.jsonl`
- `raw/cycle.jsonl`
- `raw/disconnected.jsonl`
- `raw/failed-test.jsonl`

Do not inspect files outside the current benchmark directory. Do not execute code,
SessionGraph, NetworkX, tests, searches outside these four files, or network requests. Treat every
`parent_id`/`parent_ids` relationship as a directed parent-to-event edge. An undeclared
parent is an implicit node. Maximum depth is the longest directed path in edge count and
is null for a cyclic graph. A changed artifact is the target of `created` or `modified`.
It is verified only when it has an outgoing `verified_by` edge to a non-error test node.
A response is covered when reachable from a `user_request` node.

Return only one JSON object with exactly these keys and JSON number/boolean values:

```json
{
  "artifact_is_dag": null,
  "artifact_max_depth": null,
  "artifact_components": null,
  "artifact_request_output_coverage": null,
  "artifact_changed_artifacts": null,
  "artifact_verified_artifacts": null,
  "cycle_is_dag": null,
  "cycle_cycle_nodes": null,
  "cycle_implicit_nodes": null,
  "disconnected_components": null,
  "disconnected_request_output_coverage": null,
  "failed_test_artifact_verification_coverage": null
}
```
