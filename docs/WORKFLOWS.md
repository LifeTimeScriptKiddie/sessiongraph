# Workflow mining: see repeated workflows, and know when to engineer them

`sessiongraph workflows` looks across sessions, not inside one. It finds the workflows you repeat through a harness, draws them, and gives each one of three verdicts, always with reasons:

| Verdict | Meaning | What happens |
| --- | --- | --- |
| **observe only** | Not enough evidence, or the workflow repeats and runs cleanly | Visualize only. The reasons say which. |
| **cheap fix** | A setting or routing change has a clear expected saving | A recommendation with its metric, no new loop |
| **engineer it** | The workflow repeats and has a real problem | A recommendation to codify it (skill, slash command, rule, task template), with the metric that must move |

Graph or loop engineering costs design time, evaluation runs and harness complexity. Most of the time the right answer is "observe only", and the tool says so plainly instead of inventing work.

## Run it

```sh
sessiongraph workflows --claude-code ~/.claude/projects --since 14d --out out/
# add agentctl, Pi or generic sessions (one request per session):
sessiongraph workflows --claude-code ~/.claude/projects --sessions exports/*.jsonl --out out/
# size the lookup fix with a measured effort sweep (agentctl bench-effort):
sessiongraph workflows --claude-code ~/.claude/projects --effort-evidence effort-sweep.json --out out/
```

With agentctl, `agentctl graph workflows` runs this over Claude Code transcripts plus agentctl's own job graphs, and uses the newest `bench-effort` result automatically.

Output (all content-free):

- `workflows.html`: an overview of families and verdicts. For each family: the reasons, the recommendation, the directly-follows graph with the typical path in green, and the variants.
- `workflows.md`: the same as a table.
- `workflows.json`: the data. Schema `sessiongraph.workflows.v1`.

## How it works

1. **Requests.** A request is one user turn and everything the agent did for it. For Claude Code the reader uses only `type`, `timestamp`, the model id, usage, content block types, tool names, tool-result error flags and the `<command-name>` marker. Tool arguments are inspected only to classify a Bash command, and are never stored. Housekeeping commands (`/clear`, `/model`, `/mcp` …) are not workflows. Claude Code calls its transcript format internal, so this reader is the fallback; OpenTelemetry (redacted by default) is the stable surface to add next.
2. **Phases.** Each tool call becomes a phase: `explore`, `edit`, `test`, `build`, `commit`, `delegate`, `subagent`, `web`, `skill` or `shell`. Raw tool names are too fine-grained: across 88 real sessions they showed no repeated workflow at all, while phases did.
3. **Families.** Requests group by their anchor (the slash command or skill that started them) or by phase profile:

   | Family | Phases |
   | --- | --- |
   | `answer-only` | none |
   | `lookup` | explore only |
   | `research` | explore and web |
   | `edit` | has edit |
   | `edit-test` | edit and test |
   | `ship` | has commit |
   | `verify` | test or build without edits |
   | `delegate` | delegate without edits |
   | `shell` | anything else |

   agentctl job graphs form their own families (`agentctl:<kind>`).
4. **Graph and variants.** Per family: a directly-follows graph over phases, the variants (distinct phase shapes), the dominant share and entropy, and a typical path (a greedy walk along the heaviest transitions). The picture hides transitions seen in under 5% of runs, beyond the 12 most frequent.
5. **Errors.** Errors are split by phase:
   - **Friction** is a failed edit, explore, shell, delegate or web step.
   - A red test or a failed build is feedback, not friction: that is how development works.
   - **Unrecovered** means the run's last tool call failed.

## The worth-it gate (`worth_it.py`)

| Check | Default |
| --- | --- |
| Evidence before any verdict other than observe | ≥ 5 requests, ≥ 3 sessions, ≥ 2 days |
| Cheap fix for question-answering (`lookup` and `answer-only` together) | ≥ 15% of requests and ≥ 250 median output tokens |
| Engineer: unrecovered failures | ≥ 10% of runs and ≥ 3 runs |
| Engineer: erratic with friction | entropy ≥ 1.5, dominant variant < 50%, median ≥ 6 steps, and friction ≥ 30% of runs |

Erratic alone is normal for open-ended work and gives "observe". So do failing tests that later pass.

## Keep or roll back

Every recommendation names a metric and a guard, for example `families.lookup.median_output_tokens` down with `families.lookup.error_rate` not up. After applying a change and collecting a comparable window:

```sh
sessiongraph workflows-compare before/workflows.json after/workflows.json --recommendation lookups-low-effort
```

It exits 0 (keep) only when the metric moved its way, the guard held, and both windows have enough requests to compare.

## Not done yet

- Codex and Cursor readers. The stable route for both is their OpenTelemetry export, which is redacted by default.
- Applying a recommendation automatically. Changes stay human-reviewed: agentctl's `graph apply` creates a branch for code, and settings are changed by the user.
- Outcome labels. "Content-free" means SessionGraph knows a run ended and what it cost, not whether the answer was right. Effort sweeps with checks (`agentctl bench-effort`) are the controlled way to measure quality.
