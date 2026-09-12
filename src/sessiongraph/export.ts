/**
 * SessionGraph consumer seam.
 * Exports iseeagents.context.v1 JSONL into SessionGraph's generic JSONL shape
 * without forking SessionGraph's Event/Session model. Content-free by default.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { readJsonl } from "../recorder.ts";
import { SCHEMA_VERSION, type ContextEvent } from "../schema.ts";

export const SEAM_VERSION = "iseeagents.sessiongraph.seam.v2" as const;

export type SessionGraphGenericEvent = {
  id: string;
  parent_id: string | null;
  parent_ids: string[];
  parent_relations: Record<string, string>;
  kind: string;
  role: string | null;
  name: string | null;
  timestamp: string;
  content: string;
  is_error: boolean;
  usage?: Record<string, number>;
  /** Sidecar fields ignored by SessionGraph parse_generic; kept for join tooling. */
  iseeagents?: {
    seamVersion: typeof SEAM_VERSION;
    schemaVersion: typeof SCHEMA_VERSION;
    sessionId: string;
    requestId: string | null;
    attemptId: string | null;
    evidence: string;
    coverage: string;
    boundary: string;
    adapterId: string;
    sourceKey: string | null;
    contentVersionKey: string | null;
    parentEventIds: string[];
    lineageEventIds: string[];
  };
};

export type ExportOptions = {
  /** When true, still never writes raw prompt text — only empty content. */
  includeContent?: boolean;
};

function requireUniqueIds(events: ContextEvent[]): void {
  const seen = new Set<string>();
  for (const event of events) {
    if (seen.has(event.eventId)) throw new Error("Duplicate eventId prevents an unambiguous SessionGraph join");
    seen.add(event.eventId);
  }
}

function mapKind(observation: ContextEvent["observation"]): string {
  return `iseeagents_${observation}`;
}

function mapParentRelations(event: ContextEvent): Record<string, string> {
  const relations: Record<string, string> = {};
  for (const [index, parentId] of event.parentEventIds.entries()) {
    if (event.observation === "response") relations[parentId] = "response_to";
    else if (event.observation === "inclusion") {
      // Inclusion records point to both the observed source and captured request.
      // The exact source -> request match remains in iseeagents' evidence graph.
      relations[parentId] = index === 0 ? "match_source" : "match_request";
    } else relations[parentId] = "recorded_parent";
  }
  for (const parentId of event.lineageEventIds) relations[parentId] = "summary_ancestor";
  return relations;
}

export function toSessionGraphEvent(
  event: ContextEvent,
  _opts: ExportOptions = {},
): SessionGraphGenericEvent {
  const usage: Record<string, number> = {};
  if (event.usageInputTokens != null) usage.input = event.usageInputTokens;
  if (event.usageOutputTokens != null) usage.output = event.usageOutputTokens;
  if (event.usageCachedTokens != null) usage.cached = event.usageCachedTokens;

  const parents = [...new Set([...event.parentEventIds, ...event.lineageEventIds])];
  return {
    id: event.eventId,
    parent_id: parents[0] ?? null,
    parent_ids: parents,
    parent_relations: mapParentRelations(event),
    kind: mapKind(event.observation),
    role: event.sourceCategory,
    name: event.sourceAlias,
    timestamp: event.wallTime,
    content: "", // content-free seam; provenance stays in iseeagents JSONL/SQLite
    is_error: event.observation === "capture_health" && (event.droppedEvents ?? 0) > 0,
    ...(Object.keys(usage).length ? { usage } : {}),
    iseeagents: {
      seamVersion: SEAM_VERSION,
      schemaVersion: SCHEMA_VERSION,
      sessionId: event.sessionId,
      requestId: event.requestId,
      attemptId: event.attemptId,
      evidence: event.evidence,
      coverage: event.coverage,
      boundary: event.boundary,
      adapterId: event.adapterId,
      sourceKey: event.sourceKey,
      contentVersionKey: event.contentVersionKey,
      parentEventIds: [...event.parentEventIds],
      lineageEventIds: [...event.lineageEventIds],
    },
  };
}

export function exportEventsForSessionGraph(
  events: ContextEvent[],
  opts: ExportOptions = {},
): SessionGraphGenericEvent[] {
  requireUniqueIds(events);
  return events.map((e) => toSessionGraphEvent(e, opts));
}

export function exportJsonlForSessionGraph(
  jsonlPath: string,
  outPath: string,
  opts: ExportOptions = {},
): { count: number; sessionIds: string[] } {
  const events = readJsonl(jsonlPath);
  const mapped = exportEventsForSessionGraph(events, opts);
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(
    outPath,
    mapped.map((e) => JSON.stringify(e)).join("\n") + (mapped.length ? "\n" : ""),
    "utf8",
  );
  return {
    count: mapped.length,
    sessionIds: [...new Set(events.map((e) => e.sessionId))],
  };
}

export type JoinHit = {
  eventId: string;
  sessionId: string;
  requestId: string | null;
  kind: string;
  evidence: string | null;
  coverage: string | null;
  boundary: string | null;
};

/**
 * Join SessionGraph analysis node IDs to iseeagents events by eventId.
 * analysis.graph.nodes[].id must equal ContextEvent.eventId from the export.
 */
export function joinSessionGraphAnalysis(
  analysis: {
    graph?: { nodes?: Array<{ id: string; kind?: string }> };
    events?: Array<{ id: string }>;
  },
  provenance: ContextEvent[],
): JoinHit[] {
  requireUniqueIds(provenance);
  const byId = new Map(provenance.map((e) => [e.eventId, e]));
  const ids = new Set<string>();
  for (const n of analysis.graph?.nodes ?? []) ids.add(n.id);
  for (const e of analysis.events ?? []) ids.add(e.id);

  const hits: JoinHit[] = [];
  for (const id of ids) {
    const ev = byId.get(id);
    if (!ev) continue;
    hits.push({
      eventId: id,
      sessionId: ev.sessionId,
      requestId: ev.requestId,
      kind: mapKind(ev.observation),
      evidence: ev.evidence,
      coverage: ev.coverage,
      boundary: ev.boundary,
    });
  }
  return hits;
}
