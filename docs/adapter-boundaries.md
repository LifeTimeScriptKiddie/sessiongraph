# Adapter boundary verification (Phase 2)

**Compatibility check date:** 2026-09-10
**Policy:** installed versions win over online docs.

## Pi (graph observer update)

| Item | Value |
|---|---|
| Package | `@earendil-works/pi-coding-agent` 0.85.1 |
| Adapter | `pi` / `0.85.1-observer-s3` |
| Supported | `before_agent_start.*`, `tool_call` (path/line from args), `tool_result`, `before_provider_request`, assistant `message_end` (+ usage when present) |
| Unsupported / partial | **cursor-cli / Cursor provider path** does not emit Pi `before_provider_request` or Pi `tool_*` events — tools run outside Pi. Observer records explicit `capture_health` gaps instead of inventing payloads. |
| Notes | Observe-only (returns `undefined`). Turn `requestId` is **stable** for the whole user turn; provider calls use `attemptId` …`:pN`. Tool spans only when runtime args include offset/limit (`matchMethod=runtime_line_range`). Never invents `0..N` byte ranges. Opt-in raw text: `ISEEAGENTS_PERSIST_RAW_TEXT=1`. Final payload claim: `ISEEAGENTS_FINAL_OBSERVER=1` only when this extension loads last. |

Exact matching uses only explicit common provider text fields (system, input,
messages/content, and supported text blocks), with up to eight transient source
observations and sixteen text fields. Source/payload matching is capped at 128 KiB
per item; unsupported layouts, limits and evictions emit capture gaps. Default
policy does not persist raw text.

Turn activity joins on `requestId`. Distinct payload snapshots still get distinct
`attemptId` values for provenance request keys; they no longer rewrite the turn id.

## Claude Code

| Item | Value |
|---|---|
| Tested version | `claude` **2.1.267** (`~/.local/bin/claude`) |
| Adapter | `claude-code` / `2.1.267-hooks` |
| Observed hook contract | `UserPromptSubmit` stdin includes `.prompt`; session hooks use `SessionStart` and `UserPromptSubmit` |
| Hook contract | Pre/PostToolUse use `.tool_name` / `.tool_input` (claude-plugins-official hook-development skill) |
| Supported | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact` (partial — not payload inclusion) |
| Unsupported | `provider_payload`, `Notification`, `Stop`, `SubagentStop` |
| Install | Repo opt-in `extensions/claude/hook.sh` only — **not** written into `~/.claude/settings.json` by Phase 2 |

## Codex

| Item | Value |
|---|---|
| Tested version | `codex-cli` **0.153.4** |
| Adapter | `codex` / `0.153.4-rollout-s2` |
| Verified locally | `~/.codex/sessions/**/rollout-*.jsonl` types: `session_meta`, user/assistant `response_item`, `event_msg` (`token_count` with `total_token_usage.*`), `turn_context`; `~/.codex/history.jsonl` user text inventory |
| Supported | `transcript.session_meta`, `transcript.user_message`, `transcript.assistant_message`, `transcript.token_count`, `history.user_text` |
| Unsupported | `provider_payload`, `sdk_events`, `compaction`, `plugin_hooks` |
| Notes | Offline ingest only; empty `token_count.info` → coverage `partial`. An assistant message is associated with the latest observed user message in the same recorded turn; the edge is not evidence of semantic influence. |

## Evidence rules

Hooks/transcripts ≠ provider payload. Usage counters stay separate from source token estimates. Unknown/unsupported must remain explicit in the UI and event `coverage` field.
