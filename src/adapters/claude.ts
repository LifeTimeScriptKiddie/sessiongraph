/**
 * Claude Code adapter — verified against installed Claude Code 2.1.267
 * and local hooks that read stdin JSON (UserPromptSubmit.prompt, tool_name/tool_input).
 *
 * provider_payload remains unsupported: hooks are not a complete request-capture API.
 */
import type { AppendOnlyJsonlRecorder } from "../recorder.ts";
import type { AdapterCapability } from "../schema.ts";
import {
  contentVersionKey,
  hmacKeyFromEnv,
  keyedId,
  looksSecretLike,
} from "../ids.ts";

export const CLAUDE_ADAPTER_ID = "claude-code";
export const CLAUDE_ADAPTER_VERSION = "2.1.267-hooks";

export const claudeCapability: AdapterCapability = {
  adapterId: CLAUDE_ADAPTER_ID,
  adapterVersion: CLAUDE_ADAPTER_VERSION,
  supportedBoundaries: [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PreCompact",
  ],
  unsupportedBoundaries: ["provider_payload", "Notification", "Stop", "SubagentStop"],
  notes:
    "Verified on Claude Code 2.1.267. Local hooks confirm UserPromptSubmit stdin includes `.prompt`; plugin docs on this host show Pre/PostToolUse fields `.tool_name` / `.tool_input`. Hooks are not provider-payload capture — coverage stays partial/unsupported for final request bytes.",
};

/** @deprecated Prefer claudeCapability */
export const claudeStubCapability = claudeCapability;

export type ClaudeHookInput = {
  hook_event_name?: string;
  hookEventName?: string;
  session_id?: string;
  transcript_path?: string;
  cwd?: string;
  prompt?: string;
  tool_name?: string;
  tool_input?: Record<string, unknown> | string;
  tool_response?: unknown;
  compact_trigger?: string;
  [key: string]: unknown;
};

function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

function eventName(input: ClaudeHookInput): string {
  return String(input.hook_event_name ?? input.hookEventName ?? "unknown");
}

export function createClaudeUnsupportedObservation(boundary: string) {
  return {
    observation: "capture_health" as const,
    evidence: "unknown" as const,
    boundary,
    coverage: "unsupported" as const,
    unsupportedBoundary: boundary,
    adapterId: CLAUDE_ADAPTER_ID,
    adapterVersion: CLAUDE_ADAPTER_VERSION,
    notes: claudeCapability.notes,
  };
}

/**
 * Fixture/replay helper: always records an unsupported/capture_health row.
 * Use observeClaudeHook for real hook mapping.
 */
export function createClaudeStubObservation(boundary: string) {
  return createClaudeUnsupportedObservation(boundary);
}

export type ClaudeObserveOptions = {
  recorder: AppendOnlyJsonlRecorder;
  requestId?: string;
  attemptId?: string | null;
  hmacKey?: Buffer;
  persistRawText?: boolean;
};

/**
 * Map a Claude Code hook stdin object into provenance events.
 * Returns undefined always — hooks must not mutate Claude's control flow via this helper.
 */
