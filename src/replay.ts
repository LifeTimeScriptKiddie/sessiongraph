import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { AppendOnlyJsonlRecorder, deepFreeze, readJsonl, stableStringify } from "./recorder.ts";
import {
  observeCompactionSummary,
  observeContextFile,
  observeExtensionRuntimeOnly,
  observeProviderPayload,
  observeSkill,
  observeToolResult,
  observeUsage,
  observeUserPrompt,
} from "./adapters/pi.ts";
import { createClaudeStubObservation } from "./adapters/claude-stub.ts";
import { createCodexStubObservation } from "./adapters/codex-stub.ts";
import { contentVersionKey, hmacKeyFromEnv } from "./ids.ts";
import type { ContextEvent } from "./schema.ts";

export type FixtureScenario = {
  id: string;
  title: string;
  sessionId: string;
  steps: FixtureStep[];
};

export type FixtureStep =
  | { type: "user_prompt"; requestId: string; attemptId?: string; prompt: string }
  | { type: "context_file"; requestId: string; attemptId?: string; path: string; content: string }
  | { type: "skill"; requestId: string; attemptId?: string; name: string; content: string }
  | {
      type: "tool_result";
      requestId: string;
      attemptId?: string;
      toolCallId: string;
      toolName: string;
      content: string;
      range?: { start: number; end: number };
    }
  | {
      type: "provider_payload";
      requestId: string;
      attemptId?: string;
      payload: unknown;
      provisional?: boolean;
      final?: boolean;
      mutatingExtensionAfter?: boolean;
    }
  | {
      type: "usage";
      requestId: string;
      attemptId?: string;
      input: number | null;
      output: number | null;
      cached: number | null;
    }
  | {
      type: "compaction";
      requestId: string;
      attemptId?: string;
      text: string;
      ancestorEventIds?: string[];
    }
  | { type: "extension_runtime"; requestId: string; attemptId?: string; name: string }
  | { type: "drop"; count?: number; boundary?: string }
  | { type: "retry_attempt"; requestId: string; attemptId: string }
  | { type: "claude_stub"; boundary: string }
  | { type: "codex_stub"; boundary: string }
  | { type: "file_change"; path: string; content: string };

export type ReplayResult = {
  events: ContextEvent[];
  payloadSnapshots: string[];
  payloadMutatedByObserver: boolean;
  secretLikePersisted: boolean;
};

export function replayScenario(
  scenario: FixtureScenario,
  outPath: string,
  hmacKey = hmacKeyFromEnv({ ISEEAGENTS_HMAC_KEY: "fixture-test-key" }),
): ReplayResult {
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, "", "utf8");
  const recorder = new AppendOnlyJsonlRecorder({
    path: outPath,
    sessionId: scenario.sessionId,
    adapterId: "replay",
    adapterVersion: "0.1.0",
  });

  const payloadSnapshots: string[] = [];
  let payloadMutatedByObserver = false;
  const fileVersions = new Map<string, string>();
  const ancestorIds: string[] = [];

  for (const step of scenario.steps) {
    const base = {
      recorder,
      requestId: "requestId" in step ? step.requestId : "r0",
      attemptId: "attemptId" in step ? step.attemptId ?? null : null,
      hmacKey,
      persistRawText: false,
    };

    switch (step.type) {
      case "user_prompt":
        observeUserPrompt(base, step.prompt);
        break;
      case "context_file":
        fileVersions.set(step.path, contentVersionKey(step.content, hmacKey));
        observeContextFile(base, step);
        break;
      case "skill":
        observeSkill(base, step);
        break;
      case "tool_result":
        observeToolResult(base, step);
        break;
      case "provider_payload": {
        const frozen = deepFreeze(structuredClone(step.payload));
        const before = stableStringify(frozen);
        const ret = observeProviderPayload(
          { ...base, provisional: step.provisional, final: step.final },
          frozen,
        );
        const after = stableStringify(frozen);
        if (ret !== undefined || before !== after) payloadMutatedByObserver = true;
        payloadSnapshots.push(before);
        if (step.mutatingExtensionAfter) {
          // Simulated later mutator — not our observer. Record provisional vs final separately.
          observeProviderPayload(
            { ...base, provisional: false, final: true, handlerOrdinal: 99 },
            { ...(frozen as object), __mutated_by_later_extension: true },
          );
        }
        break;
      }
      case "usage":
        observeUsage(base, step);
        break;
      case "compaction": {
        observeCompactionSummary(base, {
          text: step.text,
          ancestorEventIds: step.ancestorEventIds ?? ancestorIds.slice(-8),
        });
        break;
      }
      case "extension_runtime":
        observeExtensionRuntimeOnly(base, step.name);
        break;
      case "drop":
        recorder.markDropped(step.count ?? 1, step.boundary ?? "synthetic_drop");
        break;
      case "retry_attempt":
        recorder.record({
          requestId: step.requestId,
          attemptId: step.attemptId,
          observation: "capture_health",
          evidence: "unknown",
          boundary: "retry",
          coverage: "partial",
          notes: "Distinct attempt ID for retry",
        });
        break;
      case "claude_stub":
        recorder.record(createClaudeStubObservation(step.boundary));
        break;
      case "codex_stub":
        recorder.record(createCodexStubObservation(step.boundary));
        break;
      case "file_change":
        fileVersions.set(step.path, contentVersionKey(step.content, hmacKey));
        break;
      default:
        throw new Error(`unknown step ${(step as { type: string }).type}`);
    }

    if (step.type !== "file_change") {
      const events = readJsonl(outPath);
      const last = events[events.length - 1];
      if (last) ancestorIds.push(last.eventId);
    }
  }

  const events = readJsonl(outPath);
  const secretLikePersisted = events.some((e) => {
    const blob = JSON.stringify(e);
    return /sk-SYNTHETICNOTAREALKEY000000|BEGIN PRIVATE KEY|api_key=supersecret/.test(blob);
  });

  return { events, payloadSnapshots, payloadMutatedByObserver, secretLikePersisted };
}

export function loadScenario(path: string): FixtureScenario {
  return JSON.parse(readFileSync(path, "utf8")) as FixtureScenario;
}

export function defaultFixtureDir(root = new URL("../fixtures/", import.meta.url).pathname) {
  return root;
}

export function scenarioPath(id: string, root?: string): string {
  return join(root ?? defaultFixtureDir(), id, "scenario.json");
}
