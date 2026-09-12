/**
 * Versioned context-provenance event contract for iseeagents.
 * Separate from SessionGraph generic events; pin schemaVersion before exporters.
 */

export const SCHEMA_VERSION = "iseeagents.context.v1" as const;

export type EvidenceGrade =
  | "inventoried"
  | "runtime_loaded"
  | "read_result"
  | "payload_snapshot"
  | "final_dispatch"
  | "summary_ancestor"
  | "unknown";

export type ObservationKind =
  | "inventory"
  | "load"
  | "read"
  | "transform"
  | "inclusion"
  | "response"
  | "payload"
  | "dispatch"
  | "usage"
  | "capture_health";

export type SourceCategory =
  | "user_input"
  | "system_input"
  | "file_input"
  | "model_output"
  | "instructions"
  | "skill"
  | "profile"
  | "history"
  | "tool_result"
  | "extension_generated"
  | "summary"
  | "unattributed"
  | "other";

export type CoverageStatus = "full" | "partial" | "unsupported" | "unknown";

export type ByteRange = {
  start: number;
  end: number;
};

export type ContextEvent = {
  schemaVersion: typeof SCHEMA_VERSION;
  eventId: string;
  sessionId: string;
  agentId: string;
  parentAgentId: string | null;
  requestId: string | null;
  attemptId: string | null;
  toolCallId: string | null;

  producerSeq: number;
  monotonicMs: number | null;
  wallTime: string;
  parentEventIds: string[];

  sourceCategory: SourceCategory | null;
  sourceAlias: string | null;
  sourceKey: string | null;
  contentVersionKey: string | null;
  sourceRange: ByteRange | null;
  encoding: string | null;

  observation: ObservationKind;
  evidence: EvidenceGrade;
  adapterId: string;
  adapterVersion: string;
  boundary: string;
  handlerOrdinal: number | null;
  coverage: CoverageStatus;

  requestSpan: ByteRange | null;
  sourceSpan: ByteRange | null;
  matchMethod: string | null;
  ambiguity: string | null;
  lineageEventIds: string[];

  usageInputTokens: number | null;
  usageOutputTokens: number | null;
  usageCachedTokens: number | null;
  estimatedTokens: number | null;
  byteCount: number | null;
  charCount: number | null;

  droppedEvents: number | null;
  unsupportedBoundary: string | null;
  truncation: boolean | null;
  notes: string | null;

  /** Never required; only present under explicit capture policy. */
  rawTextRedacted: true | null;
  /**
   * Optional raw text. Only set when an adapter explicitly opts in
   * (e.g. ISEEAGENTS_PERSIST_RAW_TEXT=1 or ISEEAGENTS_PERSIST_HARNESS_TEXT=1).
   * Default captures omit this field.
   */
  rawText?: string | null;
  /**
   * Absolute filesystem path for harness inputs (instructions / skills) when known.
   * Used by the HTML viewer embed step — not a content claim by itself.
   */
  sourcePath?: string | null;
};

export type AdapterCapability = {
  adapterId: string;
  adapterVersion: string;
  supportedBoundaries: string[];
  unsupportedBoundaries: string[];
  notes: string;
};

export function isContextEvent(value: unknown): value is ContextEvent {
  if (!value || typeof value !== "object") return false;
  const e = value as Record<string, unknown>;
  return (
    e.schemaVersion === SCHEMA_VERSION &&
    typeof e.eventId === "string" &&
    typeof e.sessionId === "string" &&
    typeof e.agentId === "string" &&
    typeof e.producerSeq === "number" &&
    typeof e.wallTime === "string" &&
    typeof e.observation === "string" &&
    typeof e.evidence === "string" &&
    typeof e.adapterId === "string" &&
    typeof e.boundary === "string" &&
    typeof e.coverage === "string"
  );
}

export function assertNoFabricatedUsage(event: ContextEvent): void {
  const fields = [
    event.usageInputTokens,
    event.usageOutputTokens,
    event.usageCachedTokens,
  ] as const;
  for (const v of fields) {
    if (v !== null && (!Number.isFinite(v) || v < 0)) {
      throw new Error("usage counters must be null or non-negative finite numbers");
    }
  }
}
