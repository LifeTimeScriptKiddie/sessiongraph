/**
 * Pi observe-only extension for iseeagents.
 *
 * Load for tests with: pi -e ./extensions/pi/iseeagents-observer.ts
 * Global symlink OK: ~/.pi/agent/extensions/iseeagents-observer.ts → this file.
 *
 * Symlink-safe: deps load via realpath(import.meta.url), not relative imports
 * (relative paths resolve against the symlink location under ~/.pi).
 *
 * Critical: every handler that can rewrite payloads must return undefined
 * / omit return values so observation never contaminates measurement.
 *
 * Slice 2: stable turn requestId; tool path/line when runtime provides them;
 * optional ISEEAGENTS_PERSIST_RAW_TEXT=1; honest cursor-cli provider gaps.
 */

import { mkdirSync, readFileSync, realpathSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { ContextEvent } from "../../src/schema.ts";

type Recorder = {
  sessionId: string;
  record: (event: Record<string, unknown>) => ContextEvent;
};

type Deps = {
  AppendOnlyJsonlRecorder: new (opts: {
    path: string;
    sessionId: string;
    adapterId: string;
    adapterVersion: string;
  }) => Recorder;
  observeContextFile: (opts: Record<string, unknown>, input: { path: string; content?: string }) => ContextEvent;
  observeProviderPayload: (
    opts: Record<string, unknown>,
    payload: unknown,
  ) => undefined | { payload?: unknown };
  observeSkill: (opts: Record<string, unknown>, input: { name: string; content?: string; filePath?: string }) => ContextEvent;
  observeToolCall: (
    opts: Record<string, unknown>,
    input: { toolCallId: string; toolName: string; input?: Record<string, unknown> | null },
  ) => ContextEvent;
  observeToolResult: (
    opts: Record<string, unknown>,
    input: {
      toolCallId: string;
      toolName: string;
      content: string;
      input?: Record<string, unknown> | null;
      range?: { start: number; end: number } | null;
      path?: string | null;
      matchMethod?: string | null;
    },
  ) => ContextEvent;
  observeUserPrompt: (opts: Record<string, unknown>, prompt: string) => ContextEvent;
  observeUsage: (
    opts: Record<string, unknown>,
    usage: { input: number | null; output: number | null; cached: number | null },
  ) => void;
  observeResponse: (opts: Record<string, unknown>, text: string) => unknown;
  recordTextMatches: (opts: Record<string, unknown>) => unknown;
  payloadTextPointers: (payload: unknown) => string[];
  contentVersionKey: (text: string, key: Buffer) => string;
  hmacKeyFromEnv: () => Buffer;
  PI_ADAPTER_ID: string;
  PI_ADAPTER_VERSION: string;
};

type State = {
  recorder: Recorder | null;
  /** Stable for the whole user turn (activity tape join key). */
  requestId: string | null;
  turnId: string | null;
  attempt: number;
  payloadOrdinal: number;
  payloadEventId: string | null;
  sawProviderPayload: boolean;
  sawToolEvent: boolean;
  sources: { event: ContextEvent; text: string }[];
};

const state: State = {
  recorder: null,
  requestId: null,
  turnId: null,
  attempt: 0,
  payloadOrdinal: 0,
  payloadEventId: null,
  sawProviderPayload: false,
  sawToolEvent: false,
  sources: [],
};

const ephemeralSessionId = `ephemeral-${process.pid}-${Date.now()}`;

function sessionIdFromContext(ctx: { sessionManager: { getSessionFile?: () => unknown } }): string {
  const sessionFile = ctx.sessionManager.getSessionFile?.();
  if (typeof sessionFile !== "string" || !sessionFile) return ephemeralSessionId;
  return basename(sessionFile).replace(/\.jsonl?$/, "") || ephemeralSessionId;
}

function packageRoot(): string {
  const self = realpathSync(fileURLToPath(import.meta.url));
  return join(dirname(self), "../..");
}

function srcUrl(relFromSrc: string): string {
  return pathToFileURL(join(packageRoot(), "src", relFromSrc)).href;
}

function persistRawText(): boolean {
  return process.env.ISEEAGENTS_PERSIST_RAW_TEXT === "1";
}

/** Persist instructions / skills / system bodies (not user prompts). */
function persistHarnessText(): boolean {
  return process.env.ISEEAGENTS_PERSIST_HARNESS_TEXT === "1" || persistRawText();
}

function attemptId(payloadOrdinal?: number): string | null {
  if (!state.requestId) return null;
  const base = `${state.requestId}:a${state.attempt}`;
  return payloadOrdinal && payloadOrdinal > 0 ? `${base}:p${payloadOrdinal}` : base;
}

async function loadDeps(): Promise<Deps> {
  const [recorderMod, piMod, provenanceMod, fieldsMod, idsMod] = await Promise.all([
    import(srcUrl("recorder.ts")),
    import(srcUrl("adapters/pi.ts")),
    import(srcUrl("provenance/observe.ts")),
    import(srcUrl("provenance/text-fields.ts")),
    import(srcUrl("ids.ts")),
  ]);
  return {
    AppendOnlyJsonlRecorder: recorderMod.AppendOnlyJsonlRecorder,
    observeContextFile: piMod.observeContextFile,
    observeProviderPayload: piMod.observeProviderPayload,
    observeSkill: piMod.observeSkill,
    observeToolCall: piMod.observeToolCall,
    observeToolResult: piMod.observeToolResult,
    observeUserPrompt: piMod.observeUserPrompt,
    observeUsage: piMod.observeUsage,
    observeResponse: provenanceMod.observeResponse,
    recordTextMatches: provenanceMod.recordTextMatches,
    payloadTextPointers: fieldsMod.payloadTextPointers,
    contentVersionKey: idsMod.contentVersionKey,
    hmacKeyFromEnv: idsMod.hmacKeyFromEnv,
    PI_ADAPTER_ID: piMod.PI_ADAPTER_ID,
    PI_ADAPTER_VERSION: piMod.PI_ADAPTER_VERSION,
  };
}

function toolContent(event: { content?: unknown; result?: unknown }): string {
  const raw = event.content ?? event.result;
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) {
    return raw
      .filter((part: { type?: string }) => part.type === "text")
      .map((part: { text?: string }) => part.text ?? "")
      .join("\n");
  }
  return JSON.stringify(raw ?? "");
}

