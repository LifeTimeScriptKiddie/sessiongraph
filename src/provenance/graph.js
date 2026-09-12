/** Browser/Node shared graph projection. Never infer causality from event order. */
export const GRAPH_VERSION = "iseeagents.provenance.graph.v1";
const observations = new Set(["inventory", "load", "read", "transform", "inclusion", "payload", "dispatch", "response", "usage", "capture_health"]);
const categories = { user_input: "User input", system_input: "System input", instructions: "Instructions", file_input: "File input", tool_result: "Tool result", skill: "Skill", profile: "Profile", summary: "Summary", model_output: "Model response", other: "Runtime resource", history: "History", extension_generated: "Generated instruction", unattributed: "Unattributed" };
export function requestKey(e) { return JSON.stringify([e.sessionId, e.agentId, e.requestId, e.attemptId]); }

export function buildProvenanceGraph(events) {
  if (!Array.isArray(events) || events.length > 10000) throw new Error("Expected at most 10,000 context events");
  const byId = new Map(), nodes = [], edges = [], issues = [];
  for (const e of events) {
    if (!e || e.schemaVersion !== "iseeagents.context.v1" || typeof e.eventId !== "string" || !e.eventId
        || typeof e.sessionId !== "string" || typeof e.agentId !== "string" || !observations.has(e.observation)
        || !Array.isArray(e.parentEventIds) || !Array.isArray(e.lineageEventIds)
        || e.parentEventIds.length + e.lineageEventIds.length > 1024
        || [...e.parentEventIds, ...e.lineageEventIds].some(id => typeof id !== "string" || !id))
      throw new Error("Invalid context event or unsupported observation");
    if (byId.has(e.eventId)) throw new Error("Duplicate event ID; cannot join provenance safely");
    byId.set(e.eventId, e);
  }
  const issue = (code, eventId, message) => issues.push({ code, eventId, message });
  const edgeKeys = new Set();
  function edge(from, to, kind, evidenceId) {
    const a = byId.get(from), b = byId.get(to);
    if (!a || !b) { issue("missing_parent", evidenceId, "Referenced event is absent: " + (!a ? from : to)); return; }
    if (a.sessionId !== b.sessionId) { issue("cross_session_link", evidenceId, "Cross-session edge requires an explicit cross-session contract"); return; }
    const key = JSON.stringify([from, to, kind, evidenceId]);
    if (!edgeKeys.has(key)) { edges.push({ from, to, kind, evidenceId }); edgeKeys.add(key); }
  }
  for (const e of events) {
    if (e.observation !== "inclusion") {
      const kind = e.observation === "response" ? "response"
        : ["payload", "dispatch"].includes(e.observation) ? "request"
        : e.observation === "transform" ? "transform"
        : ["usage", "capture_health"].includes(e.observation) ? "telemetry" : "source";
      nodes.push({ id: e.eventId, kind, category: categories[e.sourceCategory] || e.sourceCategory || "Observation",
        label: e.sourceAlias || (kind === "request" ? "Payload snapshot" : kind === "response" ? "Model response" : e.observation),
        requestKey: requestKey(e), event: e });
      for (const parent of new Set(e.parentEventIds)) {
        const p = byId.get(parent);
        const responseLink = e.observation === "response" && p && ["payload", "dispatch"].includes(p.observation);
        if (responseLink && requestKey(p) !== requestKey(e)) {
          issue("response_request_mismatch", e.eventId, "Response and parent have different request/attempt identities"); continue;
        }
        edge(parent, e.eventId, responseLink ? "response_to" : "recorded_parent", e.eventId);
      }
      for (const ancestor of new Set(e.lineageEventIds)) edge(ancestor, e.eventId, "summary_ancestor", e.eventId);
    } else {
      const [sourceId, payloadId] = e.parentEventIds;
      const source = byId.get(sourceId), payload = byId.get(payloadId);
      const range = r => r && Number.isSafeInteger(r.start) && Number.isSafeInteger(r.end) && r.start >= 0 && r.end > r.start;
      if (e.parentEventIds.length !== 2 || !source || !payload || !["payload", "dispatch"].includes(payload.observation)
          || !["inventory", "load", "read", "transform"].includes(source.observation)
          || !source.contentVersionKey || e.contentVersionKey !== source.contentVersionKey
          || e.sourceKey !== source.sourceKey || requestKey(e) !== requestKey(payload)
          || source.agentId !== payload.agentId || !range(e.sourceSpan) || !range(e.requestSpan)
          || !String(e.matchMethod || "").startsWith("exact_utf8_text_field:")
          || e.evidence !== payload.evidence || !["payload_snapshot", "final_dispatch"].includes(e.evidence)) {
        issue("unverified_match", e.eventId, "Source inclusion lacks matching version, spans or request evidence"); continue;
      }
      edge(sourceId, payloadId, "observed_text_match", e.eventId);
    }
    if (e.coverage !== "full" || e.truncation === true || (e.droppedEvents || 0) > 0)
      issue("capture_gap", e.eventId, "Capture at this boundary is " + (e.coverage || "unknown"));
  }
  // Keep evidence-reference nodes out of the diagram. Incomplete links stay in issues.
  const nodeIds = new Set(nodes.map(n => n.id));
  for (const edge of edges) if (!nodeIds.has(edge.from) || !nodeIds.has(edge.to))
    issue("hidden_reference", edge.evidenceId, "A relationship references an inclusion evidence record; inspect the source log for the full chain");
  const visibleEdges = edges.filter(e => nodeIds.has(e.from) && nodeIds.has(e.to));
  const degrees = new Map(nodes.map(n => [n.id, 0])), outgoing = new Map();
  for (const e of visibleEdges) { degrees.set(e.to, degrees.get(e.to) + 1); if (!outgoing.has(e.from)) outgoing.set(e.from, []); outgoing.get(e.from).push(e.to); }
  const queue = [...degrees].filter(([, d]) => d === 0).map(([id]) => id);
  for (let i = 0; i < queue.length; i++) for (const to of outgoing.get(queue[i]) || []) { degrees.set(to, degrees.get(to) - 1); if (degrees.get(to) === 0) queue.push(to); }
  if (queue.length !== nodes.length) issue("cycle", null, "Recorded relationships contain a cycle; this is not a valid acyclic provenance graph");
  // Matching the same payload span to multiple sources is ambiguous, not additive usage.
  const spans = new Map();
  for (const e of visibleEdges.filter(e => e.kind === "observed_text_match")) {
    const m = byId.get(e.evidenceId), key = JSON.stringify([e.to, m.matchMethod, m.requestSpan]);
    if (!spans.has(key)) spans.set(key, []); spans.get(key).push(e);
  }
  for (const group of spans.values()) if (group.length > 1)
    for (const e of group) { e.ambiguous = true; issue("ambiguous_match", e.evidenceId, "The same request span matches multiple source observations; attribution is ambiguous"); }
  return { schemaVersion: GRAPH_VERSION, nodes, edges: visibleEdges, issues,
    requests: nodes.filter(n => n.kind === "request").map(n => ({ id: n.id, label: n.event.requestId || "Unidentified request", attempt: n.event.attemptId, key: n.requestKey })),
    events };
}

