/**
 * Resolve harness input texts (instructions / skills) for HTML embed.
 * Browser file:// pages cannot read arbitrary local paths — embed at build time.
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join } from "node:path";
import type { ContextEvent } from "../schema.ts";

const MAX_BYTES = 256_000;
const MAX_FILES = 40;

export type EmbeddedSources = {
  byEventId: Record<string, { path: string; text: string; truncated: boolean; bytes: number }>;
  byPath: Record<string, { text: string; truncated: boolean; bytes: number }>;
  missed: Array<{ eventId: string; path: string | null; reason: string }>;
};

function looksLikePath(value: string | null | undefined): value is string {
  if (!value) return false;
  return value.startsWith("/") || /^[A-Za-z]:[\\/]/.test(value) || value.includes("/") || value.includes("\\");
}

function parseSourcePathFromNotes(notes: string | null | undefined): string | null {
  if (!notes) return null;
  const m = notes.match(/(?:^|\n)sourcePath=([^\n]+)/);
  return m?.[1]?.trim() || null;
}

/** Prefer explicit sourcePath; then absolute sourceAlias; then skill-name guesses. */
export function resolveHarnessPath(event: ContextEvent, skillSearchRoots: string[] = defaultSkillRoots()): string | null {
  const explicit = (event as ContextEvent & { sourcePath?: string | null }).sourcePath
    ?? parseSourcePathFromNotes(event.notes);
  if (explicit && looksLikePath(explicit)) return explicit;

  if (event.sourceCategory === "instructions" || event.sourceCategory === "file_input") {
    if (looksLikePath(event.sourceAlias)) return event.sourceAlias;
  }

  if (event.sourceCategory === "skill" && event.sourceAlias) {
    const name = event.sourceAlias;
    if (looksLikePath(name) && name.endsWith(".md")) return name;
    for (const root of skillSearchRoots) {
      const candidate = join(root, name, "SKILL.md");
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
}

export function defaultSkillRoots(): string[] {
  const home = homedir();
  return [
    join(home, ".pi/agent/skills"),
    join(home, ".claude/skills"),
  ];
}

function readCapped(path: string): { text: string; truncated: boolean; bytes: number } | null {
  try {
    if (!existsSync(path) || !statSync(path).isFile()) return null;
    const buf = readFileSync(path);
    const truncated = buf.length > MAX_BYTES;
    const slice = truncated ? buf.subarray(0, MAX_BYTES) : buf;
    return { text: slice.toString("utf8"), truncated, bytes: buf.length };
  } catch {
    return null;
  }
}

/**
 * Build an embed map for harness inputs. Dedupes by path. Skips user_input / secrets.
 */
export function embedHarnessSources(
  events: ContextEvent[],
  opts: { skillSearchRoots?: string[]; maxFiles?: number } = {},
): EmbeddedSources {
  const byEventId: EmbeddedSources["byEventId"] = {};
  const byPath: EmbeddedSources["byPath"] = {};
  const missed: EmbeddedSources["missed"] = [];
  const roots = opts.skillSearchRoots ?? defaultSkillRoots();
  const maxFiles = opts.maxFiles ?? MAX_FILES;
  let filesUsed = 0;

  for (const event of events) {
    if (event.observation !== "load" && event.observation !== "inventory") continue;
    if (event.sourceCategory === "user_input") continue; // never auto-embed prompts
    if (!["instructions", "skill", "file_input", "system_input"].includes(String(event.sourceCategory))) continue;

    if (typeof event.rawText === "string" && event.rawText.length) {
      const path = resolveHarnessPath(event, roots) ?? event.sourceAlias ?? event.eventId;
      byEventId[event.eventId] = {
        path: String(path),
        text: event.rawText.length > MAX_BYTES ? `${event.rawText.slice(0, MAX_BYTES)}\n… truncated …` : event.rawText,
        truncated: event.rawText.length > MAX_BYTES,
        bytes: Buffer.byteLength(event.rawText, "utf8"),
      };
      continue;
    }

    if (event.sourceCategory === "system_input") {
      missed.push({ eventId: event.eventId, path: null, reason: "assembled system prompt not on disk; enable ISEEAGENTS_PERSIST_HARNESS_TEXT=1" });
      continue;
    }

    const path = resolveHarnessPath(event, roots);
    if (!path) {
      missed.push({ eventId: event.eventId, path: null, reason: `no resolvable path for ${event.sourceCategory}:${event.sourceAlias}` });
      continue;
    }

    if (!byPath[path]) {
      if (filesUsed >= maxFiles) {
        missed.push({ eventId: event.eventId, path, reason: "max embed file budget reached" });
        continue;
      }
      const read = readCapped(path);
      filesUsed += 1;
      if (!read) {
        missed.push({ eventId: event.eventId, path, reason: "unreadable or missing on build host" });
        continue;
      }
      byPath[path] = read;
    }
    const entry = byPath[path];
    byEventId[event.eventId] = { path, text: entry.text, truncated: entry.truncated, bytes: entry.bytes };
  }

  return { byEventId, byPath, missed };
}

export function harnessLabel(event: ContextEvent): string {
  if (event.sourceCategory === "instructions" || event.sourceCategory === "file_input") {
    const path = resolveHarnessPath(event) ?? event.sourceAlias;
    return path ? `Instructions: ${basename(path)}` : "Instructions";
  }
  if (event.sourceCategory === "skill") return `Skill: ${event.sourceAlias || "unknown"}`;
  if (event.sourceCategory === "system_input") return event.sourceAlias || "System prompt";
  return event.sourceAlias || event.boundary || event.observation;
}
