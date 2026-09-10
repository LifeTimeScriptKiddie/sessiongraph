# `suggest-workflow`

Full design: [`atoz/projects/sessiongraph/design-suggest-workflow-2026-09-10.md`](../../../atoz/projects/sessiongraph/design-suggest-workflow-2026-09-10.md)

**Status:** implemented (`suggest-map-v1`) in `src/sessiongraph/suggest.py`.

## CLI

```bash
sessiongraph suggest-workflow <analysis.json|report-dir|session.jsonl> \
  --target claude|agentctl|markdown \
  [--out DIR] [--task "…"] [--max-findings 3] [--include-healthy]
```

## Outputs

| Target | Primary artifact |
|--------|------------------|
| `markdown` | `workflow.md` DAG + experiment |
| `claude` | `workflow.js` sketch (`agent` / `parallel` / `pipeline` / `phase` / `budget`) |
| `agentctl` | `task.md` + `run.yaml` + `rubric.md` (no auto-run) |

Always: `manifest.json`, `rationale.md`, provenance `analysis.json`.

## Finding → topology (v1)

| Code | Move |
|------|------|
| `repeated_action` | RetryBudget(2) + must change hypothesis |
| `alternating_loop` | Checkpoint / strategy fork |
| `errors` | Classify before retry |
| `dead_end` | Required terminal handoff schema |
| `user_correction` | Preflight checklist node |
| `agent_timeout` | Fallback edge + preserve branches |
| `loop_bottleneck` | Fast pass → conditional escalate |
| `dangling_edges` | Warn; no invented lineage |
| `escalation_deferred` | Explicit escalation gate |

Deterministic, stdlib-only, no model calls, no silent repo edits. One primary spine from highest-severity / spine-priority finding; secondary findings become guards.
