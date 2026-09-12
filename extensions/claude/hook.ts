/**
 * Opt-in Claude Code hook entry (NOT installed globally by Phase 2).
 * Invoked via extensions/claude/hook.sh
 *
 * Reads stdin JSON, appends metadata-only events under <cwd>/.iseeagents/.
 * Always exits 0 and prints nothing that would inject context.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { AppendOnlyJsonlRecorder } from "../../src/recorder.ts";
import {
  observeClaudeHook,
  CLAUDE_ADAPTER_ID,
  CLAUDE_ADAPTER_VERSION,
  type ClaudeHookInput,
} from "../../src/adapters/claude.ts";

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf8");
}

const raw = await readStdin();
if (!raw.trim()) process.exit(0);

let input: ClaudeHookInput;
try {
  input = JSON.parse(raw) as ClaudeHookInput;
} catch {
  process.exit(0);
}

const cwd = String(input.cwd ?? process.cwd());
const sessionId = String(input.session_id ?? "claude-session");
const dir = join(cwd, ".iseeagents");
mkdirSync(dir, { recursive: true });
const recorder = new AppendOnlyJsonlRecorder({
  path: join(dir, `${sessionId}.jsonl`),
  sessionId,
  adapterId: CLAUDE_ADAPTER_ID,
  adapterVersion: CLAUDE_ADAPTER_VERSION,
});

observeClaudeHook({ recorder, persistRawText: false }, input);
process.exit(0);
