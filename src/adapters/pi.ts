import { createHash } from "node:crypto";
import type { AppendOnlyJsonlRecorder } from "../recorder.ts";
import { contentVersionKey, hmacKeyFromEnv, keyedId, looksSecretLike } from "../ids.ts";
import { stableStringify } from "../recorder.ts";
import type { ContextEvent } from "../schema.ts";

export const PI_ADAPTER_ID = "pi";
export const PI_ADAPTER_VERSION = "0.85.1-observer-s3";

export type ObserveOptions = {
  recorder: AppendOnlyJsonlRecorder;
  requestId: string;
  attemptId?: string | null;
  handlerOrdinal?: number;
  hmacKey?: Buffer;
  /** If false (default), never persist raw text for prompts. */
  persistRawText?: boolean;
  /**
   * Persist instructions / skills / system prompt bodies (not user prompts).
   * Independent of persistRawText. Default false — HTML embed can still resolve paths.
   */
  persistHarnessText?: boolean;
};

function estimateTokens(text: string): number {
  // Coarse estimate only — never treat as provider truth.
  return Math.max(1, Math.ceil(text.length / 4));
}

function maybeRawText(opts: ObserveOptions, text: string, secret: boolean): { rawTextRedacted: true | null; rawText?: string } {
  if (secret || !opts.persistRawText) return { rawTextRedacted: true };
  return { rawTextRedacted: null, rawText: text };
}

/** Extract path + optional runtime line range from Pi tool input. Never invent spans. */
export function extractToolPathAndRange(
  toolName: string,
  input: Record<string, unknown> | null | undefined,
): {
  path: string | null;
  range: { start: number; end: number } | null;
  matchMethod: string | null;
  observation: "read" | "transform" | "load";
  coverage: "full" | "partial";
} {
  const src = input && typeof input === "object" ? input : {};
  const path =
    typeof src.path === "string" ? src.path
    : typeof src.file_path === "string" ? src.file_path
    : typeof src.filePath === "string" ? src.filePath
    : null;
  const name = String(toolName || "").toLowerCase();
  const offset = typeof src.offset === "number" && Number.isFinite(src.offset) ? src.offset : null;
  const limit = typeof src.limit === "number" && Number.isFinite(src.limit) && src.limit > 0 ? src.limit : null;

  if (name === "read" || name === "read_file") {
    if (offset != null && limit != null) {
      return {
        path,
        range: { start: offset, end: offset + limit - 1 },
        matchMethod: "runtime_line_range",
        observation: "read",
        coverage: path ? "full" : "partial",
      };
    }
    return { path, range: null, matchMethod: null, observation: "read", coverage: path ? "partial" : "partial" };
  }
  if (name === "edit" || name === "write" || name === "apply_patch" || name === "strreplace") {
    return { path, range: null, matchMethod: null, observation: "transform", coverage: path ? "partial" : "partial" };
  }
  if (name === "grep" || name === "find" || name === "ls" || name === "glob") {
    const pattern = typeof src.pattern === "string" ? src.pattern : typeof src.glob_pattern === "string" ? src.glob_pattern : null;
    return {
      path: path ?? (pattern ? `pattern:${pattern}` : null),
      range: null,
      matchMethod: null,
      observation: "read",
      coverage: "partial",
    };
  }
  return { path, range: null, matchMethod: null, observation: "load", coverage: "partial" };
}

export function observeUserPrompt(
  opts: ObserveOptions,
  prompt: string,
): ContextEvent {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const secret = looksSecretLike(prompt);
  const raw = maybeRawText(opts, prompt, secret);
  return opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "load",
    evidence: "runtime_loaded",
    boundary: "before_agent_start.prompt",
    coverage: "full",
    sourceCategory: "user_input",
    sourceAlias: "user_prompt",
    sourceKey: keyedId("user_input", opts.requestId, key),
    contentVersionKey: contentVersionKey(prompt, key),
    encoding: "utf8",
    estimatedTokens: estimateTokens(prompt),
    byteCount: Buffer.byteLength(prompt, "utf8"),
    charCount: prompt.length,
    handlerOrdinal: opts.handlerOrdinal ?? 0,
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    notes: secret ? "secret-like prompt redacted; metadata only" : null,
    ...raw,
  });
}

