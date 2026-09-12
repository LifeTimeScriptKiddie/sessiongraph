/** Derived activity tape from iseeagents.context.v1 events. No second storage stream. */
export const ACTIVITY_VERSION = "iseeagents.activity.v1";

const LINE_METHODS = new Set(["runtime_line_range", "runtime_lines", "tool_line_range"]);

export function agentRuntime(adapterId) {
  const a = String(adapterId || "").toLowerCase();
  if (a === "pi") return "pi";
  if (a.includes("claude")) return "claude_code";
  if (a.includes("codex")) return "codex";
  if (a.includes("cursor")) return "cursor_agent";
  return "unknown";
}

export function activityPhase(event) {
  const obs = event.observation;
  if (obs === "capture_health") return "health";
  if (obs === "response") return "outcome";
  if (obs === "payload" || obs === "dispatch") return "boundary";
  if (obs === "usage") return null;
  if (obs === "read" || obs === "transform" || obs === "inclusion") return "process";
  if (obs === "load" || obs === "inventory") {
    if (event.sourceCategory === "tool_result") return "process";
    if (/(?:^|[._])tool(?:[._]|$)/.test(String(event.boundary || ""))) return "process";
    return "input";
  }
  return "health";
}

/** Line ranges only when matchMethod says so; otherwise bytes or unknown. Never invent lines. */
export function activityRange(event) {
  const r = event.sourceRange;
  if (!r || typeof r.start !== "number" || typeof r.end !== "number") return null;
  const method = String(event.matchMethod || "");
  if (LINE_METHODS.has(method) || method.includes("line_range")) {
    return { start: r.start, end: r.end, unit: "line" };
  }
  return { start: r.start, end: r.end, unit: "byte" };
}

function basename(path) {
  if (!path) return null;
  const parts = String(path).split(/[/\\]/);
  return parts[parts.length - 1] || path;
}

function formatRange(range) {
  if (!range) return null;
  if (range.unit === "line") return `L${range.start}–L${range.end}`;
  return `bytes [${range.start}, ${range.end})`;
}

export function activityTitle(event, phase, range) {
  const alias = event.sourceAlias || event.sourceKey || event.boundary || event.observation;
  const short = basename(alias) || alias;
  const span = formatRange(range);
  if (phase === "outcome") return "Assistant response";
  if (phase === "boundary") return event.observation === "dispatch" ? "Provider dispatch" : "Provider request snapshot";
  if (phase === "health") {
    if (event.unsupportedBoundary) return `Capture gap: ${event.unsupportedBoundary}`;
    if (event.boundary === "source_matching.eviction") return "Capture health: source matching eviction";
    return event.sourceAlias ? `Capture health: ${short}` : `Capture health: ${event.boundary || "gap"}`;
  }
  if (phase === "process") {
    const tool = event.toolCallId ? `tool ${event.toolCallId.slice(0, 8)}` : "tool/process";
    if (span) return `${short}: ${span}`;
    if (event.sourceAlias || event.sourceKey) return `${short} · range unknown`;
    return `${tool} · ${event.boundary || event.observation}`;
  }
  // input
  if (String(event.boundary || "").includes("prompt") || event.sourceCategory === "user_input") return "User input";
  if (event.sourceCategory === "instructions" || String(event.boundary || "").includes("contextFiles")) {
    const path = event.sourcePath || event.sourceAlias;
    return `Instructions: ${basename(path) || path || "context"}`;
  }
  if (event.sourceCategory === "system_input" || String(event.boundary || "").includes("systemPrompt")) {
    return "Assembled system prompt";
  }
  if (event.sourceCategory === "skill" || String(event.boundary || "").includes("skills")) {
    return `Skill: ${event.sourceAlias || short}`;
  }
  if (event.sourceCategory === "file_input") {
    return span ? `Load ${short} (${span})` : `Load ${short}`;
  }
  return short;
}

function pathFor(event) {
  if (event.sourcePath) return event.sourcePath;
  const fromNotes = typeof event.notes === "string" && event.notes.match(/(?:^|\n)sourcePath=([^\n]+)/);
  if (fromNotes) return fromNotes[1].trim();
  const alias = event.sourceAlias;
  if (alias && (alias.includes("/") || alias.includes("\\") || /\.[a-z0-9]+$/i.test(alias))) return alias;
  return event.sourceKey || null;
}

