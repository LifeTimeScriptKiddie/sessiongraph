# `suggest-workflow`


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

**Emission order (multi-fault):** the primary spine owns the body. A `repeated_action` guard adds `RetryBudget(2)` / retry phases **after** the spine (or before `Verify`/`VerifyArtifacts` in markdown) — it does not replace a `pipeline_contract` body.

## Scorecard (accuracy gates)

Accuracy for suggested workflows means **measurable session/pipeline health improvement**, not LLM taste and not answer correctness.

```bash
sessiongraph scorecard baseline/analysis.json candidate/analysis.json
sessiongraph scorecard baseline/analysis.json candidate/analysis.json \
  --min-health-delta 1 --max-finding-delta 0 --out scorecard.json
```

Default gates (`suggest-scorecard-v2`):

| Gate | Pass when |
|------|-----------|
| `workflow_health_delta` | `>= --min-health-delta` (default 1) |
| `finding_delta` | `<= --max-finding-delta` (default 0 = not increase) |
| `no_new_dangling_edges` | candidate does not invent `dangling_edges` |
| `no_new_critical_findings` | no new critical codes vs baseline |
| `agentctl_evidence_available` | for agentctl comparisons, both analyses explicitly record a terminal event and zero unclassified stage failures |

Re-analyze old agentctl exports before using this gate. A terminal record is a minimum
coverage check, not proof of complete event ordering or artifact correctness. Missing
failure classifications remain unknown; long durations alone do not prove timeouts.
`failed_gates` identifies why a scorecard failed even when health increased.

`loop_incomplete` and `loop_telemetry_gap` suggestions add capture preflight guidance.
They are observation-repair sketches; they do not certify a new trace or automatically
instrument a controller. Repairing instrumentation can reveal more failures and lower
health. Evaluate that work against fixed external checks, not a health-increase gate.

Exit code `0` = all gates pass, `1` = fail, `2` = usage/IO error.

Golden topology fixtures live in `tests/fixtures/suggest-matrix/` and are asserted by `tests/test_suggest_scorecard.py` (same findings → same graph digest).

## Targets and portability

| Target | Role |
|--------|------|
| `pi` / `claude` / `markdown` | **Portable emit** — run elsewhere without SessionGraph or agentctl |
| `agentctl` | **Local cockpit artifact only** (task + rubric on this Mac). SessionGraph never auto-runs agentctl; other machines do not need it. |

agentctl may be used on the development host to research, review, or patch SessionGraph itself. It is not a runtime dependency of suggested workflows.