export default async function iseeagentsObserver(pi: ExtensionAPI) {
  const deps = await loadDeps();

  function captureGap(boundary: string, extra: Record<string, unknown> = {}) {
    state.recorder?.record({
      observation: "capture_health",
      evidence: "unknown",
      coverage: "partial",
      boundary,
      requestId: state.requestId,
      attemptId: attemptId(),
      ...extra,
    });
  }

  function remember(event: ContextEvent, text?: string) {
    if (!text) return;
    if (Buffer.byteLength(text) > 128 * 1024) {
      captureGap("source_matching.source_limit");
      return;
    }
    state.sources.push({ event, text });
    if (state.sources.length > 8) {
      state.sources.shift();
      captureGap("source_matching.eviction");
    }
  }

  function ensureRecorder(cwd: string, sessionId: string): Recorder {
    if (state.recorder && state.recorder.sessionId === sessionId) return state.recorder;
    const dir = join(cwd, ".iseeagents");
    mkdirSync(dir, { recursive: true });
    state.recorder = new deps.AppendOnlyJsonlRecorder({
      path: join(dir, `${sessionId}.jsonl`),
      sessionId,
      adapterId: deps.PI_ADAPTER_ID,
      adapterVersion: deps.PI_ADAPTER_VERSION,
    });
    state.requestId = null;
    state.turnId = null;
    state.payloadEventId = null;
    state.payloadOrdinal = 0;
    state.attempt = 0;
    state.sawProviderPayload = false;
    state.sawToolEvent = false;
    state.sources = [];
    return state.recorder;
  }

  function baseOpts(recorder: Recorder, payloadOrdinal?: number) {
    return {
      recorder,
      requestId: state.requestId as string,
      attemptId: attemptId(payloadOrdinal),
      handlerOrdinal: 0,
      persistRawText: persistRawText(),
      persistHarnessText: persistHarnessText(),
    };
  }

  pi.on("session_start", async (_event, ctx) => {
    ensureRecorder(ctx.cwd, sessionIdFromContext(ctx));
  });

  pi.on("before_agent_start", async (event, ctx) => {
    try {
      const recorder = ensureRecorder(ctx.cwd, sessionIdFromContext(ctx));
      state.attempt += 1;
      // Stable turn id — do not rewrite on provider/tool events.
      state.requestId = `req_${Date.now()}_${state.attempt}`;
      state.turnId = state.requestId;
      state.payloadOrdinal = 0;
      state.payloadEventId = null;
      state.sawProviderPayload = false;
      state.sawToolEvent = false;
      state.sources = [];
      const opts = baseOpts(recorder);
      remember(deps.observeUserPrompt(opts, event.prompt ?? ""), event.prompt);
      if (event.systemPrompt) {
        remember(
          recorder.record({
            requestId: state.requestId,
            attemptId: opts.attemptId,
            observation: "load",
            evidence: "runtime_loaded",
            boundary: "before_agent_start.systemPrompt",
            coverage: "full",
            sourceCategory: "system_input",
            sourceAlias: "Assembled system prompt",
            sourceKey: "assembled-system-prompt",
            contentVersionKey: deps.contentVersionKey(event.systemPrompt, deps.hmacKeyFromEnv()),
            rawTextRedacted: persistHarnessText() ? null : true,
            ...(persistHarnessText() ? { rawText: event.systemPrompt } : {}),
          }),
          event.systemPrompt,
        );
      }
      const files = event.systemPromptOptions?.contextFiles ?? [];
      for (const f of files) {
        const path = typeof f === "string" ? f : (f as { path?: string }).path ?? "context";
        const content = typeof f === "string" ? undefined : (f as { content?: string }).content;
        remember(deps.observeContextFile(opts, { path, content }), content);
      }
      const skills = event.systemPromptOptions?.skills ?? [];
      for (const s of skills) {
        const name = typeof s === "string" ? s : (s as { name?: string }).name ?? "skill";
        const filePath = typeof s === "string" ? undefined : (s as { filePath?: string }).filePath;
        let content = typeof s === "string" ? undefined : (s as { content?: string }).content;
        // Pi Skill objects expose filePath, not inline content — read when capturing harness text.
        if (!content && filePath && persistHarnessText()) {
          try {
            content = readFileSync(filePath, "utf8");
          } catch {
            captureGap("before_agent_start.skill_read_error", { notes: `sourcePath=${filePath}` });
          }
        }
        remember(deps.observeSkill(opts, { name, content, filePath }), content);
      }
    } catch {
      captureGap("before_agent_start.handler_error");
    }
    // Observe only — do not inject message or rewrite systemPrompt.
  });

  pi.on("tool_call", async (event, _ctx) => {
    if (!state.recorder || !state.requestId) return;
    try {
      state.sawToolEvent = true;
      deps.observeToolCall(baseOpts(state.recorder), {
        toolCallId: event.toolCallId ?? "unknown",
        toolName: event.toolName ?? "unknown",
        input: (event.input ?? null) as Record<string, unknown> | null,
      });
    } catch {
      captureGap("tool_call.handler_error");
    }
    // Do not block or mutate tool args.
  });

  pi.on("tool_result", async (event, _ctx) => {
    if (!state.recorder || !state.requestId) return;
    try {
      state.sawToolEvent = true;
      const content = toolContent(event);
      const observation = deps.observeToolResult(baseOpts(state.recorder), {
        toolCallId: event.toolCallId ?? "unknown",
        toolName: event.toolName ?? "unknown",
        content,
        input: (event.input ?? null) as Record<string, unknown> | null,
      });
      remember(observation, content);
      const usage = event.usage;
      if (usage && typeof usage === "object") {
        const u = usage as { input?: number; output?: number; cacheRead?: number; cacheWrite?: number };
        deps.observeUsage(baseOpts(state.recorder), {
          input: typeof u.input === "number" ? u.input : null,
          output: typeof u.output === "number" ? u.output : null,
          cached: typeof u.cacheRead === "number" ? u.cacheRead : null,
        });
      }
    } catch {
      captureGap("tool_result.handler_error");
    }
    // Do not return a modified tool result.
  });

  pi.on("before_provider_request", (event, _ctx) => {
    if (!state.recorder || !state.requestId) return;
    try {
      state.sawProviderPayload = true;
      const ordinal = ++state.payloadOrdinal;
      // Keep turn requestId stable; distinguish provider calls via attemptId :pN.
      state.payloadEventId = null;
      const claimFinal = process.env.ISEEAGENTS_FINAL_OBSERVER === "1";
      return deps.observeProviderPayload(
        {
          ...baseOpts(state.recorder, ordinal),
          provisional: !claimFinal,
          final: claimFinal,
          onRecorded: (record: ContextEvent) => {
            state.payloadEventId = record.eventId;
            try {
              if (Buffer.byteLength(JSON.stringify(event.payload)) > 128 * 1024) {
                captureGap("source_matching.payload_limit");
                return;
              }
              const pointers = deps.payloadTextPointers(event.payload);
              if (!pointers.length) captureGap("source_matching.unsupported_text_layout");
              if (pointers.length > 16) captureGap("source_matching.field_limit");
              for (const source of state.sources) {
                for (const textPointer of pointers.slice(0, 16)) {
                  deps.recordTextMatches({
                    recorder: state.recorder,
                    source: source.event,
                    sourceText: source.text,
                    payloadEvent: record,
                    payload: event.payload,
                    textPointer,
                  });
                }
              }
            } catch {
              captureGap("source_matching.failed");
            }
          },
        },
        event.payload,
      );
    } catch {
      captureGap("before_provider_request.handler_error", {
        unsupportedBoundary: "before_provider_request",
        coverage: "unsupported",
      });
      return undefined;
    }
  });

  pi.on("message_end", (event, _ctx) => {
    if (!state.recorder || !state.requestId || event.message?.role !== "assistant") return;
    try {
      const content = event.message.content;
      const text =
        typeof content === "string"
          ? content
          : Array.isArray(content)
            ? content
                .filter((part: { type: string }) => part.type === "text")
                .map((part: { text?: string }) => part.text ?? "")
                .join("\n")
            : "";
      const opts = {
        ...baseOpts(state.recorder, state.payloadOrdinal || undefined),
        payloadEventId: state.payloadEventId,
      };
      deps.observeResponse(opts, text);
      const usage = (event.message as { usage?: Record<string, unknown> }).usage;
      if (usage && typeof usage === "object") {
        deps.observeUsage(opts, {
          input: typeof usage.input === "number" ? usage.input : null,
          output: typeof usage.output === "number" ? usage.output : null,
          cached: typeof usage.cacheRead === "number" ? usage.cacheRead : null,
        });
      }
      if (!state.sawProviderPayload) {
        const api = String((event.message as { api?: string }).api ?? "");
        const provider = String((event.message as { provider?: string }).provider ?? "");
        const cursorPath = /cursor/i.test(api) || /cursor/i.test(provider);
        captureGap("capture_health.missing_provider_payload", {
          unsupportedBoundary: "before_provider_request",
          coverage: "unsupported",
          notes: cursorPath
            ? `No before_provider_request on this turn (api=${api || "?"} provider=${provider || "?"}). cursor-cli/external providers bypass Pi wire-payload hooks.`
            : "No before_provider_request on this turn; provider hook did not fire or is unsupported on this path.",
        });
      }
      if (!state.sawToolEvent && !state.sawProviderPayload) {
        captureGap("capture_health.missing_tool_events", {
          unsupportedBoundary: "tool_call|tool_result",
          coverage: "unsupported",
          notes: "No Pi tool_call/tool_result events this turn. Tools may run outside Pi (e.g. Cursor agent tools).",
        });
      }
    } catch {
      captureGap("message_end.handler_error");
    }
    // Observe only: no replacement of the response.
  });
}
