import { existsSync } from "node:fs";
import { basename, resolve } from "node:path";
import { AppendOnlyJsonlRecorder } from "./recorder.ts";
import { CODEX_ADAPTER_ID, CODEX_ADAPTER_VERSION, ingestCodexRollout } from "./adapters/codex.ts";

const args = process.argv.slice(2);
const input = args.shift();
let output: string | undefined;
while (args.length) {
  const flag = args.shift(), value = args.shift();
  if (flag !== "--out" || !value) throw new Error("usage: npm run ingest:codex -- ROLLOUT.jsonl --out CAPTURE.jsonl");
  output = value;
}
if (!input || !output) throw new Error("usage: npm run ingest:codex -- ROLLOUT.jsonl --out CAPTURE.jsonl");
if (resolve(input) === resolve(output)) throw new Error("Output must not replace the source rollout");
if (existsSync(output)) throw new Error("Output already exists; capture ingestion is append-only");

const sessionId = basename(input).replace(/^rollout-/, "").replace(/\.jsonl$/, "") || "codex-rollout";
const recorder = new AppendOnlyJsonlRecorder({
  path: output,
  sessionId,
  adapterId: CODEX_ADAPTER_ID,
  adapterVersion: CODEX_ADAPTER_VERSION,
});
const result = await ingestCodexRollout({ recorder, persistRawText: false }, input);
console.log(JSON.stringify({ ...result, output: resolve(output), rawTextPersisted: false }));
