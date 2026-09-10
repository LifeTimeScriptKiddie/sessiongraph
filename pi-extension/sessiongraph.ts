import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const execFileAsync = promisify(execFile);

export default function sessionGraphExtension(pi: ExtensionAPI) {
  pi.registerCommand("sessiongraph", {
    description: "Analyze the current session locally with SessionGraph",
    handler: async (args, ctx) => {
      const sessionFile = ctx.sessionManager.getSessionFile();
      if (!sessionFile || !existsSync(sessionFile)) {
        ctx.ui.notify("This session has not been persisted yet; add a turn and try again.", "warning");
        return;
      }
      const outputDir = args.trim() || ".sessiongraph/current";
      try {
        await ctx.waitForIdle();
        await execFileAsync("sessiongraph", ["analyze", sessionFile, "--out", outputDir], {
          cwd: ctx.cwd,
          timeout: 120_000,
        });
        ctx.ui.notify("SessionGraph report: " + outputDir + "/report.md", "info");
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        ctx.ui.notify("SessionGraph failed: " + message, "error");
      }
    },
  });
}
