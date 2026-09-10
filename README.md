# SessionGraph

SessionGraph is a local-first analyzer for coding-agent sessions. It reads Pi v3 session JSONL, agentctl improvement-loop traces, or a small generic JSONL format; builds an interaction graph; detects repeated/alternating loops, agent timeouts, and dead ends; and produces an evidence-backed Markdown report. It never calls a model or network service.

**Scope.** SessionGraph is a triage tool for *session and loop health*: it ranks recorded sessions by workflow health and surfaces repeated-action loops, dead ends, unrecovered errors, agent timeouts, and user-correction turns, so you can find the sessions worth investigating. It is **not** an agent-quality, routing, or answer-correctness evaluator — it observes what happened in a session, not whether the agent chose the right tool, model, or answer.

The default output omits transcript and tool-argument content. Findings reference event IDs and stable, redacted fingerprints. Content is included only with an explicit `--include-content` flag and is still passed through secret and PII redaction.

## Quick start

```bash
cd sessiongraph
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
sessiongraph analyze tests/fixtures/pi-loop.jsonl --out sessiongraph-report
open sessiongraph-report/report.md
```

Find locally stored Pi sessions without reading their contents:

```bash
sessiongraph discover
```

Analyze one explicitly selected session:

```bash
sessiongraph analyze ~/.pi/agent/sessions/<project>/<session>.jsonl --out .sessiongraph/baseline
```

The outputs are:

- `analysis.json`: metrics, content-free graph, findings, and sanitized event records;
- `report.md`: human-readable evidence and recommendations;
- `graph.mmd`: a Mermaid interaction graph.

## Closed improvement loop

SessionGraph separates observation from causal evaluation:

```text
session -> deterministic findings -> suggest-workflow (optional)
        -> human / Claude Workflow / agentctl applies sketch
        -> comparable candidate sessions -> before/after comparison -> keep or roll back
```

Analyze baseline and candidate sessions, then compare them:

```bash
sessiongraph analyze baseline.jsonl --out .sessiongraph/baseline
sessiongraph analyze candidate.jsonl --out .sessiongraph/candidate
sessiongraph compare .sessiongraph/baseline/analysis.json .sessiongraph/candidate/analysis.json
```

Emit a **suggested dynamic workflow** from findings (stdlib-only; never auto-runs agents):

```bash
sessiongraph suggest-workflow .sessiongraph/baseline/analysis.json --target markdown --out .sessiongraph/suggest-md
sessiongraph suggest-workflow .sessiongraph/baseline --target claude --out .sessiongraph/suggest-claude
sessiongraph suggest-workflow .sessiongraph/baseline --target agentctl --out .sessiongraph/suggest-agentctl
```

| `--target` | Primary artifacts |
|------------|-------------------|
| `markdown` | `workflow.md` DAG + experiment |
| `claude` | `workflow.js` sketch (`agent` / `parallel` / `pipeline` / `phase` / `budget`) |
| `agentctl` | `task.md` + `run.yaml` + `rubric.md` (operator runs `agentctl` separately) |

Always also writes `manifest.json`, `rationale.md`, and a copy of `analysis.json`. Mapping version: `suggest-map-v1`. See [`docs/suggest-workflow.md`](docs/suggest-workflow.md).

For a generic critique-and-revision loop (less topology-aware), `prepare-loop` remains available:

```bash
sessiongraph prepare-loop .sessiongraph/baseline/report.md --out .sessiongraph/agentctl-loop
agentctl run .sessiongraph/agentctl-loop
```

Analyze the resulting control loop itself:

```bash
sessiongraph analyze .sessiongraph/agentctl-loop/trace.jsonl --out .sessiongraph/agentctl-loop-analysis
```

Agentctl traces are recognized from their lifecycle events. SessionGraph reconstructs the
unrolled `generate → validate → evaluate → decision → retry/finish` graph and reports loop
iterations, retry count, final status, stage duration, bottlenecks, failed stages, and timeouts
without copying prompts or candidate text.

`agentctl run` mutates its checkpoint and creates candidate/evaluation artifacts. The generated task embeds only the content-free report, not the source transcript. `loop-run/` contains the human-readable configuration and rubric used by `prepare-loop`. Prefer `suggest-workflow --target agentctl` when you want finding→topology budgets instead of a generic improvement prompt.

## CodeCollector retrieval reports

Analyze saved JSON from `insane_research_standalone/standalone_fetch.py`:

```bash
sessiongraph analyze-retrieval baseline-fetch.json --out baseline-analysis
sessiongraph analyze-retrieval candidate-fetch.json --out candidate-analysis
sessiongraph compare baseline-analysis/analysis.json candidate-analysis/analysis.json
```

This offline adapter reads the producer's pretty-printed JSON directly. It records
attempt order, unsuccessful attempts, elapsed seconds, final success, and deferred
browser escalation. It excludes URLs, content, headers, and error text. Both
`strong_ok` and `weak_ok` count as successful attempts, matching the producer.
Non-successful attempts followed by a successful retrieval are retained as metrics,
without marking the whole retrieval as failed.

Compare the same sources and success requirements across real runs before changing
retrieval policy. Fewer attempts alone does not establish better retrieval quality.
SessionGraph supplies observation and comparison; it does not execute or tune the
retrieval engine automatically.

Offline verification with the sibling CodeCollector producer installed locally:

```bash
PYTHONPATH=src python3 tests/replay_codecollector_retrieval.py
PYTHONPATH=src python3 tests/benchmark_export.py
```

The replay uses actual producer classes with a mocked fetch; its candidate is
synthetic and proves integration compatibility, not a real policy speedup.

## Pi command

After installing the CLI, copy or symlink `pi-extension/sessiongraph.ts` into `.pi/extensions/` in a trusted project. Restart Pi or use `/reload`, then:

```text
/sessiongraph .sessiongraph/current
```

Pi extensions run with the user's full permissions. Review the extension before installing it. This one resolves the active persisted session and invokes the local `sessiongraph` executable.

## Generic JSONL

Each line is an event object. Supported fields include `id`, `parent_id`, `type` or `kind`, `role`, `name` / `tool_name`, `content` / `text`, `arguments`, `timestamp`, `is_error`, and `usage`. Missing IDs and parent links are filled as a linear trace.

```json
{"id":"1","role":"user","content":"Fix the test"}
{"id":"2","parent_id":"1","type":"tool_call","name":"test","arguments":{"suite":"unit"}}
{"id":"3","parent_id":"2","type":"tool_result","name":"test","is_error":true,"content":"failed"}
```

## Detector semantics

- `repeated_action`: the same canonical tool name and arguments appears three times inside eight tool calls, at least two attempts fail, and none records recovery;
- `alternating_loop`: tool signatures form A-B-A-B with at least two failed results;
- `errors`: unrecovered errored tool results or aborted messages occurred — an errored tool call whose same signature succeeds later in the session is treated as recovered and excluded, so the count reflects failures the run never got past;
- `user_correction`: a user turn contains an English correction phrase;
- `dead_end`: the final recorded event is errored or aborted;
- `dangling_edges`: a parent referenced by the selected branch is absent.

These are review signals, not diagnoses of model intent. `workflow_health` is a deterministic triage score, not a quality benchmark.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m compileall -q src tests
```

See [RESEARCH.md](RESEARCH.md) for similar projects, design boundaries, and sources.
