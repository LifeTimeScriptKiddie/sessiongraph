import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { join, resolve } from "node:path";
import { createGraphFixture } from "./create-graph-fixture.ts";
import { renderProvenanceHtml } from "../src/viewer/render.ts";

const root = resolve(".sessiongraph/demo");
mkdirSync(root, { recursive: true });
const run = mkdtempSync(join(root, "synthetic-"));
const events = createGraphFixture(join(run, "capture.jsonl"));
const html = renderProvenanceHtml(events, { label: "Synthetic SessionGraph demo", embedSources: false });
const output = join(root, "provenance.html");
writeFileSync(output, html);
console.log(`Synthetic demo: ${output}`);
