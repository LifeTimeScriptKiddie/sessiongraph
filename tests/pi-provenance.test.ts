import { it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import observer from "../extensions/pi/iseeagents-observer.ts";
import { readJsonl, deepFreeze, stableStringify } from "../src/recorder.ts";
import { buildProvenanceGraph, inspectRequest } from "../src/provenance/graph.js";
import { payloadTextPointers } from "../src/provenance/text-fields.ts";

it("Pi hooks record input matches and response associations across separate provider calls without mutation", async () => {
  const hooks = new Map<string, Function>();
  await observer({ on: (name: string, fn: Function) => hooks.set(name, fn) } as any);
  const cwd = mkdtempSync(join(tmpdir(), "isee-pi-graph-"));
  const ctx = { cwd, sessionManager: { getSessionFile: () => "fixture-session.jsonl" } };
  await hooks.get("session_start")!({}, ctx);
  await hooks.get("before_agent_start")!({ prompt: "User fixture", systemPrompt: "System fixture", systemPromptOptions: { contextFiles: [], skills: [] } }, ctx);
  await hooks.get("tool_result")!({ toolCallId: "read1", toolName: "read", input: { path: "excerpt.txt" }, content: [{ type: "text", text: "File excerpt" }] }, ctx);
  const payload = deepFreeze({ messages: [{ role: "system", content: "System fixture" }, { role: "user", content: "User fixture" }, { role: "tool", content: "File excerpt" }] });
  const before = stableStringify(payload);
  for (let i = 0; i < 2; i++) {
    assert.equal(await hooks.get("before_provider_request")!({ payload }, ctx), undefined);
    assert.equal(await hooks.get("message_end")!({ message: { role: "assistant", content: [{ type: "text", text: "Output fixture" }] } }, ctx), undefined);
  }
  assert.equal(stableStringify(payload), before);
  const events = readJsonl(join(cwd, ".iseeagents/fixture-session.jsonl"));
  const turnIds = [...new Set(events.map((e) => e.requestId).filter(Boolean))];
  assert.equal(turnIds.length, 1, "turn requestId must stay stable across provider calls");
  const graphEvents = events.filter((e) => e.observation !== "capture_health");
  const graph = buildProvenanceGraph(graphEvents);
  assert.equal(graph.requests.length, 2);
  assert.notEqual(graph.requests[0].key, graph.requests[1].key);
  assert.equal(graph.requests[0].label, graph.requests[1].label);
  for (const request of graph.requests) {
    const view = inspectRequest(graph, request.id);
    assert.equal(view.matches.length, 3);
    assert.equal(view.responses.length, 1);
  }
  assert.equal(/User fixture|System fixture|File excerpt|Output fixture/.test(JSON.stringify(events)), false);
  const next = { ...ctx, sessionManager: { getSessionFile: () => "another-session.jsonl" } };
  await hooks.get("session_start")!({}, next);
  await hooks.get("message_end")!({ message: { role: "assistant", content: [] } }, next);
  assert.equal(readJsonl(join(cwd, ".iseeagents/another-session.jsonl")).length, 0);
});
it("matching selectors include only explicit provider content fields, not metadata or role strings", () => {
  assert.deepEqual(payloadTextPointers({ system: "s", messages: [{ role: "user", content: [{ type: "text", text: "a" }] }], metadata: { content: "hidden" } }), ["/system", "/messages/0/content/0/text"]);
  assert.deepEqual(payloadTextPointers({ input: "hello" }), ["/input"]);
  assert.deepEqual(payloadTextPointers({ metadata: "only metadata" }), []);
});
