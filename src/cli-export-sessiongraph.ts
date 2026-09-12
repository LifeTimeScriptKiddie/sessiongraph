import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { exportJsonlForSessionGraph } from "./sessiongraph/export.ts";

const args = process.argv.slice(2);
const input = args.shift();
let output: string | undefined;
while (args.length) {
  const flag = args.shift(), value = args.shift();
  if (flag !== "--out" || !value) throw new Error("usage: npm run export:sessiongraph -- CAPTURE.jsonl --out SESSIONGRAPH.jsonl");
  output = value;
}
if (!input || !output) throw new Error("usage: npm run export:sessiongraph -- CAPTURE.jsonl --out SESSIONGRAPH.jsonl");
if (resolve(input) === resolve(output)) throw new Error("Output must not replace the source capture");
if (existsSync(output)) throw new Error("Output already exists; choose a fresh export path");

const result = exportJsonlForSessionGraph(input, output);
console.log(JSON.stringify({ ...result, output: resolve(output), contentIncluded: false }));
