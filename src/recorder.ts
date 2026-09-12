import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import {
  SCHEMA_VERSION,
  assertNoFabricatedUsage,
  isContextEvent,
  type ContextEvent,
} from "./schema.ts";
import { newEventId } from "./ids.ts";

export type RecorderOptions = {
  path: string;
  sessionId: string;
  agentId?: string;
  parentAgentId?: string | null;
  adapterId?: string;
  adapterVersion?: string;
};

export class AppendOnlyJsonlRecorder {
  readonly path: string;
  readonly sessionId: string;
  readonly agentId: string;
  readonly parentAgentId: string | null;
  readonly adapterId: string;
  readonly adapterVersion: string;
  private seq = 0;
  private dropped = 0;

  constructor(opts: RecorderOptions) {
    this.path = opts.path;
    this.sessionId = opts.sessionId;
    this.agentId = opts.agentId ?? "agent-main";
    this.parentAgentId = opts.parentAgentId ?? null;
    this.adapterId = opts.adapterId ?? "replay";
    this.adapterVersion = opts.adapterVersion ?? "0.1.0";
    mkdirSync(dirname(this.path), { recursive: true });
    if (!existsSync(this.path)) writeFileSync(this.path, "", "utf8");
    else this.seq = countLines(this.path);
  }

  nextSeq(): number {
    this.seq += 1;
    return this.seq;
  }

  record(partial: Omit<Partial<ContextEvent>, "schemaVersion" | "eventId" | "sessionId" | "producerSeq" | "wallTime"> & {
    observation: ContextEvent["observation"];
    evidence: ContextEvent["evidence"];
    boundary: string;
    coverage: ContextEvent["coverage"];
  }): ContextEvent {
    const event: ContextEvent = {
      schemaVersion: SCHEMA_VERSION,
      eventId: newEventId(),
      sessionId: this.sessionId,
      agentId: partial.agentId ?? this.agentId,
      parentAgentId: partial.parentAgentId ?? this.parentAgentId,
      requestId: partial.requestId ?? null,
      attemptId: partial.attemptId ?? null,
      toolCallId: partial.toolCallId ?? null,
      producerSeq: this.nextSeq(),
      monotonicMs: partial.monotonicMs ?? null,
      wallTime: new Date().toISOString(),
      parentEventIds: partial.parentEventIds ?? [],
      sourceCategory: partial.sourceCategory ?? null,
      sourceAlias: partial.sourceAlias ?? null,
      sourceKey: partial.sourceKey ?? null,
      contentVersionKey: partial.contentVersionKey ?? null,
      sourceRange: partial.sourceRange ?? null,
      encoding: partial.encoding ?? null,
      observation: partial.observation,
      evidence: partial.evidence,
      adapterId: partial.adapterId ?? this.adapterId,
      adapterVersion: partial.adapterVersion ?? this.adapterVersion,
      boundary: partial.boundary,
      handlerOrdinal: partial.handlerOrdinal ?? null,
      coverage: partial.coverage,
      requestSpan: partial.requestSpan ?? null,
      sourceSpan: partial.sourceSpan ?? null,
      matchMethod: partial.matchMethod ?? null,
      ambiguity: partial.ambiguity ?? null,
      lineageEventIds: partial.lineageEventIds ?? [],
      usageInputTokens: partial.usageInputTokens ?? null,
      usageOutputTokens: partial.usageOutputTokens ?? null,
      usageCachedTokens: partial.usageCachedTokens ?? null,
      estimatedTokens: partial.estimatedTokens ?? null,
      byteCount: partial.byteCount ?? null,
      charCount: partial.charCount ?? null,
      droppedEvents: partial.droppedEvents ?? null,
      unsupportedBoundary: partial.unsupportedBoundary ?? null,
      truncation: partial.truncation ?? null,
      notes: partial.notes ?? null,
      rawTextRedacted: partial.rawTextRedacted ?? null,
      sourcePath: partial.sourcePath ?? null,
      ...(partial.rawText != null && partial.rawText !== ""
        ? { rawText: partial.rawText }
        : {}),
    };
    assertNoFabricatedUsage(event);
    appendFileSync(this.path, `${JSON.stringify(event)}\n`, "utf8");
    return event;
  }

  markDropped(count = 1, boundary = "unknown"): ContextEvent {
    this.dropped += count;
    return this.record({
      observation: "capture_health",
      evidence: "unknown",
      boundary,
      coverage: "partial",
      droppedEvents: this.dropped,
      notes: `dropped ${count} event(s); cumulative=${this.dropped}`,
    });
  }

  get droppedCount(): number {
    return this.dropped;
  }
}

export function readJsonl(path: string): ContextEvent[] {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const parsed = JSON.parse(line) as unknown;
      if (!isContextEvent(parsed)) throw new Error(`invalid event in ${path}`);
      return parsed;
    });
}

function countLines(path: string): number {
  const text = readFileSync(path, "utf8");
  if (!text) return 0;
  return text.trimEnd().split("\n").filter(Boolean).length;
}

/** Deep freeze helper to detect accidental payload mutation in tests. */
export function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const v of Object.values(value as object)) deepFreeze(v);
  }
  return value;
}

export function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_k, v) => {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const sorted: Record<string, unknown> = {};
      for (const key of Object.keys(v as object).sort()) {
        sorted[key] = (v as Record<string, unknown>)[key];
      }
      return sorted;
    }
    return v;
  });
}