export function observeContextFile(
  opts: ObserveOptions,
  file: { path: string; content?: string },
): ContextEvent {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const content = file.content ?? "";
  const persistBody = Boolean(opts.persistHarnessText || opts.persistRawText);
  const raw = maybeRawText({ ...opts, persistRawText: persistBody }, content, false);
  return opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "load",
    evidence: "runtime_loaded",
    boundary: "before_agent_start.contextFiles",
    coverage: content ? "full" : "partial",
    sourceCategory: "instructions",
    sourceAlias: file.path,
    sourcePath: file.path,
    sourceKey: keyedId("instructions", file.path, key),
    contentVersionKey: content ? contentVersionKey(content, key) : null,
    encoding: "utf8",
    estimatedTokens: content ? estimateTokens(content) : null,
    byteCount: content ? Buffer.byteLength(content, "utf8") : null,
    charCount: content ? content.length : null,
    handlerOrdinal: opts.handlerOrdinal ?? 0,
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    ...raw,
  });
}

export function observeSkill(
  opts: ObserveOptions,
  skill: { name: string; content?: string; filePath?: string },
): ContextEvent {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const content = skill.content ?? "";
  const persistBody = Boolean(opts.persistHarnessText || opts.persistRawText);
  const raw = maybeRawText({ ...opts, persistRawText: persistBody }, content, false);
  return opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "load",
    evidence: "runtime_loaded",
    boundary: "before_agent_start.skills",
    coverage: content || skill.filePath ? (content ? "full" : "partial") : "partial",
    sourceCategory: "skill",
    sourceAlias: skill.name,
    sourcePath: skill.filePath ?? null,
    sourceKey: keyedId("skill", skill.name, key),
    contentVersionKey: content ? contentVersionKey(content, key) : null,
    encoding: "utf8",
    estimatedTokens: content ? estimateTokens(content) : null,
    byteCount: content ? Buffer.byteLength(content, "utf8") : null,
    charCount: content ? content.length : null,
    handlerOrdinal: opts.handlerOrdinal ?? 0,
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    notes: skill.filePath ? `sourcePath=${skill.filePath}` : null,
    ...raw,
  });
}

export function observeToolCall(
  opts: ObserveOptions,
  tool: {
    toolCallId: string;
    toolName: string;
    input?: Record<string, unknown> | null;
  },
): ContextEvent {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const span = extractToolPathAndRange(tool.toolName, tool.input);
  return opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    toolCallId: tool.toolCallId,
    observation: "load",
    evidence: "runtime_loaded",
    boundary: "tool_call.start",
    coverage: span.coverage,
    sourceCategory: "tool_result",
    sourceAlias: span.path ?? tool.toolName,
    sourceKey: keyedId("tool_call", `${tool.toolName}:${tool.toolCallId}`, key),
    contentVersionKey: null,
    sourceRange: span.range,
    matchMethod: span.matchMethod,
    encoding: null,
    handlerOrdinal: opts.handlerOrdinal ?? 0,
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    notes: span.range
      ? `Tool start ${tool.toolName}; runtime line range from tool args`
      : `Tool start ${tool.toolName}; path/range only when runtime provided them`,
    rawTextRedacted: true,
  });
}

export function observeToolResult(
  opts: ObserveOptions,
  tool: {
    toolCallId: string;
    toolName: string;
    content: string;
    range?: { start: number; end: number } | null;
    path?: string | null;
    matchMethod?: string | null;
    observation?: "read" | "transform" | "load";
    coverage?: "full" | "partial";
    input?: Record<string, unknown> | null;
  },
): ContextEvent {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const span = extractToolPathAndRange(tool.toolName, tool.input);
  const range = tool.range !== undefined ? tool.range : span.range;
  const matchMethod = tool.matchMethod !== undefined ? tool.matchMethod : span.matchMethod;
  const path = tool.path !== undefined ? tool.path : span.path;
  const observation = tool.observation ?? span.observation;
  const coverage = tool.coverage ?? (range || path ? span.coverage : "partial");
  const secret = looksSecretLike(tool.content);
  const raw = maybeRawText(opts, tool.content, secret);
  return opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    toolCallId: tool.toolCallId,
    observation,
    evidence: "read_result",
    boundary: "tool_result",
    coverage,
    sourceCategory: "tool_result",
    sourceAlias: path ?? tool.toolName,
    sourceKey: keyedId("tool_result", `${tool.toolName}:${tool.toolCallId}`, key),
    contentVersionKey: contentVersionKey(tool.content, key),
    sourceRange: range ?? null,
    matchMethod: matchMethod ?? null,
    encoding: "utf8",
    estimatedTokens: estimateTokens(tool.content),
    byteCount: Buffer.byteLength(tool.content, "utf8"),
    charCount: tool.content.length,
    handlerOrdinal: opts.handlerOrdinal ?? 0,
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    notes: secret
      ? "secret-like tool output not persisted"
      : range
        ? null
        : "No runtime span on tool result; refusing to invent 0..N byte range",
    ...raw,
  });
}

