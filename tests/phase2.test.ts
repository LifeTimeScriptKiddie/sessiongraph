import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadScenario, replayScenario } from "../src/replay.ts";
import { readJsonl, AppendOnlyJsonlRecorder, deepFreeze, stableStringify } from "../src/recorder.ts";
import { DerivedSqliteIndex, rebuildDerivedIndex } from "../src/index/sqlite.ts";
import {
  exportJsonlForSessionGraph,
  joinSessionGraphAnalysis,
  SEAM_VERSION,
} from "../src/sessiongraph/export.ts";
import {
  observeClaudeHook,
  claudeCapability,
  createClaudeStubObservation,
} from "../src/adapters/claude.ts";
import {
  observeCodexRolloutLine,
  codexCapability,
  createCodexStubObservation,
} from "../src/adapters/codex.ts";
import { observeProviderPayload } from "../src/adapters/pi.ts";

const fixturesRoot = new URL("../fixtures/", import.meta.url).pathname;
const outRoot = mkdtempSync(join(tmpdir(), "iseeagents-p2-"));

function replayFixture(id: string) {
  const scenario = loadScenario(join(fixturesRoot, id, "scenario.json"));
  const out = join(outRoot, `${id}.jsonl`);
  return { scenario, result: replayScenario(scenario, out), out };
}

describe("phase2 sqlite derived index", () => {
  it("rebuilds from JSONL and queries by session/request/source-version", () => {
    const { out, result, scenario } = replayFixture("scenario-01");
    const dbPath = join(outRoot, "scenario-01.sqlite");
    const stats = rebuildDerivedIndex(out, dbPath);
    assert.equal(stats.eventCount, result.events.length);
    assert.equal(stats.schemaVersion, "iseeagents.context.v1");

    const index = new DerivedSqliteIndex(dbPath);
    try {
      assert.equal(index.meta("source_of_truth"), "jsonl");
      assert.equal(index.count(), result.events.length);
      const bySession = index.query({ sessionId: scenario.sessionId });
      assert.equal(bySession.length, result.events.length);
      const req = result.events.find((e) => e.requestId)?.requestId;
      assert.ok(req);
      const byReq = index.query({ sessionId: scenario.sessionId, requestId: req });
      assert.ok(byReq.length >= 1);
      const withVersion = result.events.find((e) => e.contentVersionKey);
      if (withVersion?.sourceKey && withVersion.contentVersionKey) {
        const hit = index.query({
          sourceKey: withVersion.sourceKey,
          contentVersionKey: withVersion.contentVersionKey,
        });
        assert.ok(hit.some((e) => e.eventId === withVersion.eventId));
      }
    } finally {
      index.close();
    }
  });

  it("rebuild is idempotent for the same JSONL", () => {
    const { out } = replayFixture("scenario-03");
    const dbPath = join(outRoot, "idempotent.sqlite");
    rebuildDerivedIndex(out, dbPath);
    const a = new DerivedSqliteIndex(dbPath);
    const fp1 = a.fingerprint();
    a.close();
    rebuildDerivedIndex(out, dbPath);
    const b = new DerivedSqliteIndex(dbPath);
    const fp2 = b.fingerprint();
    b.close();
    assert.equal(fp1, fp2);
  });
});

describe("phase2 sessiongraph seam", () => {
  it("exports content-free generic JSONL with join metadata", () => {
    const { out, result } = replayFixture("scenario-01");
    const exportPath = join(outRoot, "sg-export.jsonl");
    const exported = exportJsonlForSessionGraph(out, exportPath);
    assert.equal(exported.count, result.events.length);
    const lines = readFileSync(exportPath, "utf8").trim().split("\n");
    const first = JSON.parse(lines[0]) as {
      content: string;
      iseeagents: { seamVersion: string; sessionId: string };
      id: string;
      parent_relations: Record<string, string>;
    };
    assert.equal(first.content, "");
    assert.equal(first.iseeagents.seamVersion, SEAM_VERSION);
    assert.equal(first.id, result.events[0].eventId);
    assert.deepEqual(first.parent_relations, {});

    const rows = lines.map(line => JSON.parse(line)) as Array<{
      kind: string;
      parent_ids: string[];
      parent_relations: Record<string, string>;
    }>;
    assert.ok(rows.every(row => Object.keys(row.parent_relations).every(id => row.parent_ids.includes(id))));

    const analysis = {
      graph: {
        nodes: result.events.slice(0, 3).map((e) => ({
          id: e.eventId,
          kind: `iseeagents_${e.observation}`,
        })),
      },
    };
    const hits = joinSessionGraphAnalysis(analysis, result.events);
    assert.equal(hits.length, 3);
    assert.equal(hits[0].sessionId, result.events[0].sessionId);
  });
});

