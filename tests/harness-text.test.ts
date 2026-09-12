import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { embedHarnessSources, resolveHarnessPath } from "../src/viewer/embed-sources.ts";
import { renderProvenanceHtml } from "../src/viewer/render.ts";
import { SCHEMA_VERSION, type ContextEvent } from "../src/schema.ts";
import { AppendOnlyJsonlRecorder } from "../src/recorder.ts";
import { observeContextFile, observeSkill } from "../src/adapters/pi.ts";

function baseEvent(partial: Partial<ContextEvent> & Pick<ContextEvent, "observation" | "boundary" | "evidence" | "coverage">): ContextEvent {
  return {
    schemaVersion: SCHEMA_VERSION,
    eventId: partial.eventId ?? "e1",
    sessionId: "s",
    agentId: "agent-main",
    parentAgentId: null,
    requestId: "r1",
    attemptId: "r1:a1",
    toolCallId: null,
    producerSeq: partial.producerSeq ?? 1,
    monotonicMs: null,
    wallTime: "2026-09-11T12:00:00.000Z",
    parentEventIds: [],
    sourceCategory: partial.sourceCategory ?? null,
    sourceAlias: partial.sourceAlias ?? null,
    sourcePath: partial.sourcePath ?? null,
    sourceKey: null,
    contentVersionKey: null,
    sourceRange: null,
    encoding: null,
    observation: partial.observation,
    evidence: partial.evidence,
    adapterId: "pi",
    adapterVersion: "test",
    boundary: partial.boundary,
    handlerOrdinal: 0,
    coverage: partial.coverage,
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
    notes: partial.notes ?? null,
    rawTextRedacted: partial.rawTextRedacted ?? true,
    rawText: partial.rawText,
  };
}

describe("harness text embed", () => {
  it("does not read local files or retain raw text and absolute paths by default", () => {
    const dir = mkdtempSync(join(tmpdir(), "isee-private-export-"));
    const path = join(dir, "AGENTS.md");
    writeFileSync(path, "SYNTHETIC_DISK_CONTENT_DO_NOT_EXPORT");
    const event = baseEvent({
      observation: "load", boundary: "test", evidence: "runtime_loaded", coverage: "full",
      sourceCategory: "instructions", sourcePath: path, sourceAlias: path,
      rawText: "SYNTHETIC_RECORDED_CONTENT_DO_NOT_EXPORT", rawTextRedacted: null,
    });
    const html = renderProvenanceHtml([event]);
    assert.doesNotMatch(html, /SYNTHETIC_DISK_CONTENT_DO_NOT_EXPORT|SYNTHETIC_RECORDED_CONTENT_DO_NOT_EXPORT/);
    assert.equal(html.includes(path), false);
    assert.match(html, /"sourceAlias":"AGENTS.md"/);
    assert.match(html, /"rawTextRedacted":true/);
    assert.match(html, /"byEventId":\{\},"byPath":\{\}/);
    const withText = renderProvenanceHtml([event], { embedSources: true });
    assert.match(withText, /SYNTHETIC_RECORDED_CONTENT_DO_NOT_EXPORT/);
  });

  it("embeds instruction file contents by path for click-through", () => {
    const dir = mkdtempSync(join(tmpdir(), "isee-embed-"));
    const path = join(dir, "AGENTS.md");
    writeFileSync(path, "# Hello harness\nDo the thing.\n");
    const events = [
      baseEvent({
        observation: "load",
        boundary: "before_agent_start.contextFiles",
        evidence: "runtime_loaded",
        coverage: "full",
        sourceCategory: "instructions",
        sourceAlias: path,
        sourcePath: path,
        eventId: "inst-1",
      }),
    ];
    const embedded = embedHarnessSources(events, { skillSearchRoots: [] });
    assert.equal(embedded.byEventId["inst-1"]?.text.includes("Hello harness"), true);
    assert.equal(embedded.byPath[path]?.text.includes("Do the thing"), true);

    const html = renderProvenanceHtml(events, { label: "embed-test", embedSources: true });
    assert.match(html, /Hello harness/);
    assert.match(html, /"sources"/);
    assert.match(html, /Harness text|resolveStepText|Embedded at HTML build/);
  });

  it("resolves skill name to SKILL.md under search roots", () => {
    const root = mkdtempSync(join(tmpdir(), "isee-skills-"));
    const skillDir = join(root, "telegram-bridge");
    mkdirSync(skillDir);
    const skillPath = join(skillDir, "SKILL.md");
    writeFileSync(skillPath, "---\nname: telegram-bridge\n---\nOperate the bridge.\n");
    const event = baseEvent({
      observation: "load",
      boundary: "before_agent_start.skills",
      evidence: "runtime_loaded",
      coverage: "partial",
      sourceCategory: "skill",
      sourceAlias: "telegram-bridge",
      eventId: "sk-1",
    });
    assert.equal(resolveHarnessPath(event, [root]), skillPath);
    const embedded = embedHarnessSources([event], { skillSearchRoots: [root] });
    assert.match(embedded.byEventId["sk-1"].text, /Operate the bridge/);
  });

  it("observeSkill stores sourcePath; harness persist stores body", () => {
    const dir = mkdtempSync(join(tmpdir(), "isee-skill-cap-"));
    const jsonl = join(dir, "cap.jsonl");
    const recorder = new AppendOnlyJsonlRecorder({ path: jsonl, sessionId: "s", adapterId: "pi" });
    const ev = observeSkill(
      { recorder, requestId: "r1", persistHarnessText: true },
      { name: "demo", filePath: "/tmp/demo/SKILL.md", content: "skill body here" },
    );
    assert.equal(ev.sourcePath, "/tmp/demo/SKILL.md");
    assert.equal(ev.rawText, "skill body here");
    assert.notEqual(ev.rawTextRedacted, true);

    const fileEv = observeContextFile(
      { recorder, requestId: "r1", persistHarnessText: true },
      { path: "/tmp/AGENTS.md", content: "agents body" },
    );
    assert.equal(fileEv.sourcePath, "/tmp/AGENTS.md");
    assert.equal(fileEv.rawText, "agents body");
  });
});
