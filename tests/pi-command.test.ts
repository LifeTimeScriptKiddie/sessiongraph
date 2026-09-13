import { it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import extension from "../packages/sessiongraph/pi-extension/sessiongraph.ts";
import { createGraphFixture } from "../scripts/create-graph-fixture.ts";

function harness(saved = true) {
  const cwd = mkdtempSync(join(tmpdir(), "sessiongraph-command-"));
  const sessionFile = join(cwd, "synthetic.jsonl");
  if (saved) writeFileSync(sessionFile, "{}\n");
  const notices: string[] = [];
  let handler: any;
  extension({ registerCommand(name: string, command: any) { assert.equal(name, "sessiongraph"); handler = command.handler; } } as any);
  const ctx = { cwd, hasUI: true, waitForIdle: async () => {}, sessionManager: { getSessionFile: () => saved ? sessionFile : undefined }, ui: { notify: (message: string) => notices.push(message), select: async () => "Help" } };
  return { cwd, notices, ctx, run: (args: string) => handler(args, ctx) };
}
it("Pi command presents a menu and supports help without a saved session", async () => {
  const h = harness(false); await h.run(""); assert.match(h.notices[0], /\/sessiongraph open/);
});
it("Pi command explains missing sessions and refuses unknown actions", async () => {
  const h = harness(false); await h.run("view"); assert.match(h.notices[0], /not saved yet/);
  await h.run("anything"); assert.match(h.notices[1], /Unknown action/);
});
it("Pi command does not substitute another session's capture", async () => {
  const h = harness(); createGraphFixture(join(h.cwd, ".iseeagents", "other.jsonl"));
  await h.run("view"); assert.match(h.notices[0], /No recorded context/);
  assert.equal(existsSync(join(h.cwd, ".sessiongraph", "synthetic", "provenance.html")), false);
});
it("Pi command builds current-session HTML without Python or raw source text", async () => {
  const h = harness(); const capture = join(h.cwd, ".iseeagents", "synthetic.jsonl");
  const events = createGraphFixture(capture);
  events[0].rawText = "PRIVATE_TEST_MARKER_123";
  writeFileSync(capture, events.map(e => JSON.stringify(e)).join("\n") + "\n");
  await h.run("view");
  const html = readFileSync(join(h.cwd, ".sessiongraph", "synthetic", "provenance.html"), "utf8");
  assert.match(h.notices[0], /Graph ready/); assert.ok(!html.includes("PRIVATE_TEST_MARKER_123"));
});
it("Pi manifest exposes both recorder and command entry points", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.deepEqual(pkg.pi.extensions, ["./dist/extensions/pi/iseeagents-observer.js", "./dist/packages/sessiongraph/pi-extension/sessiongraph.js"]);
});
it("Pi status does not mistake a reserved session path for a saved session", async () => {
  const h = harness(false);
  h.ctx.sessionManager.getSessionFile = () => join(h.cwd, "reserved-but-unsaved.jsonl");
  await h.run("status");
  assert.match(h.notices[0], /Current session: not saved yet/);
});
