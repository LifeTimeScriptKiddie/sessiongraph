import { it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createGraphFixture } from "../scripts/create-graph-fixture.ts";
import { buildProvenanceGraph, inspectRequest } from "../src/provenance/graph.js";
import { exportEventsForSessionGraph, joinSessionGraphAnalysis } from "../src/sessiongraph/export.ts";
import { recordTextMatches } from "../src/provenance/observe.ts";
import { AppendOnlyJsonlRecorder, stableStringify, deepFreeze } from "../src/recorder.ts";
import { contentVersionKey } from "../src/ids.ts";

const root = mkdtempSync(join(tmpdir(), "iseeagents-graph-"));
const events = createGraphFixture(join(root, "fixture.jsonl"));
const graph = buildProvenanceGraph(events);

it("matches only observed user/system/file input and keeps unlinked resources separate", () => {
  const view = inspectRequest(graph, graph.requests[0].id);
  assert.equal(view.matches.length, 3);
  assert.deepEqual(view.matches.map(e => events.find(n => n.eventId === e.from)!.sourceCategory).sort(), ["file_input", "system_input", "user_input"]);
  assert.ok(view.unmatched.some(n => n.event.sourceCategory === "skill"));
  assert.ok(view.unmatched.some(n => n.event.boundary === "extension_execute"));
  assert.equal(view.responses.length, 1);
});
it("summary ancestry does not become direct input attribution or duplicate usage", () => {
  const view = inspectRequest(graph, graph.requests[1].id);
  assert.equal(view.matches.length, 1);
  assert.equal(graph.nodes.find(n => n.id === view.matches[0].from)!.kind, "transform");
  assert.equal(graph.edges.filter(e => e.kind === "summary_ancestor").length, 3);
  assert.equal(view.ancestors.length, 4);
  assert.equal(view.usage.length, 0);
});
it("usage and same request IDs never fabricate an observed response", () => {
  const view = inspectRequest(graph, graph.requests[2].id);
  assert.equal(view.matches.length, 0);
  assert.equal(view.outputStatus, "Output not recorded");
  assert.equal(view.usage[0].usageOutputTokens, 9);
  assert.ok(graph.issues.some(i => i.code === "missing_parent"));
});
it("export retains all declared parents and summary ancestry with explicit roots", () => {
  const rows = exportEventsForSessionGraph(events);
  assert.deepEqual(rows[0].parent_ids, []);
  const summary = events.find(e => e.observation === "transform")!;
  assert.deepEqual(rows.find(e => e.id === summary.eventId)!.parent_ids, summary.lineageEventIds);
  assert.equal(rows.find(e => e.kind === "iseeagents_inclusion")!.parent_ids.length, 2);
});
it("missing, duplicate, cyclic and cross-session graph evidence stays visible or fails closed", () => {
  assert.throws(() => buildProvenanceGraph([...events, events[0]]), /Duplicate/);
  assert.throws(() => exportEventsForSessionGraph([...events, events[0]]), /Duplicate/);
  assert.throws(() => joinSessionGraphAnalysis({}, [...events, events[0]]), /Duplicate/);
  const cyclic = structuredClone(events.slice(0, 2));
  cyclic[0].parentEventIds = [cyclic[1].eventId]; cyclic[1].parentEventIds = [cyclic[0].eventId];
  assert.ok(buildProvenanceGraph(cyclic).issues.some(i => i.code === "cycle"));
  cyclic[1].sessionId = "another";
  assert.ok(buildProvenanceGraph(cyclic).issues.some(i => i.code === "cross_session_link"));
});
it("unverified matches and mismatched response attempts are not accepted as causal edges", () => {
  const modified = structuredClone(events);
  const match = modified.find(e => e.observation === "inclusion")!;
  match.requestSpan = null;
  const response = modified.find(e => e.observation === "response")!;
  response.attemptId = "other-attempt";
  const result = buildProvenanceGraph(modified);
  assert.ok(result.issues.some(i => i.code === "unverified_match"));
  assert.ok(result.issues.some(i => i.code === "response_request_mismatch"));
  assert.equal(inspectRequest(result, result.requests[0].id).responses.length, 0);
});
it("duplicate source matches are ambiguous rather than additive token credit", () => {
  const match = events.find(e => e.observation === "inclusion")!;
  const result = buildProvenanceGraph([...events, { ...match, eventId: "alternative-match" }]);
  assert.ok(result.issues.some(i => i.code === "ambiguous_match"));
});
it("exact matching verifies captured versions, Unicode byte spans and never mutates payload", () => {
  const recorder = new AppendOnlyJsonlRecorder({ path: join(root, "unicode.jsonl"), sessionId: "unicode" });
  const key = Buffer.from("fixture");
  const source = recorder.record({ observation: "read", evidence: "read_result", boundary: "read", coverage: "full",
    sourceKey: "file", contentVersionKey: contentVersionKey("café", key) });
  const payload = deepFreeze({ input: "é café" });
  const serialized = stableStringify(payload);
  const p = recorder.record({ requestId: "r", observation: "payload", evidence: "payload_snapshot", boundary: "capture", coverage: "partial",
    contentVersionKey: contentVersionKey(serialized, key) });
  const opts = { recorder, source, sourceText: "café", payloadEvent: p, payload, textPointer: "/input", hmacKey: key };
  const matches = recordTextMatches(opts);
  assert.deepEqual(matches[0].requestSpan, { start: 3, end: 8 });
  assert.deepEqual(matches[0].sourceSpan, { start: 0, end: 5 });
  assert.equal(stableStringify(payload), serialized);
  assert.equal(JSON.stringify(matches).includes("café"), false);
  assert.throws(() => recordTextMatches({ ...opts, sourceText: "changed" }), /version mismatch/);
  assert.throws(() => recordTextMatches({ ...opts, textPointer: "/missing" }), /not found/);
});
