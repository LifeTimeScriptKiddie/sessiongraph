/**
 * Codex adapter — verified against installed codex-cli 0.153.4 rollout JSONL.
 *
 * Supported: offline transcript ingest for session_meta, user/assistant
 * response_item messages, and event_msg token_count usage. provider_payload /
 * live SDK capture unsupported.
 */
import { createReadStream } from "node:fs";
import { createInterface } from "node:readline";
import type { AppendOnlyJsonlRecorder } from "../recorder.ts";
import type { AdapterCapability } from "../schema.ts";
import {
  contentVersionKey,
  hmacKeyFromEnv,
  keyedId,
  looksSecretLike,
} from "../ids.ts";

export const CODEX_ADAPTER_ID = "codex";
export const CODEX_ADAPTER_VERSION = "0.153.4-rollout-s2";

export const codexCapability: AdapterCapability = {
  adapterId: CODEX_ADAPTER_ID,
  adapterVersion: CODEX_ADAPTER_VERSION,
  supportedBoundaries: [
    "transcript.session_meta",
    "transcript.user_message",
    "transcript.assistant_message",
    "transcript.token_count",
    "history.user_text",
  ],
  unsupportedBoundaries: [
    "provider_payload",
    "sdk_events",
    "compaction",
    "plugin_hooks",
  ],
  notes:
    "Verified on codex-cli 0.153.4 local rollouts under ~/.codex/sessions/**/rollout-*.jsonl (types session_meta, user/assistant response_item, event_msg/token_count) and ~/.codex/history.jsonl. Assistant messages are associated with the latest recorded user message in the same turn; this is not proof of semantic influence. No complete request-capture API verified — do not claim full payload inclusion.",
};

/** @deprecated Prefer codexCapability */
export const codexStubCapability = codexCapability;

export function createCodexUnsupportedObservation(boundary: string) {
  return {
    observation: "capture_health" as const,
    evidence: "unknown" as const,
    boundary,
    coverage: "unsupported" as const,
    unsupportedBoundary: boundary,
    adapterId: CODEX_ADAPTER_ID,
    adapterVersion: CODEX_ADAPTER_VERSION,
    notes: codexCapability.notes,
  };
}

/** @deprecated alias for replay fixtures */
export function createCodexStubObservation(boundary: string) {
  return createCodexUnsupportedObservation(boundary);
}

export type CodexRolloutLine = {
  timestamp?: string;
  ordinal?: number;
  type?: string;
  payload?: Record<string, unknown>;
};

export type CodexObserveOptions = {
  recorder: AppendOnlyJsonlRecorder;
  hmacKey?: Buffer;
  persistRawText?: boolean;
  maxLines?: number;
};

export type CodexRolloutContext = {
  sessionId: string;
  turn: number;
  lastUserEventId?: string | null;
};

function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

function extractUserText(payload: Record<string, unknown>): string {
  if (payload.role !== "user") return "";
  const content = payload.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const item of content) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    if (typeof row.text === "string") parts.push(row.text);
    else if (typeof row.input_text === "string") parts.push(row.input_text);
    else if (row.type === "input_text" && typeof row.text === "string") {
      parts.push(row.text);
    }
  }
  return parts.join("\n");
}

function extractAssistantText(payload: Record<string, unknown>): string {
  if (payload.role !== "assistant") return "";
  const content = payload.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const item of content) {
    if (!item || typeof item !== "object") continue;
    const row = item as Record<string, unknown>;
    if ((row.type === "output_text" || row.type === "text") && typeof row.text === "string") {
      parts.push(row.text);
    }
  }
  return parts.join("\n");
}

function readUsage(info: Record<string, unknown> | undefined): {
  input: number | null;
  output: number | null;
  cached: number | null;
} {
  if (!info || typeof info !== "object") {
    return { input: null, output: null, cached: null };
  }
  const total =
    (info.total_token_usage as Record<string, unknown> | undefined) ??
    (info.last_token_usage as Record<string, unknown> | undefined) ??
    {};
  const num = (v: unknown) =>
    typeof v === "number" && Number.isFinite(v) ? v : null;
  return {
    input: num(total.input_tokens),
    output: num(total.output_tokens),
    cached: num(total.cached_input_tokens),
  };
}

