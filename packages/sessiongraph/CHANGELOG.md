# Changelog

All notable changes to SessionGraph are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Generic JSONL explicit null parents remain roots instead of acquiring fabricated
  previous-event edges. Optional `parent_ids` preserves all declared parents for
  iseeagents provenance and other multi-input graphs; malformed lists fail closed.
- Agentctl scorecards no longer accept apparent health gains from unfinished traces
  or missing stage failure classifications. Scorecard v2 reports failed gate IDs.
- suggest-map multi-fault emission: `pipeline_contract` primary keeps contract
  pi/claude phases when a `repeated_action` retry guard is present (retry
  appends after the spine, does not replace it).
- Markdown `RetryBudget(2)` inserts before `Verify` **or** `VerifyArtifacts`
  (no longer appends after `Done` on contract spines).

### Added
- Optional NetworkX structural metrics (`graph-metrics`) and a self-contained
  PyVis HTML explorer (`visualize`) for content-free `analysis.json` graphs.
- Typed generic JSONL parent edges through validated `parent_relations`, enabling
  explicit artifact lineage such as `created`, `modified`, and `verified_by`.
- `sessiongraph join-iseeagents` CLI: join `analysis.json` event ids to
  `iseeagents.context.v1` provenance JSONL (content-free; key = `eventId`).
- `merge_events` graph metric and comparison delta for multi-parent events.
- Agentctl terminal-record and missing-failure-classification metrics, findings, and
  capture-preflight workflow suggestions, with deterministic real-controller replay
  evidence documented in workspace notes.
- `sessiongraph scorecard`: pass/fail compare gates for suggest-workflow
  accuracy (`workflow_health` ↑, finding count not ↑, no new `dangling_edges`
  or critical findings). Version `suggest-scorecard-v2` also gates agentctl evidence.
- Fixture matrix under `tests/fixtures/suggest-matrix/` plus
  `topology_snapshot` / `topology_digest` helpers for same-findings→same-graph
  determinism.
- `suggest-workflow --target pi`: emit pi-dynamic-workflows-compatible
  `workflow.js` (`export const meta` + top-level `await`). Same
  `suggest-map-v1` topology as other targets; never auto-runs Pi.
- `analyze-pipeline`: ordered pipeline contracts with externally recorded artifact
  checks, missing-check accounting, stage timeouts, content-free evidence hashes,
  and contract-preserving `pipeline_contract` workflow suggestions. Pipeline
  comparisons require matching fixture, verifier and contract hashes.
- `sessiongraph suggest-workflow`: deterministic finding→topology compiler
  (`suggest-map-v1`) that emits markdown / Claude `workflow.js` /
  pi-dynamic-workflows `workflow.js` / agentctl sketches from `analysis.json`,
  a report directory, or session JSONL. Stdlib only; never auto-runs agents or
  patches user repos. See `docs/suggest-workflow.md`.

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
