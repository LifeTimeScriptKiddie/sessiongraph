# Research notes

Research date: 2026-09-09. These notes describe the adjacent-project review that shaped the MVP.

## Comparable work

- [Pi session format](https://pi.dev/docs/latest/session-format) documents the v3 JSONL tree (`id` / `parentId`), message types, usage, and `SessionManager`. SessionGraph reads this format directly.
- [Pi extensions](https://pi.dev/docs/latest/extensions) expose session lifecycle events, `ctx.sessionManager`, and local commands. The included `/sessiongraph` extension uses the current persisted session path.
- [Datadog Trajectory](https://github.com/datadog-labs/trajectory) is the closest broad product: multi-client capture, local timelines, metrics, and explicit retry/loop/stall questions. Use it when full observability and many agent adapters matter more than a small offline analyzer.
- [Hodoscope](https://github.com/AR-FORUM/hodoscope) summarizes, embeds, clusters, and visualizes large action collections. It is better for population-level exploratory research but normally introduces model and embedding dependencies.
- [deja](https://github.com/yussypu/deja) records API traffic and provides deterministic replay, branching, diffing, and statistical comparison. SessionGraph does not attempt replay.
- [AgentLens](https://github.com/dreadnode/agent-lens) captures trajectories in ATIF, tracks file state, supports interventions, and uses rubric judges. It is an evaluation harness rather than a post-hoc personal workflow analyzer.
- [SWE-chat](https://arxiv.org/abs/2604.20779) demonstrates why real interaction traces matter: user corrections, tool use, and code survival expose failure modes that patch-only benchmarks miss.

## Chosen gap

SessionGraph is deliberately small and deterministic. It needs no model, database, browser, or hosted telemetry. It turns one Pi or generic JSONL session into a content-free evidence graph, rule-based findings, and a before/after improvement experiment. Agentctl is optional and receives only the redacted report the operator explicitly copies into the run directory.

## Limits

- Repeated calls can be correct behavior; findings are signals, not proof of failure.
- Parent links reconstruct recorded lineage, not hidden reasoning or real-world causality.
- Text heuristics for user corrections are English-first and should be validated before team-level conclusions.
- Cross-session claims require comparable tasks and multiple runs. One trace is not evidence that a workflow change generalizes.