/** Returns true when a provenance event was written. */
export function observeCodexRolloutLine(
  opts: CodexObserveOptions,
  line: CodexRolloutLine,
  ctx: CodexRolloutContext,
): boolean {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const type = String(line.type ?? "unknown");
  const payload = (line.payload ?? {}) as Record<string, unknown>;
  const requestId = `codex:${ctx.sessionId}:t${ctx.turn}`;
  const attemptId = `${requestId}:a1`;
  const base = {
    requestId,
    attemptId,
    adapterId: CODEX_ADAPTER_ID,
    adapterVersion: CODEX_ADAPTER_VERSION,
  };

  if (type === "session_meta") {
    const sid = String(payload.session_id ?? payload.id ?? ctx.sessionId);
    opts.recorder.record({
      ...base,
      observation: "inventory",
      evidence: "inventoried",
      boundary: "transcript.session_meta",
      coverage: "partial",
      sourceCategory: "other",
      sourceAlias: "codex_session",
      sourceKey: keyedId("session", sid, key),
      notes: `cli_version=${String(payload.cli_version ?? "unknown")}; model_provider=${String(payload.model_provider ?? "unknown")}`,
      rawTextRedacted: true,
    });
    return true;
  }

  if (type === "response_item") {
    const text = extractUserText(payload);
    if (text) {
      const secret = looksSecretLike(text);
      const event = opts.recorder.record({
        ...base,
        observation: "load",
        evidence: "runtime_loaded",
        boundary: "transcript.user_message",
        coverage: "partial",
        sourceCategory: "user_input",
        sourceAlias: "user_prompt",
        sourceKey: keyedId("user_input", String(payload.id ?? requestId), key),
        contentVersionKey: contentVersionKey(text, key),
        encoding: "utf8",
        estimatedTokens: estimateTokens(text),
        byteCount: Buffer.byteLength(text, "utf8"),
        charCount: text.length,
        notes: secret
          ? "secret-like user text redacted; metadata only"
          : "Rollout user message — not confirmed provider payload inclusion",
        rawTextRedacted: secret || !opts.persistRawText ? true : null,
        ...(!secret && opts.persistRawText ? { rawText: text } : {}),
      });
      ctx.lastUserEventId = event.eventId;
      return true;
    }

    const assistantText = extractAssistantText(payload);
    if (!assistantText) return false;
    const secret = looksSecretLike(assistantText);
    const phase = typeof payload.phase === "string" ? payload.phase : "unknown";
    opts.recorder.record({
      ...base,
      observation: "response",
      evidence: "runtime_loaded",
      boundary: "transcript.assistant_message",
      coverage: "partial",
      sourceCategory: "model_output",
      sourceAlias: `codex_assistant_${phase}`,
      sourceKey: keyedId("model_output", String(payload.id ?? `${requestId}:${phase}`), key),
      contentVersionKey: contentVersionKey(assistantText, key),
      parentEventIds: ctx.lastUserEventId ? [ctx.lastUserEventId] : [],
      encoding: "utf8",
      estimatedTokens: estimateTokens(assistantText),
      byteCount: Buffer.byteLength(assistantText, "utf8"),
      charCount: assistantText.length,
      notes: secret
        ? "secret-like assistant text redacted; metadata only"
        : "Rollout assistant message associated with the latest observed user message in this turn; association is not semantic influence",
      rawTextRedacted: secret || !opts.persistRawText ? true : null,
      ...(!secret && opts.persistRawText ? { rawText: assistantText } : {}),
    });
    return true;
  }

  if (type === "event_msg" && payload.type === "token_count") {
    const usage = readUsage(payload.info as Record<string, unknown> | undefined);
    opts.recorder.record({
      ...base,
      observation: "usage",
      evidence: "final_dispatch",
      boundary: "transcript.token_count",
      coverage:
        usage.input == null && usage.output == null ? "partial" : "full",
      usageInputTokens: usage.input,
      usageOutputTokens: usage.output,
      usageCachedTokens: usage.cached,
      notes:
        usage.input == null
          ? "token_count event present but info empty/partial on this line"
          : "Provider totals from rollout token_count; independent of source estimates",
    });
    return true;
  }

  return false;
}

export async function ingestCodexRollout(
  opts: CodexObserveOptions,
  rolloutPath: string,
): Promise<{ lines: number; recorded: number }> {
  const max = opts.maxLines ?? 50_000;
  const stream = createReadStream(rolloutPath, { encoding: "utf8" });
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  let lines = 0;
  let recorded = 0;
  let turn = 0;
  const context: CodexRolloutContext = { sessionId: opts.recorder.sessionId, turn: 0 };

  for await (const raw of rl) {
    if (!raw.trim()) continue;
    lines += 1;
    if (lines > max) break;
    let parsed: CodexRolloutLine;
    try {
      parsed = JSON.parse(raw) as CodexRolloutLine;
    } catch {
      opts.recorder.markDropped(1, "transcript.parse_error");
      continue;
    }
    const payload = (parsed.payload ?? {}) as Record<string, unknown>;
    if (parsed.type === "turn_context" || payload.type === "task_started") {
      turn += 1;
      context.turn = turn;
      context.lastUserEventId = null;
    }
    context.turn = Math.max(1, turn);
    if (
      observeCodexRolloutLine(opts, parsed, context)
    ) {
      recorded += 1;
    }
  }
  return { lines, recorded };
}

export function observeCodexHistoryLine(
  opts: CodexObserveOptions,
  row: { session_id?: string; ts?: number; text?: string },
): void {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const text = String(row.text ?? "");
  if (!text) return;
  const requestId = `codex-hist:${row.session_id ?? opts.recorder.sessionId}:${row.ts ?? 0}`;
  const secret = looksSecretLike(text);
  opts.recorder.record({
    requestId,
    attemptId: `${requestId}:a1`,
    observation: "inventory",
    evidence: "inventoried",
    boundary: "history.user_text",
    coverage: "partial",
    sourceCategory: "user_input",
    sourceAlias: "history_prompt",
    sourceKey: keyedId("user_input", requestId, key),
    contentVersionKey: contentVersionKey(text, key),
    estimatedTokens: estimateTokens(text),
    adapterId: CODEX_ADAPTER_ID,
    adapterVersion: CODEX_ADAPTER_VERSION,
    notes: secret
      ? "secret-like history text redacted"
      : "history.jsonl inventory only — not runtime load proof",
    rawTextRedacted: true,
  });
}