/**
 * Project events → chronological ActivityStep[].
 * Adds one derived health row per turn that has input/outcome but no payload/dispatch.
 */
export function buildActivityTape(events) {
  if (!Array.isArray(events) || events.length > 10000) throw new Error("Expected at most 10,000 context events");
  const steps = [];
  const byRequest = new Map();

  for (const event of events) {
    if (!event || event.schemaVersion !== "iseeagents.context.v1") continue;
    const phase = activityPhase(event);
    if (!phase) continue;
    const range = activityRange(event);
    const step = {
      eventId: event.eventId,
      seq: event.producerSeq,
      wallTime: event.wallTime,
      phase,
      agentRuntime: agentRuntime(event.adapterId),
      title: activityTitle(event, phase, range),
      path: pathFor(event),
      range,
      toolName: event.toolCallId ? (event.sourceAlias || event.boundary || "tool") : null,
      evidence: event.evidence,
      requestId: event.requestId,
      hasMessagePreview: Boolean(event.rawText),
      coverage: event.coverage,
      boundary: event.boundary,
      adapterId: event.adapterId,
      agentId: event.agentId,
      attemptId: event.attemptId,
      toolCallId: event.toolCallId,
      matchMethod: event.matchMethod,
      ambiguity: event.ambiguity,
      parentEventIds: event.parentEventIds || [],
      usageInputTokens: event.usageInputTokens,
      usageOutputTokens: event.usageOutputTokens,
      usageCachedTokens: event.usageCachedTokens,
      unsupportedBoundary: event.unsupportedBoundary,
      derived: false,
      event,
    };
    steps.push(step);
    const rid = event.requestId || "_none";
    if (!byRequest.has(rid)) byRequest.set(rid, { hasBoundary: false, hasIO: false, maxSeq: 0, wallTime: event.wallTime, agentRuntime: step.agentRuntime, adapterId: event.adapterId, agentId: event.agentId });
    const bucket = byRequest.get(rid);
    if (phase === "boundary") bucket.hasBoundary = true;
    if (phase === "input" || phase === "outcome" || phase === "process") bucket.hasIO = true;
    if (event.producerSeq > bucket.maxSeq) { bucket.maxSeq = event.producerSeq; bucket.wallTime = event.wallTime; }
  }

  for (const [requestId, bucket] of byRequest) {
    if (requestId === "_none") continue;
    if (!bucket.hasIO || bucket.hasBoundary) continue;
    const already = steps.some(s => s.requestId === requestId && s.phase === "health" && (
      /no provider payload/i.test(s.title)
      || s.unsupportedBoundary === "before_provider_request"
      || s.boundary === "capture_health.missing_provider_payload"
    ));
    if (already) continue;
    steps.push({
      eventId: `derived:gap:${requestId}`,
      seq: bucket.maxSeq + 0.5,
      wallTime: bucket.wallTime,
      phase: "health",
      agentRuntime: bucket.agentRuntime,
      title: "Capture gap: no provider payload snapshot",
      path: null,
      range: null,
      toolName: null,
      evidence: "unknown",
      requestId,
      hasMessagePreview: false,
      coverage: "unsupported",
      boundary: "capture_health.missing_provider_payload",
      adapterId: bucket.adapterId,
      agentId: bucket.agentId,
      attemptId: null,
      toolCallId: null,
      matchMethod: null,
      ambiguity: "Derived from absence of payload/dispatch for this turn",
      parentEventIds: [],
      usageInputTokens: null,
      usageOutputTokens: null,
      usageCachedTokens: null,
      unsupportedBoundary: "before_provider_request",
      derived: true,
      event: null,
    });
  }

  steps.sort((a, b) => {
    if (a.seq !== b.seq) return a.seq - b.seq;
    return String(a.wallTime).localeCompare(String(b.wallTime));
  });

  const turns = [];
  const seen = new Set();
  for (const step of steps) {
    const id = step.requestId;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    turns.push(id);
  }

  return {
    version: ACTIVITY_VERSION,
    steps,
    turns,
    counts: {
      events: events.length,
      steps: steps.length,
      input: steps.filter(s => s.phase === "input").length,
      process: steps.filter(s => s.phase === "process").length,
      boundary: steps.filter(s => s.phase === "boundary").length,
      outcome: steps.filter(s => s.phase === "outcome").length,
      health: steps.filter(s => s.phase === "health").length,
    },
  };
}
