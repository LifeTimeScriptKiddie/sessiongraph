import { it, describe } from "node:test";
import assert from "node:assert/strict";
import { buildActivityTape, activityRange, activityPhase } from "../src/activity/project.js";
import type { ContextEvent } from "../src/schema.ts";

function ev(partial: Partial<ContextEvent> & Pick<ContextEvent, "eventId" | "observation" | "boundary" | "producerSeq">): ContextEvent {
  return {
    schemaVersion: "iseeagents.context.v1",
    sessionId: "s1",
    agentId: "agent-main",
    parentAgentId: null,
    requestId: "req_1",
    attemptId: null,
    toolCallId: null,
    monotonicMs: null,
    wallTime: "2026-09-11T12:00:00.000Z",
    parentEventIds: [],
    sourceCategory: null,
    sourceAlias: null,
    sourceKey: null,
    contentVersionKey: null,
    sourceRange: null,
    encoding: null,
    evidence: "runtime_loaded",
    adapterId: "pi",
    adapterVersion: "0.2.0",
    handlerOrdinal: null,
    coverage: "partial",
    requestSpan: null,
    sourceSpan: null,
    matchMethod: null,
    ambiguity: null,
    lineageEventIds: [],
    usageInputTokens: null,
    usageOutputTokens: null,
    usageCachedTokens: null,
    estimatedTokens: null,
    byteCount: null,
    charCount: null,
    droppedEvents: null,
    unsupportedBoundary: null,
    truncation: null,
    notes: null,
    rawTextRedacted: true,
    ...partial,
  };
}

describe("activity tape projection", () => {
  it("orders input → health gap → outcome for sparse Pi captures", () => {
    const events = [
      ev({ eventId: "a", observation: "load", boundary: "before_agent_start.prompt", producerSeq: 1, sourceAlias: "user_prompt", sourceCategory: "user_input" }),
      ev({ eventId: "b", observation: "load", boundary: "before_agent_start.contextFiles", producerSeq: 2, sourceAlias: "/tmp/foo.ts" }),
      ev({ eventId: "c", observation: "response", boundary: "message_end.assistant", producerSeq: 3, evidence: "unknown", sourceCategory: "model_output" }),
    ];
    const tape = buildActivityTape(events);
    assert.equal(tape.counts.input, 2);
    assert.equal(tape.counts.outcome, 1);
    assert.ok(tape.counts.health >= 1);
    assert.equal(tape.steps[0].phase, "input");
    assert.equal(tape.steps[0].title, "User input");
    assert.match(tape.steps.find(s => s.phase === "health" && s.derived)!.title, /no provider payload/i);
    assert.equal(tape.steps.find(s => s.phase === "outcome")!.title, "Assistant response");
    const seqs = tape.steps.map(s => s.seq);
    assert.deepEqual(seqs, [...seqs].sort((a, b) => a - b));
  });

  it("never treats default byte spans as line ranges", () => {
    const withBytes = ev({
      eventId: "r1",
      observation: "read",
      boundary: "tool.read.result",
      producerSeq: 1,
      sourceAlias: "/tmp/foo.ts",
      sourceRange: { start: 0, end: 400 },
      matchMethod: null,
    });
    const range = activityRange(withBytes);
    assert.equal(range?.unit, "byte");
    const withLines = { ...withBytes, matchMethod: "runtime_line_range", sourceRange: { start: 40, end: 80 } };
    assert.equal(activityRange(withLines)?.unit, "line");
    const tape = buildActivityTape([withLines]);
    assert.match(tape.steps[0].title, /L40–L80/);
  });

  it("maps adapter ids to agent runtimes", () => {
    const tape = buildActivityTape([
      ev({ eventId: "1", observation: "load", boundary: "x", producerSeq: 1, adapterId: "claude_code" }),
    ]);
    assert.equal(tape.steps[0].agentRuntime, "claude_code");
    assert.equal(activityPhase(ev({ eventId: "2", observation: "capture_health", boundary: "gap", producerSeq: 2 })), "health");
  });
});
