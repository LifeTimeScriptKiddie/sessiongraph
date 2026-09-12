import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createGraphFixture } from "./create-graph-fixture.ts";
import { exportJsonlForSessionGraph } from "../src/sessiongraph/export.ts";
import { renderProvenanceHtml } from "../src/viewer/render.ts";

const root = fileURLToPath(new URL("..", import.meta.url));
const temp = mkdtempSync(join(tmpdir(), "iseeagents-sessiongraph-"));
const capture = join(temp, "capture.jsonl");
const exported = join(temp, "sessiongraph.jsonl");
const report = join(temp, "report");
const metricsPath = join(temp, "graph-metrics.json");

function uv(args: string[]): void {
  const run = spawnSync("uv", ["--directory", join(root, "packages/sessiongraph"), "run", "--extra", "graph", "--frozen", ...args], {
    cwd: root,
    encoding: "utf8",
  });
  assert.equal(run.status, 0, `uv ${args.join(" ")} failed\n${run.stdout}\n${run.stderr}`);
}

const events = createGraphFixture(capture);
const result = exportJsonlForSessionGraph(capture, exported);
assert.equal(result.count, events.length);

uv(["sessiongraph", "analyze", exported, "--out", report]);
uv(["sessiongraph", "graph-metrics", join(report, "analysis.json"), "--out", metricsPath]);

const analysis = JSON.parse(readFileSync(join(report, "analysis.json"), "utf8"));
const metrics = JSON.parse(readFileSync(metricsPath, "utf8"));
assert.equal(analysis.events.length, events.length);
assert.equal(metrics.metrics.declared_nodes, events.length);
assert.ok(metrics.metrics.edges > 0);
assert.ok(metrics.metrics.relation_counts.response_to >= 1);
assert.ok(metrics.metrics.relation_counts.summary_ancestor >= 1);
assert.ok(metrics.metrics.relation_counts.match_source >= 1);
assert.ok(metrics.metrics.request_roots >= 1);
assert.ok(metrics.metrics.outputs >= 1);
assert.equal(metrics.metrics.request_output_coverage, 1);

const html = renderProvenanceHtml(events, { sessiongraph: analysis, sessiongraphMetrics: metrics, embedSources: false });
assert.match(html, /NetworkX structural metrics|networkx-/i);
assert.match(html, /response_to/);
console.log(`Cross-language contract passed: ${events.length} events, ${metrics.metrics.edges} edges`);
