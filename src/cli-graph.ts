import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { writeProvenanceHtml } from "./viewer/render.ts";

const args = process.argv.slice(2);
const input = args.shift();
const opts: Record<string, string> = {};
let includeSourceText = false;
while (args.length) {
  const flag = args.shift()!;
  if (flag === "--include-source-text") { includeSourceText = true; continue; }
  const value = args.shift();
  if (!["--out", "--label", "--analysis", "--metrics"].includes(flag) || value == null || value.startsWith("--"))
    throw new Error("Expected --out FILE [--label TEXT] [--analysis analysis.json] [--metrics graph-metrics.json] [--include-source-text]");
  opts[flag] = value;
}
if (!input || !opts["--out"]) throw new Error("usage: npm run graph -- CAPTURE.jsonl --out VIEW.html [--analysis analysis.json] [--metrics graph-metrics.json] [--label TEXT]");
if (opts["--metrics"] && !opts["--analysis"]) throw new Error("--metrics requires --analysis so measurements retain their graph context");
if (resolve(input) === resolve(opts["--out"])) throw new Error("Output must not replace the source capture");
writeProvenanceHtml(input, opts["--out"], {
  embedSources: includeSourceText,
  label: opts["--label"],
  sessiongraph: opts["--analysis"] ? JSON.parse(readFileSync(opts["--analysis"], "utf8")) : undefined,
  sessiongraphMetrics: opts["--metrics"] ? JSON.parse(readFileSync(opts["--metrics"], "utf8")) : undefined,
});
console.log(`Wrote ${resolve(opts["--out"])}`);
