import { readFileSync, writeFileSync, mkdirSync, statSync, existsSync } from "node:fs";
import { dirname, basename, win32 } from "node:path";
import { readJsonl } from "../recorder.ts";
import { buildProvenanceGraph } from "../provenance/graph.js";
import { embedHarnessSources } from "./embed-sources.ts";
import type { ContextEvent } from "../schema.ts";

export function renderProvenanceHtml(
  events: ContextEvent[],
  opts: { label?: string; sessiongraph?: unknown; sessiongraphMetrics?: unknown; embedSources?: boolean } = {},
): string {
  buildProvenanceGraph(events); // Validate before emitting a runnable document.
  const template = readFileSync(new URL("template.html", import.meta.url), "utf8");
  const activity = readFileSync(new URL("../activity/project.js", import.meta.url), "utf8").replace(/^export /gm, "");
  const graph = readFileSync(new URL("../provenance/graph.js", import.meta.url), "utf8").replace(/^export /gm, "");
  const viewer = readFileSync(new URL("viewer.js", import.meta.url), "utf8");
  // Raw content and local source paths are private; include them only by explicit opt-in.
  const includeSourceText = opts.embedSources === true;
  const fields = [
    "schemaVersion", "eventId", "sessionId", "agentId", "parentAgentId", "requestId", "attemptId", "toolCallId",
    "producerSeq", "monotonicMs", "wallTime", "parentEventIds", "sourceCategory", "sourceAlias", "sourcePath",
    "sourceKey", "contentVersionKey", "sourceRange", "encoding", "observation", "evidence", "adapterId",
    "adapterVersion", "boundary", "handlerOrdinal", "coverage", "requestSpan", "sourceSpan", "matchMethod",
    "ambiguity", "lineageEventIds", "usageInputTokens", "usageOutputTokens", "usageCachedTokens",
    "estimatedTokens", "byteCount", "charCount", "droppedEvents", "unsupportedBoundary", "truncation",
    "rawTextRedacted", "rawText",
  ];
  const safe = events.map(event => Object.fromEntries(fields.map(key => {
    let value = (event as unknown as Record<string, unknown>)[key] ?? null;
    if (!includeSourceText && (key === "rawText" || key === "sourcePath")) value = null;
    if (!includeSourceText && key === "rawTextRedacted") value = true;
    if (!includeSourceText && key === "sourceAlias" && typeof value === "string") {
      if (/^[A-Za-z]:[\\/]/.test(value)) value = win32.basename(value);
      else if (value.startsWith("/") || value.startsWith("~/")) value = basename(value);
    }
    if (["sourceRange", "sourceSpan", "requestSpan"].includes(key) && value && typeof value === "object") {
      const range = value as { start: number; end: number };
      return [key, { start: range.start, end: range.end }];
    }
    return [key, value];
  })));
  const sg = opts.sessiongraph as { graph?: { nodes?: { id: string }[] }; findings?: { code: string; summary: string; evidence: string[] }[] } | undefined;
  const sessiongraph = sg
    ? {
      graph: { nodes: (sg.graph?.nodes ?? []).map(n => ({ id: n.id })) },
      findings: (sg.findings ?? []).map(f => ({ code: f.code, summary: f.summary, evidence: f.evidence })),
    }
    : null;
  const structural = opts.sessiongraphMetrics as {
    schema_version?: number;
    engine?: string;
    metrics?: Record<string, unknown>;
    scope?: string;
  } | undefined;
  const metricNames = [
    "declared_nodes", "implicit_nodes", "edges", "roots", "leaves",
    "weakly_connected_components", "is_directed_acyclic", "cycle_nodes", "max_depth",
    "request_roots", "outputs", "reachable_outputs", "request_output_coverage",
    "changed_artifacts", "verified_artifacts", "artifact_verification_coverage",
  ];
  const safeMetrics = structural
    ? {
      schema_version: structural.schema_version ?? null,
      engine: typeof structural.engine === "string" ? structural.engine : null,
      metrics: {
        ...Object.fromEntries(metricNames.map(name => [name, structural.metrics?.[name] ?? null])),
        relation_counts: structural.metrics?.relation_counts && typeof structural.metrics.relation_counts === "object"
          ? Object.fromEntries(Object.entries(structural.metrics.relation_counts as Record<string, unknown>)
            .filter(([key, value]) => /^[a-z][a-z0-9_]{0,63}$/.test(key) && typeof value === "number"))
          : {},
      },
      scope: typeof structural.scope === "string" ? structural.scope : "structural measurements only",
    }
    : null;
  const embedSources = includeSourceText;
  const sources = embedSources ? embedHarnessSources(events) : { byEventId: {}, byPath: {}, missed: [] };
  const json = JSON.stringify({
    events: safe,
    label: opts.label || "Recorded context events",
    sessiongraph,
    sessiongraphMetrics: safeMetrics,
    sources,
  }).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
  return template
    .replace("__ISEEAGENTS_DATA__", () => json)
    .replace("__ISEEAGENTS_ACTIVITY__", () => activity)
    .replace("__ISEEAGENTS_GRAPH__", () => graph)
    .replace("__ISEEAGENTS_VIEWER__", () => viewer);
}

export function writeProvenanceHtml(
  input: string,
  output: string,
  opts: { label?: string; sessiongraph?: unknown; sessiongraphMetrics?: unknown; embedSources?: boolean } = {},
) {
  const source = statSync(input);
  if (existsSync(output)) {
    const target = statSync(output);
    if (source.dev === target.dev && source.ino === target.ino) throw new Error("Output must not replace the source capture");
  }
  const html = renderProvenanceHtml(readJsonl(input), opts);
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, html);
}