export function observeClaudeHook(
  opts: ClaudeObserveOptions,
  input: ClaudeHookInput,
): undefined {
  const boundary = eventName(input);
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  const requestId =
    opts.requestId ??
    `claude:${input.session_id ?? "nosession"}:${boundary}:${Date.now()}`;
  const attemptId = opts.attemptId ?? `${requestId}:a1`;
  const base = {
    requestId,
    attemptId,
    adapterId: CLAUDE_ADAPTER_ID,
    adapterVersion: CLAUDE_ADAPTER_VERSION,
    handlerOrdinal: 0,
  };

  if (claudeCapability.unsupportedBoundaries.includes(boundary)) {
    opts.recorder.record({
      ...base,
      ...createClaudeUnsupportedObservation(boundary),
    });
    return undefined;
  }

  switch (boundary) {
    case "SessionStart": {
      opts.recorder.record({
        ...base,
        observation: "inventory",
        evidence: "inventoried",
        boundary,
        coverage: "partial",
        sourceCategory: "other",
        sourceAlias: "claude_session",
        sourceKey: keyedId("session", String(input.session_id ?? "unknown"), key),
        notes: input.transcript_path
          ? "SessionStart observed; transcript path inventoried, not parsed as payload"
          : "SessionStart observed",
        rawTextRedacted: true,
      });
      break;
    }
    case "UserPromptSubmit": {
      const prompt = String(input.prompt ?? "");
      const secret = looksSecretLike(prompt);
      opts.recorder.record({
        ...base,
        observation: "load",
        evidence: "runtime_loaded",
        boundary,
        coverage: "partial",
        sourceCategory: "user_input",
        sourceAlias: "user_prompt",
        sourceKey: keyedId("user_input", requestId, key),
        contentVersionKey: prompt ? contentVersionKey(prompt, key) : null,
        encoding: "utf8",
        estimatedTokens: prompt ? estimateTokens(prompt) : null,
        byteCount: prompt ? Buffer.byteLength(prompt, "utf8") : null,
        charCount: prompt ? prompt.length : null,
        notes: secret
          ? "secret-like prompt redacted; metadata only"
          : "Hook observes prompt text presence; not provider payload inclusion",
        rawTextRedacted: secret || !opts.persistRawText ? true : null,
      });
      break;
    }
    case "PreToolUse": {
      const toolName = String(input.tool_name ?? "unknown");
      opts.recorder.record({
        ...base,
        observation: "load",
        evidence: "runtime_loaded",
        boundary,
        coverage: "partial",
        sourceCategory: "other",
        sourceAlias: toolName,
        sourceKey: keyedId("tool_call", `${toolName}:${requestId}`, key),
        notes: "PreToolUse — tool invocation observed; arguments not treated as model payload",
        rawTextRedacted: true,
      });
      break;
    }
    case "PostToolUse": {
      const toolName = String(input.tool_name ?? "unknown");
      const response =
        typeof input.tool_response === "string"
          ? input.tool_response
          : input.tool_response != null
            ? JSON.stringify(input.tool_response)
            : "";
      opts.recorder.record({
        ...base,
        observation: "read",
        evidence: "read_result",
        boundary,
        coverage: response ? "partial" : "unknown",
        sourceCategory: "tool_result",
        sourceAlias: toolName,
        sourceKey: keyedId("tool_result", `${toolName}:${requestId}`, key),
        contentVersionKey: response ? contentVersionKey(response, key) : null,
        encoding: "utf8",
        estimatedTokens: response ? estimateTokens(response) : null,
        byteCount: response ? Buffer.byteLength(response, "utf8") : null,
        sourceRange: response
          ? { start: 0, end: Buffer.byteLength(response, "utf8") }
          : null,
        notes: "PostToolUse tool result — not confirmed in provider request bytes",
        rawTextRedacted: true,
      });
      break;
    }
    case "PreCompact": {
      opts.recorder.record({
        ...base,
        observation: "transform",
        evidence: "summary_ancestor",
        boundary,
        coverage: "partial",
        sourceCategory: "summary",
        sourceAlias: "precompact",
        sourceKey: keyedId("summary", requestId, key),
        notes: `PreCompact trigger=${String(input.compact_trigger ?? "unknown")}; summary text not claimed without payload boundary`,
        rawTextRedacted: true,
      });
      break;
    }
    default: {
      opts.recorder.record({
        ...base,
        observation: "capture_health",
        evidence: "unknown",
        boundary,
        coverage: "unknown",
        unsupportedBoundary: boundary,
        notes: `Unlisted hook event on adapter ${CLAUDE_ADAPTER_VERSION}`,
      });
    }
  }
  return undefined;
}
