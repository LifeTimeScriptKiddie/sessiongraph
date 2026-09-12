import { it } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync, linkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import vm from "node:vm";
import { createGraphFixture } from "../scripts/create-graph-fixture.ts";
import { renderProvenanceHtml, writeProvenanceHtml } from "../src/viewer/render.ts";

const events = createGraphFixture(join(mkdtempSync(join(tmpdir(), "isee-viewer-")), "fixture.jsonl"));
const html = renderProvenanceHtml(events, { label: "Synthetic interaction test" });

// Minimal DOM contract harness. This tests interactions, not browser layout/rendering.
class Element {
  tagName: string; children: Element[] = []; attrs = new Map(); handlers = new Map<string, Function[]>();
  _text = ""; className = ""; value = ""; name = ""; checked = false; hidden = false; type = ""; required = false; files: any[] = [];
  style: Record<string, string> = {}; dataset: Record<string, string> = {};
  constructor(tag: string) { this.tagName = tag; }
  set textContent(v: string) { this._text = String(v); this.children = []; }
  get textContent(): string { return this._text + this.children.map(c => c.textContent).join(""); }
  append(...children: Element[]) { this.children.push(...children); }
  replaceChildren(...children: Element[]) { this._text = ""; this.children = children; }
  setAttribute(k: string, v: string) { this.attrs.set(k, v); }
  getAttribute(k: string) { return this.attrs.get(k); }
  addEventListener(k: string, f: Function) { this.handlers.set(k, [...(this.handlers.get(k) || []), f]); }
  async dispatch(k: string, extra: Record<string, unknown> = {}) { for (const f of this.handlers.get(k) || []) await f({ target: this, preventDefault() {}, ...extra }); }
  click() { return this.dispatch("click"); }
  getBoundingClientRect() { return { left: 0, right: 200, top: 0, bottom: 100, width: 900, height: 500 }; }
}
function setup(inputHtml = html) {
  const elements = new Map<string, Element>(), created: Element[] = [];
  for (const match of inputHtml.matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"/g)) elements.set(match[2], new Element(match[1]));
  elements.get("capture-data")!.textContent = inputHtml.match(/<script type="application\/json" id="capture-data">([\s\S]*?)<\/script>/)![1];
  const get = (id: string) => { const e = elements.get(id); assert.ok(e, `Element ${id} exists`); return e; };
  const create = (tag: string) => { const e = new Element(tag); created.push(e); return e; };
  const handlers = new Map();
  const code = inputHtml.match(/<script>([\s\S]*?)<\/script>/)![1];
  vm.runInNewContext(code, {
    document: { getElementById: get, createElement: create, createElementNS: (_ns: string, tag: string) => create(tag), createTextNode: (text: string) => { const e = create("text"); e.textContent = text; return e; } },
    window: { innerWidth: 1200, addEventListener: (name: string, fn: Function) => handlers.set(name, fn) },
    requestAnimationFrame: (fn: Function) => fn(), setTimeout: (fn: Function) => fn(), URL, Blob,
    FormData: class { get(name: string) { return created.find(e => e.tagName === "input" && e.name === name && e.checked)?.value ?? null; } },
  });
  return { get, created };
}

it("shows attached SessionGraph structural metrics with an explicit interpretation limit", () => {
  const analysis = { graph: { nodes: events.map(event => ({ id: event.eventId })) }, findings: [] };
  const metrics = {
    schema_version: 1,
    engine: "networkx-test",
    metrics: {
      declared_nodes: events.length, edges: 14, weakly_connected_components: 5,
      max_depth: 3, cycle_nodes: 0, request_output_coverage: 1,
      artifact_verification_coverage: null, relation_counts: { response_to: 2 },
    },
    scope: "structural measurements only",
  };
  const measured = renderProvenanceHtml(events, { sessiongraph: analysis, sessiongraphMetrics: metrics, embedSources: false });
  const { get } = setup(measured);
  assert.match(get("detail-sections").textContent, /14 edges/);
  assert.match(get("detail-sections").textContent, /response_to 2/);
  assert.match(get("detail-sections").textContent, /do not establish correctness, attention, or semantic influence/);
});

it("activity tape is the default home view with split detail sections", async () => {
  const { get } = setup();
  assert.equal(get("mode-activity").getAttribute("aria-pressed"), "true");
  assert.equal(get("activity-view").hidden, false);
  assert.equal(get("provenance-view").hidden, true);
  assert.equal(get("page-extras").hidden, true);
  assert.match(get("load-status").textContent, /activity steps/);
  assert.match(get("activity-list").textContent, /User input|Assistant response|Load |Skill|Instructions|input|outcome/i);
  assert.match(get("detail-sections").textContent, /What|Where|Evidence|Usage|SessionGraph|Harness text/);
});

it("provenance mode still selects requests and exposes unknown output", async () => {
  const { get } = setup();
  await get("mode-provenance").click();
  assert.equal(get("provenance-view").hidden, false);
  assert.equal(get("page-extras").hidden, false);
  assert.match(get("request-summary").textContent, /recorded match edge/);
  assert.match(get("output-summary").textContent, /Response observed|Output not recorded/);
  const picker = get("request-picker");
  // First option is "All turns" in activity fill; after provenance mode refill, options are payload snapshots.
  assert.ok(picker.children.length >= 2);
  picker.value = picker.children[1].value; await picker.dispatch("change");
  assert.match(get("request-summary").textContent, /recorded match edge/);
});

it("local interpretation scoring distinguishes correct and wrong answers without reporting a user study", async () => {
  const { get, created } = setup();
  const choices: Record<string, string> = { unlinked: "1", boundary: "0", summary: "2", output: "1", influence: "2" };
  await get("study-form").dispatch("submit");
  assert.match(get("study-result").textContent, /Answer all/);
  for (const e of created.filter(e => e.tagName === "input")) e.checked = choices[e.name] === e.value;
  await get("study-form").dispatch("submit");
  assert.match(get("study-result").textContent, /5\/5 correct/);
  assert.equal(get("download-result").hidden, false);
  for (const e of created.filter(e => e.tagName === "input")) e.checked = String((Number(choices[e.name]) + 1) % 3) === e.value;
  await get("study-form").dispatch("submit");
  assert.match(get("study-result").textContent, /0\/5 correct/);
});

it("local capture load projects an activity tape and reports load failures", async () => {
  const { get } = setup();
  const file = get("capture-file");
  file.files = [{ name: "inventory.jsonl", size: 100, text: async () => JSON.stringify(events[0]) + "\n" }];
  await file.dispatch("change");
  assert.match(get("load-status").textContent, /Loaded 1 events/);
  assert.match(get("activity-list").textContent, /./);
  file.files = [{ name: "bad.jsonl", size: 10, text: async () => "invalid" }];
  await file.dispatch("change");
  assert.equal(get("error").hidden, false);
  assert.match(get("load-status").textContent, /Could not load/);
});

it("HTML export omits unknown/raw fields and escapes script-closing content", () => {
  const input = structuredClone(events);
  input[0].sourceAlias = "</script><script>malicious()</script>";
  input[0].notes = "RAW_SECRET_MARKER";
  (input[0] as any).rawPrompt = "RAW_SECRET_MARKER";
  (input[0] as any).sourceRange = { start: 0, end: 3, raw: "RAW_SECRET_MARKER" };
  const rendered = renderProvenanceHtml(input, { embedSources: false });
  assert.equal(rendered.includes("RAW_SECRET_MARKER"), false);
  assert.equal(rendered.includes("</script><script>malicious()"), false);
  assert.ok(rendered.includes("\\u003c/script>"));
  assert.match(rendered, /buildActivityTape|Activity tape/);
});

it("rendering refuses missing captures and output aliases that would overwrite the capture", () => {
  const dir = mkdtempSync(join(tmpdir(), "isee-source-preserve-"));
  const input = join(dir, "source.jsonl"), alias = join(dir, "alias.html");
  const body = events.map(e => JSON.stringify(e)).join("\n") + "\n";
  writeFileSync(input, body); linkSync(input, alias);
  assert.throws(() => writeProvenanceHtml(input, alias), /must not replace/);
  assert.equal(readFileSync(input, "utf8"), body);
  assert.throws(() => writeProvenanceHtml(join(dir, "absent.jsonl"), join(dir, "view.html")), /ENOENT/);
});