describe("phase2 claude adapter honesty", () => {
  it("maps verified hooks and keeps provider_payload unsupported", () => {
    assert.ok(claudeCapability.supportedBoundaries.includes("UserPromptSubmit"));
    assert.ok(claudeCapability.unsupportedBoundaries.includes("provider_payload"));

    const path = join(outRoot, "claude.jsonl");
    const recorder = new AppendOnlyJsonlRecorder({
      path,
      sessionId: "claude-test",
      adapterId: "claude-code",
    });
    observeClaudeHook(
      { recorder, persistRawText: false },
      {
        hook_event_name: "UserPromptSubmit",
        session_id: "claude-test",
        prompt: "hello from fixture",
        cwd: outRoot,
      },
    );
    observeClaudeHook(
      { recorder, persistRawText: false },
      {
        hook_event_name: "PostToolUse",
        session_id: "claude-test",
        tool_name: "Read",
        tool_response: "file bytes",
      },
    );
    observeClaudeHook(
      { recorder, persistRawText: false },
      { hook_event_name: "provider_payload", session_id: "claude-test" },
    );
    const events = readJsonl(path);
    assert.ok(events.some((e) => e.boundary === "UserPromptSubmit" && e.coverage === "partial"));
    assert.ok(events.some((e) => e.boundary === "PostToolUse" && e.evidence === "read_result"));
    assert.ok(
      events.some(
        (e) => e.boundary === "provider_payload" && e.coverage === "unsupported",
      ),
    );
    assert.equal(events.every((e) => e.rawTextRedacted === true || e.observation === "capture_health"), true);
  });

  it("stub helper still marks unsupported boundaries", () => {
    const obs = createClaudeStubObservation("provider_payload");
    assert.equal(obs.coverage, "unsupported");
  });
});

describe("phase2 codex adapter honesty", () => {
  it("ingests rollout lines for meta/user/usage and refuses provider_payload claims", () => {
    assert.ok(codexCapability.supportedBoundaries.includes("transcript.token_count"));
    assert.ok(codexCapability.unsupportedBoundaries.includes("provider_payload"));

    const path = join(outRoot, "codex.jsonl");
    const recorder = new AppendOnlyJsonlRecorder({
      path,
      sessionId: "codex-test",
      adapterId: "codex",
    });
    const ctx = { sessionId: "codex-test", turn: 1 };
    assert.equal(
      observeCodexRolloutLine(
        { recorder },
        {
          type: "session_meta",
          payload: { session_id: "codex-test", cli_version: "0.153.4" },
        },
        ctx,
      ),
      true,
    );
    assert.equal(
      observeCodexRolloutLine(
        { recorder },
        {
          type: "response_item",
          payload: {
            role: "user",
            content: [{ type: "input_text", text: "codex user turn" }],
          },
        },
        ctx,
      ),
      true,
    );
    assert.equal(
      observeCodexRolloutLine(
        { recorder },
        {
          type: "response_item",
          payload: {
            type: "message",
            role: "assistant",
            phase: "final_answer",
            id: "assistant-message-1",
            content: [{ type: "output_text", text: "codex response" }],
          },
        },
        ctx,
      ),
      true,
    );
    assert.equal(
      observeCodexRolloutLine(
        { recorder },
        {
          type: "event_msg",
          payload: {
            type: "token_count",
            info: {
              total_token_usage: {
                input_tokens: 100,
                output_tokens: 20,
                cached_input_tokens: 40,
              },
            },
          },
        },
        ctx,
      ),
      true,
    );
    const stub = createCodexStubObservation("provider_payload");
    recorder.record(stub);
    const events = readJsonl(path);
    assert.ok(events.some((e) => e.boundary === "transcript.session_meta"));
    assert.ok(events.some((e) => e.boundary === "transcript.user_message"));
    const user = events.find((e) => e.boundary === "transcript.user_message");
    const response = events.find((e) => e.boundary === "transcript.assistant_message");
    assert.ok(user && response);
    assert.equal(response.observation, "response");
    assert.deepEqual(response.parentEventIds, [user.eventId]);
    assert.equal(response.rawText, undefined);
    assert.ok(
      events.some(
        (e) => e.boundary === "transcript.token_count" && e.usageInputTokens === 100,
      ),
    );
    assert.ok(events.some((e) => e.coverage === "unsupported"));
  });
});

describe("phase2 pi non-mutation regression", () => {
  it("observer still returns undefined and does not mutate payload", () => {
    const path = join(outRoot, "pi-mut.jsonl");
    const recorder = new AppendOnlyJsonlRecorder({
      path,
      sessionId: "pi-mut",
    });
    const payload = deepFreeze({ messages: [{ role: "user", content: "x" }] });
    const before = stableStringify(payload);
    const ret = observeProviderPayload(
      { recorder, requestId: "r1", persistRawText: false },
      payload,
    );
    assert.equal(ret, undefined);
    assert.equal(stableStringify(payload), before);
  });
});

describe("phase2 preview polish markers", () => {
  it("HTML preview documents coverage discrepancy semantics", () => {
    const preview = new URL("../examples/context-trace.html", import.meta.url).pathname;
    assert.equal(existsSync(preview), true);
    const html = readFileSync(preview, "utf8");
    assert.match(html, /Synthetic example/);
    assert.match(html, /coverage/i);
    assert.match(html, /discrepancy|unattributed|Provider totals/i);
  });
});
