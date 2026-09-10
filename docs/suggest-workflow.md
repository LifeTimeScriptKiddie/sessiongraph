# `suggest-workflow`

Full design: [`atoz/projects/sessiongraph/design-suggest-workflow-2026-09-10.md`](../../../atoz/projects/sessiongraph/design-suggest-workflow-2026-09-10.md)

**Status:** implemented (`suggest-map-v1`) in `src/sessiongraph/suggest.py`.

## CLI

```bash
sessiongraph suggest-workflow <analysis.json|report-dir|session.jsonl> \
  --target claude|pi|agentctl|markdown \
  [--out DIR] [--task "…"] [--max-findings 3] [--include-healthy]
```

## Outputs

| Target | Primary artifact |
|--------|------------------|
| `markdown` | `workflow.md` DAG + experiment |
| `claude` | `workflow.js` sketch (`export async function run` + `agent` / `parallel` / `phase` / `budget`) |
| `pi` | `workflow.js` for **pi-dynamic-workflows** (`export const meta` first; top-level `await` / `return`; no `run()` wrapper) |
| `agentctl` | `task.md` + `run.yaml` + `rubric.md` (no auto-run) |

Always: `manifest.json`, `rationale.md`, provenance `analysis.json`.

### `--target pi` contract

Sketches must satisfy pi-dynamic-workflows `parseWorkflowScript`:

1. First statement: `export const meta = { name, description, phases? }` (literal only)
2. Body uses globals `agent` / `parallel` / `pipeline` / `phase` / `log` / `args` / `budget`
3. No `Date.now()`, `Math.random()`, or `new Date()`
4. Task via `const task = (args && args.task) || "…"` (operator overrides with tool `args`)

SessionGraph never installs or invokes pi-dynamic-workflows; the operator pastes/runs the sketch in Pi.

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
| `pipeline_contract` | CheckContract → RepairProducer → VerifyArtifacts |

Deterministic, stdlib-only, no model calls, no silent repo edits. One primary spine from highest-severity / spine-priority finding; secondary findings become guards.
