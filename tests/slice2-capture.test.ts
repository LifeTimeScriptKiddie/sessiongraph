import { it, describe } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  extractToolPathAndRange,
  observeToolCall,
  observeToolResult,
  PI_ADAPTER_VERSION,
} from "../src/adapters/pi.ts";
import { AppendOnlyJsonlRecorder, readJsonl } from "../src/recorder.ts";
import observer from "../extensions/pi/iseeagents-observer.ts";

describe("slice 2 capture: tool spans + stable turn requestId", () => {
  it("extracts runtime line ranges from read tool args only", () => {
    const withRange = extractToolPathAndRange("read", { path: "/tmp/a.ts", offset: 10, limit: 20 });
    assert.equal(withRange.path, "/tmp/a.ts");
    assert.deepEqual(withRange.range, { start: 10, end: 29 });
    assert.equal(withRange.matchMethod, "runtime_line_range");
    assert.equal(withRange.observation, "read");

    const pathOnly = extractToolPathAndRange("read", { path: "/tmp/a.ts" });
    assert.equal(pathOnly.path, "/tmp/a.ts");
    assert.equal(pathOnly.range, null);
    assert.equal(pathOnly.matchMethod, null);

    const edit = extractToolPathAndRange("edit", { path: "/tmp/b.ts" });
    assert.equal(edit.observation, "transform");
    assert.equal(edit.range, null);
  });

  it("observeToolResult does not invent 0..N byte ranges", () => {
    const dir = mkdtempSync(join(tmpdir(), "isee-tool-"));
    const recorder = new AppendOnlyJsonlRecorder({
      path: join(dir, "t.jsonl"),
      sessionId: "s",
      adapterId: "pi",
      adapterVersion: PI_ADAPTER_VERSION,
    });
    const event = observeToolResult(
      { recorder, requestId: "r1", attemptId: "r1:a1" },
      { toolCallId: "c1", toolName: "bash", content: "hello world" },
    );
    assert.equal(event.sourceRange, null);
    assert.equal(event.matchMethod, null);
    assert.match(String(event.notes), /refusing to invent/i);
  });

  it("observeToolCall + result keep path and runtime lines", () => {
    const dir = mkdtempSync(join(tmpdir(), "isee-tool2-"));
    const recorder = new AppendOnlyJsonlRecorder({
      path: join(dir, "t.jsonl"),
      sessionId: "s",
      adapterId: "pi",
      adapterVersion: PI_ADAPTER_VERSION,
    });
    const start = observeToolCall(
      { recorder, requestId: "r1" },
      { toolCallId: "c1", toolName: "read", input: { path: "src/a.ts", offset: 40, limit: 10 } },
    );
    const result = observeToolResult(
      { recorder, requestId: "r1" },
      {
        toolCallId: "c1",
        toolName: "read",
        content: "line\n".repeat(10),
        input: { path: "src/a.ts", offset: 40, limit: 10 },
      },
    );
    assert.equal(start.boundary, "tool_call.start");
    assert.equal(start.sourceAlias, "src/a.ts");
    assert.deepEqual(start.sourceRange, { start: 40, end: 49 });
    assert.equal(start.matchMethod, "runtime_line_range");
    assert.equal(result.sourceAlias, "src/a.ts");
    assert.deepEqual(result.sourceRange, { start: 40, end: 49 });
    assert.equal(result.matchMethod, "runtime_line_range");
  });

  it("Pi observer keeps turn requestId stable across payload + tools + response", async () => {
    const hooks = new Map<string, Function>();
    await observer({ on: (name: string, fn: Function) => hooks.set(name, fn) } as any);
    const cwd = mkdtempSync(join(tmpdir(), "isee-stable-"));
    const ctx = { cwd, sessionManager: { getSessionFile: () => "stable-session.jsonl" } };
    await hooks.get("session_start")!({}, ctx);
    await hooks.get("before_agent_start")!(
      { prompt: "Turn prompt", systemPrompt: "Sys", systemPromptOptions: { contextFiles: [], skills: [] } },
      ctx,
    );
    await hooks.get("tool_call")!(
      { toolCallId: "t1", toolName: "read", input: { path: "f.ts", offset: 1, limit: 5 } },
      ctx,
    );
    await hooks.get("tool_result")!(
      {
        toolCallId: "t1",
        toolName: "read",
        input: { path: "f.ts", offset: 1, limit: 5 },
        content: [{ type: "text", text: "aaaa\nbbbb\n" }],
      },
      ctx,
    );
    assert.equal(await hooks.get("before_provider_request")!({ payload: { messages: [{ role: "user", content: "Turn prompt" }] } }, ctx), undefined);
    assert.equal(
      await hooks.get("message_end")!({ message: { role: "assistant", content: [{ type: "text", text: "done" }], api: "openai" } }, ctx),
      undefined,
    );
    const events = readJsonl(join(cwd, ".iseeagents/stable-session.jsonl"));
    const ids = [...new Set(events.map((e) => e.requestId).filter(Boolean))];
    assert.equal(ids.length, 1, `expected one turn requestId, got ${ids.join(",")}`);
    assert.ok(events.some((e) => e.boundary === "tool_call.start" && e.sourceRange?.start === 1));
    assert.ok(events.some((e) => e.observation === "payload" || e.observation === "dispatch"));
    assert.ok(events.some((e) => e.observation === "response"));
    assert.ok(events.some((e) => e.attemptId && String(e.attemptId).includes(":p1")));
    // No invented tool byte span when range known as lines
    const toolRead = events.find((e) => e.boundary === "tool_result");
    assert.equal(toolRead?.matchMethod, "runtime_line_range");
  });

  it("records cursor-cli provider gap health without inventing payload", async () => {
    const hooks = new Map<string, Function>();
    await observer({ on: (name: string, fn: Function) => hooks.set(name, fn) } as any);
    const cwd = mkdtempSync(join(tmpdir(), "isee-cursor-"));
    const ctx = { cwd, sessionManager: { getSessionFile: () => "cursor-session.jsonl" } };
    await hooks.get("session_start")!({}, ctx);
    await hooks.get("before_agent_start")!(
      { prompt: "hi", systemPromptOptions: { contextFiles: [], skills: [] } },
      ctx,
    );
    await hooks.get("message_end")!({
      message: { role: "assistant", content: [{ type: "text", text: "ok" }], api: "cursor-cli", provider: "cursor" },
    }, ctx);
    const events = readJsonl(join(cwd, ".iseeagents/cursor-session.jsonl"));
    assert.equal(events.filter((e) => e.observation === "payload" || e.observation === "dispatch").length, 0);
    const gap = events.find((e) => e.unsupportedBoundary === "before_provider_request");
    assert.ok(gap);
    assert.match(String(gap?.notes), /cursor-cli/i);
    const toolGap = events.find((e) => e.unsupportedBoundary === "tool_call|tool_result");
    assert.ok(toolGap);
  });

  it("uses a unique ephemeral session label when Pi has no session file", async () => {
    const hooks = new Map<string, Function>();
    await observer({ on: (name: string, fn: Function) => hooks.set(name, fn) } as any);
    const cwd = mkdtempSync(join(tmpdir(), "isee-ephemeral-"));
    const ctx = { cwd, sessionManager: { getSessionFile: () => undefined } };
    await hooks.get("session_start")!({}, ctx);
    await hooks.get("before_agent_start")!(
      { prompt: "ephemeral", systemPromptOptions: { contextFiles: [], skills: [] } },
      ctx,
    );
    const names = readdirSync(join(cwd, ".iseeagents"));
    assert.equal(names.length, 1);
    assert.match(names[0], /^ephemeral-\d+-\d+\.jsonl$/);
    assert.doesNotMatch(names[0], /unknown-session/);
  });

  it("ISEEAGENTS_PERSIST_RAW_TEXT=1 stores rawText on prompt", async () => {
    const prev = process.env.ISEEAGENTS_PERSIST_RAW_TEXT;
    process.env.ISEEAGENTS_PERSIST_RAW_TEXT = "1";
    try {
      const hooks = new Map<string, Function>();
      await observer({ on: (name: string, fn: Function) => hooks.set(name, fn) } as any);
      const cwd = mkdtempSync(join(tmpdir(), "isee-raw-"));
      const ctx = { cwd, sessionManager: { getSessionFile: () => "raw-session.jsonl" } };
      await hooks.get("session_start")!({}, ctx);
      await hooks.get("before_agent_start")!(
        { prompt: "VISIBLE_PROMPT_TEXT", systemPromptOptions: { contextFiles: [], skills: [] } },
        ctx,
      );
      const events = readJsonl(join(cwd, ".iseeagents/raw-session.jsonl"));
      const prompt = events.find((e) => e.boundary === "before_agent_start.prompt");
      assert.equal(prompt?.rawText, "VISIBLE_PROMPT_TEXT");
      assert.notEqual(prompt?.rawTextRedacted, true);
    } finally {
      if (prev === undefined) delete process.env.ISEEAGENTS_PERSIST_RAW_TEXT;
      else process.env.ISEEAGENTS_PERSIST_RAW_TEXT = prev;
    }
  });
});