export function inspectRequest(graph, requestId) {
  const request = graph.nodes.find(n => n.id === requestId && n.kind === "request");
  if (!request) throw new Error("Select a recorded payload snapshot");
  const matches = graph.edges.filter(e => e.to === requestId && e.kind === "observed_text_match");
  const responses = graph.edges.filter(e => e.from === requestId && e.kind === "response_to").map(e => graph.nodes.find(n => n.id === e.to));
  const ancestors = new Set(matches.map(e => e.from));
  let changed = true;
  while (changed) { changed = false; for (const edge of graph.edges) if (edge.kind === "summary_ancestor" && ancestors.has(edge.to) && !ancestors.has(edge.from)) { ancestors.add(edge.from); changed = true; } }
  const candidates = graph.nodes.filter(n => ["source", "transform"].includes(n.kind)
    && n.event.sessionId === request.event.sessionId && n.event.agentId === request.event.agentId);
  const usage = graph.events.filter(e => e.observation === "usage" && requestKey(e) === request.requestKey);
  return { request, matches, responses, ancestors: [...ancestors], candidates, usage,
    unmatched: candidates.filter(n => !matches.some(e => e.from === n.id)),
    outputStatus: responses.length ? "Response observed; semantic influence unknown" : "Output not recorded",
    attention: "Model-internal processing and which inputs influenced the result are not observable here" };
}
