# Changelog

All notable changes to SessionGraph are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `analyze-pipeline`: ordered pipeline contracts with externally recorded artifact
  checks, missing-check accounting, stage timeouts, content-free evidence hashes,
  and contract-preserving `pipeline_contract` workflow suggestions. Pipeline
  comparisons require matching fixture, verifier and contract hashes.
- `sessiongraph suggest-workflow`: deterministic finding→topology compiler
  (`suggest-map-v1`) that emits markdown / Claude `workflow.js` / agentctl
  sketches from `analysis.json`, a report directory, or session JSONL. Stdlib
  only; never auto-runs agents or patches user repos. See
  `docs/suggest-workflow.md`.

### Changed
- `errors` finding now reports **unrecovered** errors only: an errored tool
  call whose same signature succeeds later in the session is treated as
  recovered and excluded, so the count reflects failures the run never got
  past rather than a raw error tally that fired on nearly every session. The
  summary also breaks out how many errors were later recovered.

### Added
- Explicit **Scope** statement in the README (triage tool for session/loop
  health; not an agent-quality or routing evaluator).
- Packaging metadata: PyPI trove classifiers, project URLs, a `dev` optional
  dependency group (`build`, `pytest`), and a named maintainer.
- Continuous integration (unit tests + `compileall`) across Python 3.11–3.13
  on Linux, macOS, and Windows.
- Tests covering recovered vs. unrecovered tool errors.

## [0.1.0] - 2026-09-09

### Added
- Initial release: local-first analyzer for Pi v3 sessions, agentctl
  improvement-loop traces, and a generic JSONL format.
- Deterministic detectors: `repeated_action`, `alternating_loop`, `errors`,
  `user_correction`, `dead_end`, `dangling_edges`, plus agentctl loop metrics
  (`agent_timeout`, `loop_bottleneck`).
- Content-free-by-default output with secret/PII redaction, DoS import caps,
  Markdown report, Mermaid graph, `compare`, and `prepare-loop`.
