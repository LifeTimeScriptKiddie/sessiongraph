/** Explicit source-to-payload matching at a named capture boundary. Raw text stays in memory. */
import type { ContextEvent } from "../schema.ts";
import type { AppendOnlyJsonlRecorder } from "../recorder.ts";
import { stableStringify } from "../recorder.ts";
import { contentVersionKey, hmacKeyFromEnv } from "../ids.ts";

export function recordTextMatches(opts: {
  recorder: AppendOnlyJsonlRecorder; source: ContextEvent; sourceText: string;
  payloadEvent: ContextEvent; payload: unknown; textPointer: string; hmacKey?: Buffer;
}): ContextEvent[] {
  const { recorder, source, sourceText, payloadEvent, payload, textPointer } = opts;
  const key = opts.hmacKey ?? hmacKeyFromEnv();
  if (source.sessionId !== payloadEvent.sessionId || source.agentId !== payloadEvent.agentId
      || source.sessionId !== recorder.sessionId || !["payload", "dispatch"].includes(payloadEvent.observation)
      || !["load", "read", "transform", "inventory"].includes(source.observation)
      || source.contentVersionKey !== contentVersionKey(sourceText, key)
      || payloadEvent.contentVersionKey !== contentVersionKey(typeof payload === "string" ? payload : stableStringify(payload), key))
    throw new Error("Source/payload identity or captured version mismatch");
  if (typeof sourceText !== "string" || !sourceText.length) return [];
  if (Buffer.byteLength(sourceText) > 1024 * 1024 || textPointer.length > 512) throw new Error("Match input exceeds capture limit");
  let text: unknown = payload;
  if (textPointer !== "") {
    if (!textPointer.startsWith("/")) throw new Error("textPointer must be a JSON pointer");
    for (const token of textPointer.slice(1).split("/")) {
      const part = token.replace(/~1/g, "/").replace(/~0/g, "~");
      if (!text || typeof text !== "object" || !Object.hasOwn(text, part)) throw new Error("Payload text field not found");
      text = (text as Record<string, unknown>)[part];
    }
  }
  if (typeof text !== "string") throw new Error("Match boundary must select an observed string field");
  if (Buffer.byteLength(text) > 2 * 1024 * 1024) throw new Error("Payload text field exceeds match limit");
  const offsets: number[] = [];
  for (let start = text.indexOf(sourceText); start >= 0; start = text.indexOf(sourceText, start + sourceText.length)) {
    offsets.push(start); if (offsets.length > 128) throw new Error("Too many matching spans; capture requires a narrower source");
  }
  return offsets.map(start => recorder.record({
    agentId: payloadEvent.agentId, requestId: payloadEvent.requestId, attemptId: payloadEvent.attemptId,
    observation: "inclusion", evidence: payloadEvent.evidence, boundary: payloadEvent.boundary,
    coverage: payloadEvent.coverage, parentEventIds: [source.eventId, payloadEvent.eventId],
    sourceCategory: source.sourceCategory, sourceAlias: source.sourceAlias, sourceKey: source.sourceKey,
    contentVersionKey: source.contentVersionKey, sourceSpan: { start: 0, end: Buffer.byteLength(sourceText) },
    requestSpan: { start: Buffer.byteLength(text.slice(0, start)), end: Buffer.byteLength(text.slice(0, start + sourceText.length)) },
    encoding: "utf8", matchMethod: `exact_utf8_text_field:${textPointer}`,
    ambiguity: offsets.length > 1 ? "Multiple occurrences; each span is distinct" : null,
    adapterId: payloadEvent.adapterId, adapterVersion: payloadEvent.adapterVersion, rawTextRedacted: true,
  }));
}

export function observeResponse(opts: { recorder: AppendOnlyJsonlRecorder; requestId: string; attemptId?: string | null;
  payloadEventId?: string | null; hmacKey?: Buffer; boundary?: string; persistRawText?: boolean }, text: string): ContextEvent {
  const secret = false;
  const raw = opts.persistRawText && text
    ? { rawTextRedacted: null as true | null, rawText: text }
    : { rawTextRedacted: true as true | null };
  return opts.recorder.record({ requestId: opts.requestId, attemptId: opts.attemptId ?? `${opts.requestId}:a1`,
    observation: "response", evidence: "runtime_loaded", coverage: "partial",
    boundary: opts.boundary ?? "message_end.assistant", sourceCategory: "model_output", sourceAlias: "Assistant response",
    contentVersionKey: contentVersionKey(text, opts.hmacKey ?? hmacKeyFromEnv()),
    parentEventIds: opts.payloadEventId ? [opts.payloadEventId] : [], byteCount: Buffer.byteLength(text),
    notes: "Response observed at runtime; later handlers may alter it. No semantic influence claim.",
    ...raw,
  });
}