/**
 * Observe provider payload without mutating it.
 * Returns undefined always so Pi keeps the original payload.
 */
export function observeProviderPayload(
  opts: ObserveOptions & { provisional?: boolean; final?: boolean; onRecorded?: (event: ContextEvent) => void },
  payload: unknown,
): undefined {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const serialized = typeof payload === "string" ? payload : stableStringify(payload);
  const fingerprint = createHash("sha256").update(serialized).digest("hex").slice(0, 16);
  const provisional = opts.provisional === true && opts.final !== true;
  const event = opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: opts.final ? "dispatch" : "payload",
    evidence: opts.final ? "final_dispatch" : "payload_snapshot",
    boundary: provisional
      ? "before_provider_request.provisional"
      : opts.final
        ? "before_provider_request.final"
        : "before_provider_request",
    coverage: provisional ? "partial" : "full",
    sourceCategory: "unattributed",
    sourceAlias: "provider_payload",
    sourceKey: keyedId("payload", opts.requestId, key),
    contentVersionKey: contentVersionKey(serialized, key),
    encoding: "json",
    estimatedTokens: estimateTokens(serialized),
    byteCount: Buffer.byteLength(serialized, "utf8"),
    handlerOrdinal: opts.handlerOrdinal ?? 0,
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    matchMethod: `sha256:${fingerprint}`,
    notes: provisional
      ? "Earlier observer; later handlers may still mutate payload"
      : "Observer returns undefined; payload unchanged",
    rawTextRedacted: true,
  });
  opts.onRecorded?.(event);
  return undefined;
}

export function observeUsage(
  opts: ObserveOptions,
  usage: { input: number | null; output: number | null; cached: number | null },
): void {
  opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "usage",
    evidence: "final_dispatch",
    boundary: "provider_usage",
    coverage: usage.input === null ? "partial" : "full",
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    usageInputTokens: usage.input,
    usageOutputTokens: usage.output,
    usageCachedTokens: usage.cached,
    notes: "Provider totals are independent of source token estimates",
  });
}

export function observeCompactionSummary(
  opts: ObserveOptions,
  summary: { text: string; ancestorEventIds: string[] },
): void {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "transform",
    evidence: "summary_ancestor",
    boundary: "compaction",
    coverage: "full",
    sourceCategory: "summary",
    sourceAlias: "compaction_summary",
    sourceKey: keyedId("summary", opts.requestId, key),
    contentVersionKey: contentVersionKey(summary.text, key),
    lineageEventIds: summary.ancestorEventIds,
    estimatedTokens: estimateTokens(summary.text),
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    notes: "Summary is a new source/version; do not double-count ancestors as simultaneous content",
    rawTextRedacted: true,
  });
}

export function observeExtensionRuntimeOnly(
  opts: ObserveOptions,
  extensionName: string,
): void {
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  opts.recorder.record({
    requestId: opts.requestId,
    attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "load",
    evidence: "runtime_loaded",
    boundary: "extension_execute",
    coverage: "full",
    sourceCategory: "other",
    sourceAlias: extensionName,
    sourceKey: keyedId("extension", extensionName, key),
    contentVersionKey: null,
    matchMethod: null,
    ambiguity: "extension executed; no payload match for extension source",
    adapterId: PI_ADAPTER_ID,
    adapterVersion: PI_ADAPTER_VERSION,
    notes: "Runtime execution is not source-text attribution",
  });
}
