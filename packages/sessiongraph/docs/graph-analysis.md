# Structural graph analysis and visualization

SessionGraph's default analyzer remains standard-library-only. The optional
`graph` and `visual` extras add NetworkX measurements and a self-contained PyVis
HTML explorer without changing parsing, findings, or workflow-health scoring.

```bash
python -m pip install -e ".[visual]"
sessiongraph analyze session.jsonl --out .sessiongraph/run
sessiongraph graph-metrics .sessiongraph/run/analysis.json \
  --out .sessiongraph/run/graph-metrics.json
sessiongraph visualize .sessiongraph/run/analysis.json \
  --out .sessiongraph/run/graph.html
```

## Typed edges

Generic JSONL events can declare a `parent_relations` object. Each key must name
one of the event's declared parents; each value is a nonempty label no longer
than 64 characters.

```json
{"id":"request","kind":"user_request","parent_ids":[]}
{"id":"run","kind":"agent_run","parent_ids":["request"],"parent_relations":{"request":"requested"}}
{"id":"artifact","kind":"artifact","parent_ids":["run"],"parent_relations":{"run":"modified"}}
{"id":"test","kind":"test_run","parent_ids":["artifact"],"parent_relations":{"artifact":"verified_by"}}
```

Relations are producer assertions. SessionGraph preserves and displays them; it
does not infer that an input influenced a model or that a test proves correctness.
Omitted relations use `precedes` for compatibility with existing traces.

## Measurements

`graph-metrics` reports declared and implicit nodes, edges, roots, leaves, weakly
connected components, cycle nodes, maximum DAG depth, relation counts,
request-to-output reachability, and modified-artifact verification coverage.
Every aggregate that affects coverage has an evidence list of node IDs.

An artifact is counted as changed when it is the target of a `created` or
`modified` edge. It is counted as verified when it has an outgoing `verified_by`
edge to a recorded, non-error test node. This is verification-record coverage,
not a judgment about test quality.

## Visualization boundary

The HTML explorer uses only `analysis.json` graph nodes and edges. It does not
copy the `events` array or transcript fields. IDs are replaced with safe local
rendering IDs, while escaped original IDs appear in hover details. Dependencies
are embedded so the resulting HTML opens without a server or network connection.

See [`../examples/artifact-lineage.jsonl`](../examples/artifact-lineage.jsonl)
for a synthetic end-to-end example.
