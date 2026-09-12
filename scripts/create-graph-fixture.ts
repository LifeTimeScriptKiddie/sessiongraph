import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { AppendOnlyJsonlRecorder, deepFreeze, readJsonl } from "../src/recorder.ts";
import { keyedId, contentVersionKey } from "../src/ids.ts";
import { observeProviderPayload, observeUsage } from "../src/adapters/pi.ts";
import { recordTextMatches, observeResponse } from "../src/provenance/observe.ts";
import type { ContextEvent } from "../src/schema.ts";

export function createGraphFixture(path: string): ContextEvent[] {
  if (existsSync(path)) throw new Error("Choose a fresh fixture path; existing captures are never replaced");
  const recorder = new AppendOnlyJsonlRecorder({ path, sessionId: "synthetic-graph-demo", adapterId: "fixture", adapterVersion: "graph-v1" });
  const key = Buffer.from("synthetic-graph-fixture-key");
  const source = (category: ContextEvent["sourceCategory"], alias: string, text: string, requestId = "r1") => recorder.record({
    requestId, attemptId: `${requestId}:a1`, observation: category === "file_input" ? "read" : "load",
    evidence: category === "file_input" ? "read_result" : "runtime_loaded", coverage: "full", boundary: "fixture.input",
    sourceCategory: category, sourceAlias: alias, sourceKey: keyedId("source", alias, key),
    contentVersionKey: contentVersionKey(text, key), byteCount: Buffer.byteLength(text), estimatedTokens: Math.ceil(text.length / 4), rawTextRedacted: true,
  });
  const userText = "Explain why the sample returns four.", systemText = "Use only the supplied sample.", fileText = "return 2 + 2;";
  const user = source("user_input", "Your question", userText);
  const system = source("system_input", "System instruction", systemText);
  const file = source("file_input", "sample.ts · excerpt v1", fileText);
  recorder.record({ requestId: "r1", attemptId: "r1:a1", observation: "inventory", evidence: "inventoried", coverage: "full",
    boundary: "fixture.inventory", sourceCategory: "skill", sourceAlias: "SKILL.md · available only" });
  recorder.record({ requestId: "r1", attemptId: "r1:a1", observation: "load", evidence: "runtime_loaded", coverage: "full",
    boundary: "extension_execute", sourceCategory: "other", sourceAlias: "Observer extension · runs only" });
  const payload = deepFreeze({ messages: [{ role: "system", content: systemText }, { role: "user", content: userText }, { role: "tool", content: fileText }] });
  let request!: ContextEvent;
  observeProviderPayload({ recorder, requestId: "r1", attemptId: "r1:a1", hmacKey: key, provisional: true, onRecorded: e => { request = e; } }, payload);
  for (const [input, text, pointer] of [[user, userText, "/messages/1/content"], [system, systemText, "/messages/0/content"], [file, fileText, "/messages/2/content"]] as const)
    recordTextMatches({ recorder, source: input, sourceText: text, payloadEvent: request, payload, textPointer: pointer, hmacKey: key });
  observeResponse({ recorder, requestId: "r1", attemptId: "r1:a1", payloadEventId: request.eventId, hmacKey: key }, "The expression adds two and two, producing four.");
  observeUsage({ recorder, requestId: "r1", attemptId: "r1:a1" }, { input: 240, output: 32, cached: 80 });
  const summaryText = "Earlier task: explain the sample expression 2 + 2.";
  const summary = recorder.record({ requestId: "r2", attemptId: "r2:a1", observation: "transform", evidence: "summary_ancestor",
    boundary: "fixture.compaction", coverage: "full", sourceCategory: "summary", sourceAlias: "Compaction summary",
    sourceKey: keyedId("summary", "s1", key), contentVersionKey: contentVersionKey(summaryText, key),
    lineageEventIds: [user.eventId, system.eventId, file.eventId], rawTextRedacted: true });
  const payload2 = deepFreeze({ messages: [{ role: "system", content: summaryText }] });
  let request2!: ContextEvent;
  observeProviderPayload({ recorder, requestId: "r2", attemptId: "r2:a1", hmacKey: key, final: true, onRecorded: e => { request2 = e; } }, payload2);
  recordTextMatches({ recorder, source: summary, sourceText: summaryText, payloadEvent: request2, payload: payload2, textPointer: "/messages/0/content", hmacKey: key });
  observeResponse({ recorder, requestId: "r2", attemptId: "r2:a1", payloadEventId: request2.eventId, hmacKey: key }, "Continuing from the summary.");
  source("file_input", "sample.ts · excerpt v2", "return 3 + 3;", "r3");
  observeProviderPayload({ recorder, requestId: "r3", attemptId: "r3:a2", hmacKey: key, provisional: true }, { messages: [] });
  recorder.record({ requestId: "r3", attemptId: "r3:a2", observation: "capture_health", evidence: "unknown", coverage: "partial",
    boundary: "fixture.capture_loss", droppedEvents: 2, parentEventIds: ["missing-observation"] });
  observeUsage({ recorder, requestId: "r3", attemptId: "r3:a2" }, { input: null, output: 9, cached: null });
  return readJsonl(path);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!process.argv[2]) throw new Error("usage: create-graph-fixture.ts NEW_CAPTURE.jsonl");
  console.log(`Recorded ${createGraphFixture(process.argv[2]).length} synthetic events`);
}
