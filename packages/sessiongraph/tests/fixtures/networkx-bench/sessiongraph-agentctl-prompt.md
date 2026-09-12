# Read-only benchmark task

Answer the graph questions using only the recorded SessionGraph measurement files in
the current benchmark directory:

- `artifact-lineage/graph-metrics.json`
- `cycle/graph-metrics.json`
- `disconnected/graph-metrics.json`
- `failed-test/graph-metrics.json`

Do not inspect files outside the current benchmark directory. Do not execute code,
SessionGraph, NetworkX, tests, searches outside these four files, or network requests.
Treat the measurements as producer output to report, not as proof of model reasoning
or answer quality.

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
