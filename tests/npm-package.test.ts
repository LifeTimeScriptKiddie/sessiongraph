import { it } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

it("packed npm runtime imports and runs its demo from node_modules", () => {
  const root = fileURLToPath(new URL("../", import.meta.url));
  const npm = process.env.npm_execpath;
  assert.ok(npm, "Run through npm test so the npm CLI is available");
  const work = mkdtempSync(join(tmpdir(), "sessiongraph-npm-"));
  const packed = JSON.parse(execFileSync(process.execPath, [npm, "pack", "--ignore-scripts", "--json", "--pack-destination", work], { cwd: root, encoding: "utf8" }))[0];
  assert.ok(packed.files.some((f: { path: string }) => f.path === "dist/extensions/pi/iseeagents-observer.js"));
  assert.ok(!packed.files.some((f: { path: string }) => /\.ts$|(?:^|\/)(?:\.env|\.venv|__pycache__|\.iseeagents|\.sessiongraph)(?:\/|$)/.test(f.path)));
  execFileSync(process.execPath, [npm, "install", "--prefix", work, "--offline", "--ignore-scripts", "--no-audit", "--no-fund", join(work, packed.filename)], { stdio: "pipe" });
  execFileSync(process.execPath, ["--input-type=module", "-e", "import * as sg from '@lifetimescriptkiddie/sessiongraph'; if (!Object.keys(sg).length) throw Error('Empty package');"], { cwd: work, stdio: "pipe" });
  const pkg = join(work, "node_modules", "@lifetimescriptkiddie", "sessiongraph");
  const manifest = JSON.parse(readFileSync(join(pkg, "package.json"), "utf8"));
  for (const entry of manifest.pi.extensions) assert.ok(existsSync(join(pkg, entry)));
  execFileSync(process.execPath, [join(pkg, "dist/scripts/create-public-demo.js")], { cwd: work, stdio: "pipe" });
  assert.ok(existsSync(join(work, ".sessiongraph/demo/provenance.html")));
});
