import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadScenario, replayScenario } from "../src/replay.ts";
import { readJsonl } from "../src/recorder.ts";
import { claudeStubCapability } from "../src/adapters/claude-stub.ts";
import { codexStubCapability } from "../src/adapters/codex-stub.ts";

const fixturesRoot = new URL("../fixtures/", import.meta.url).pathname;
const outRoot = mkdtempSync(join(tmpdir(), "iseeagents-"));

function run(id: string) {
  const scenario = loadScenario(join(fixturesRoot, id, "scenario.json"));
  const out = join(outRoot, `${id}.jsonl`);
  return { scenario, result: replayScenario(scenario, out), out };
}

describe("iseeagents acceptance scenarios", () => {
  it("01: records prompt, AGENTS.md, skill, partial read, tool result", () => {
    const { result } = run("scenario-01");
    const cats = new Set(result.events.map((e) => e.sourceCategory));
    assert.ok(cats.has("user_input"));
    assert.ok(cats.has("instructions"));
    assert.ok(cats.has("skill"));
    assert.ok(cats.has("tool_result"));
    assert.ok(result.events.some((e) => e.evidence === "read_result" && e.sourceRange));
    assert.ok(result.events.some((e) => e.observation === "usage" && e.usageInputTokens === 420));
  });

  it("02: extension runtime does not attribute source text without payload match", () => {
    const { result } = run("scenario-02");
    const ext = result.events.find((e) => e.sourceAlias === "iseeagents-observer");
    assert.ok(ext);
    assert.equal(ext?.contentVersionKey, null);
    assert.ok(ext?.ambiguity?.includes("no payload match"));
    assert.equal(
      result.events.filter((e) => e.sourceAlias === "iseeagents-observer" && e.evidence === "final_dispatch")
        .length,
      0,
    );
  });

  it("03: reread after change gets distinct content versions", () => {
    const { result } = run("scenario-03");
    const reads = result.events.filter((e) => e.observation === "read");
    assert.equal(reads.length, 2);
    assert.notEqual(reads[0].contentVersionKey, reads[1].contentVersionKey);
    assert.notEqual(reads[0].requestId, reads[1].requestId);
  });

  it("04: compaction creates summary lineage without requiring ancestor double-count", () => {
    const { result } = run("scenario-04");
    const summary = result.events.find((e) => e.evidence === "summary_ancestor");
    assert.ok(summary);
    assert.equal(summary?.sourceCategory, "summary");
    const r2Payload = result.events.find(
      (e) => e.requestId === "r2" && e.observation === "dispatch",
    );
    assert.ok(r2Payload);
    // Ancestors may be linked, but r2 dispatch is the summary payload era — estimates stay on their events.
    const simultaneousAncestorCharge = result.events.filter(
      (e) => e.requestId === "r2" && e.sourceCategory === "user_input" && e.evidence === "final_dispatch",
    );
    assert.equal(simultaneousAncestorCharge.length, 0);
  });

  it("05: provisional early observer vs final after later mutator", () => {
    const { result } = run("scenario-05");
    assert.ok(result.events.some((e) => e.boundary.includes("provisional")));
    assert.ok(result.events.some((e) => e.evidence === "final_dispatch"));
    assert.equal(result.payloadMutatedByObserver, false);
  });

  it("06: drop + retry keep partial coverage and distinct attempt IDs", () => {
    const { result } = run("scenario-06");
    assert.ok(result.events.some((e) => e.observation === "capture_health" && (e.droppedEvents ?? 0) >= 1));
    const attempts = new Set(result.events.map((e) => e.attemptId).filter(Boolean));
    assert.ok(attempts.has("r1:a1"));
    assert.ok(attempts.has("r1:a2"));
    const usage = result.events.find((e) => e.observation === "usage");
    assert.equal(usage?.usageInputTokens, null);
    assert.equal(usage?.coverage, "partial");
  });

  it("07: provider totals stay independent of source estimates", () => {
    const { result } = run("scenario-07");
    const usage = result.events.find((e) => e.observation === "usage");
    assert.equal(usage?.usageInputTokens, 999);
    const estimates = result.events
      .filter((e) => e.estimatedTokens != null)
      .map((e) => e.estimatedTokens as number);
    const sumEst = estimates.reduce((a, b) => a + b, 0);
    assert.notEqual(sumEst, usage?.usageInputTokens);
    // No clamping remainder to fabricated exact attribution on usage event.
    assert.equal(usage?.estimatedTokens, null);
  });

  it("08: observer does not mutate payload; secret-like fixture strings not persisted", () => {
    const { result } = run("scenario-08");
    assert.equal(result.payloadMutatedByObserver, false);
    assert.equal(result.secretLikePersisted, false);
    const blob = result.events.map((e) => JSON.stringify(e)).join("\n");
    assert.equal(/sk-SYNTHETICNOTAREALKEY000000/.test(blob), false);
    assert.equal(/api_key=supersecret/.test(blob), false);
    assert.equal(/BEGIN PRIVATE KEY/.test(blob), false);
    assert.ok(result.events.some((e) => e.notes?.includes("secret-like")));
  });
});

describe("adapter stubs", () => {
  it("claude and codex stubs declare unsupported boundaries", () => {
    assert.ok(claudeStubCapability.unsupportedBoundaries.length > 0);
    assert.ok(codexStubCapability.unsupportedBoundaries.length > 0);
    const { result } = run("scenario-01");
    void result;
    const out = join(outRoot, "stubs.jsonl");
    const scenario = {
      id: "stubs",
      title: "stubs",
      sessionId: "stub",
      steps: [
        { type: "claude_stub" as const, boundary: "PreCompact" },
        { type: "codex_stub" as const, boundary: "provider_payload" },
      ],
    };
    const r = replayScenario(scenario, out);
    assert.ok(r.events.every((e) => e.coverage === "unsupported"));
  });
});

describe("preview retained", () => {
  it("keeps synthetic HTML preview path", () => {
    const preview = new URL("../examples/context-trace.html", import.meta.url).pathname;
    assert.equal(existsSync(preview), true);
    assert.match(readFileSync(preview, "utf8"), /Synthetic example/);
  });
});

describe("jsonl append-only", () => {
  it("reads back written events in order", () => {
    const { out, result } = run("scenario-01");
    const again = readJsonl(out);
    assert.equal(again.length, result.events.length);
    assert.deepEqual(
      again.map((e) => e.producerSeq),
      result.events.map((e) => e.producerSeq),
    );
  });
});
