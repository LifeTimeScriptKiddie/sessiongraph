import { execFile } from "node:child_process";
import { existsSync, realpathSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { writeProvenanceHtml } from "../../../src/viewer/render.ts";

const execFileAsync = promisify(execFile);
const analyzerRoot = resolve(dirname(realpathSync(fileURLToPath(import.meta.url))), "..");
const HELP = [
  "/sessiongraph — choose an action",
  "/sessiongraph open — build and open this session's activity/provenance graph (no Python needed)",
  "/sessiongraph view — build the HTML graph without opening a browser",
  "/sessiongraph report — analyze the current Pi session for errors and repeated actions",
  "/sessiongraph status — show capture and analyzer readiness",
  "/sessiongraph help — show this help",
  "Graphs omit raw text by default. Captures and reports remain local and may contain private metadata.",
].join("\n");
const choices = {
  "Open activity / provenance graph": "open",
  "Analyze session and write report": "report",
  "Check capture and analyzer setup": "status",
  "Help": "help",
};

function backend(): string {
  const local = join(analyzerRoot, ".venv", process.platform === "win32" ? "Scripts/sessiongraph.exe" : "bin/sessiongraph");
  return existsSync(local) ? local : "sessiongraph";
}
function setupHelp(): string {
  const quotedRoot = process.platform === "win32"
    ? "'" + analyzerRoot.replace(/'/g, "''") + "'"
    : "'" + analyzerRoot.replace(/'/g, "'\"'\"'") + "'";
  return "The Python analyzer is not installed or is unavailable on PATH. Graph viewing still works.\n"
    + "With Python 3.11+ and uv installed, run:\n"
    + `uv --directory ${quotedRoot} sync --frozen\n`
    + "Then retry /sessiongraph report. No Python packages are installed automatically.";
}

export default function sessionGraphExtension(pi: ExtensionAPI) {
  pi.registerCommand("sessiongraph", {
    description: "Open session graphs, analyze activity, or check setup",
    handler: async (args, ctx) => {
      let action = args.trim().toLowerCase();
      if (!action) {
        if (!ctx.hasUI) action = "status";
        else {
          const selected = await ctx.ui.select("SessionGraph", Object.keys(choices));
          if (!selected) return;
          action = choices[selected as keyof typeof choices];
        }
      }
      if (action === "help") { ctx.ui.notify(HELP, "info"); return; }
      if (!["open", "view", "report", "status"].includes(action)) {
        ctx.ui.notify("Unknown action. Use /sessiongraph help.", "warning"); return;
      }
      try {
        await ctx.waitForIdle();
        const sessionFile = ctx.sessionManager.getSessionFile();
        const id = sessionFile ? basename(sessionFile).replace(/\.jsonl?$/, "") : null;
        const capture = id ? join(ctx.cwd, ".iseeagents", `${id}.jsonl`) : null;
        const hasCapture = !!capture && existsSync(capture) && statSync(capture).size > 0;
        if (action === "status") {
          let analyzer = "ready";
          try { await execFileAsync(backend(), ["--help"], { cwd: ctx.cwd, timeout: 10_000 }); }
          catch (error) {
            analyzer = (error as NodeJS.ErrnoException).code === "ENOENT"
              ? setupHelp() : `unavailable: ${error instanceof Error ? error.message : String(error)}`;
          }
          ctx.ui.notify([
            `Current session: ${sessionFile ? "saved" : "not saved yet"}`,
            `Capture: ${hasCapture ? "ready" : "no recorded activity yet; complete a turn with this package enabled"}`,
            `Analyzer: ${analyzer}`,
            "Use /sessiongraph open for a graph or /sessiongraph report for analysis.",
          ].join("\n"), "info");
          return;
        }
        if (!sessionFile || !existsSync(sessionFile) || !id) {
          ctx.ui.notify("This session is not saved yet. Complete a turn in a saved Pi session, then retry.", "warning"); return;
        }
        const outputDir = join(ctx.cwd, ".sessiongraph", id);
        if (action === "report") {
          try {
            await execFileAsync(backend(), ["analyze", sessionFile, "--out", outputDir], { cwd: ctx.cwd, timeout: 120_000 });
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code === "ENOENT") { ctx.ui.notify(setupHelp(), "warning"); return; }
            throw error;
          }
          ctx.ui.notify(`Session report ready: ${join(outputDir, "report.md")}`, "info");
          return;
        }
        if (!hasCapture || !capture) {
          ctx.ui.notify("No recorded context for this session yet. Complete a turn with the SessionGraph package enabled, then retry. /sessiongraph report can analyze older Pi sessions without a capture.", "warning"); return;
        }
        const html = join(outputDir, "provenance.html");
        writeProvenanceHtml(capture, html, { embedSources: false });
        ctx.ui.notify(`Graph ready: ${html}`, "info");
        if (action === "open") {
          try {
            const url = pathToFileURL(html).href;
            if (process.platform === "darwin") await execFileAsync("open", [url], { timeout: 10_000 });
            else if (process.platform === "win32") await execFileAsync("rundll32.exe", ["url.dll,FileProtocolHandler", url], { timeout: 10_000 });
            else await execFileAsync("xdg-open", [url], { timeout: 10_000 });
          } catch {
            ctx.ui.notify(`Could not launch a browser. Open this file manually: ${html}`, "warning");
          }
        }
      } catch (error) {
        ctx.ui.notify(`SessionGraph failed: ${error instanceof Error ? error.message : String(error)}`, "error");
      }
    },
  });
}
