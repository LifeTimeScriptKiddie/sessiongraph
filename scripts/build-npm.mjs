// Build the npm runtime using Node's built-in TypeScript stripper; no compiler dependency.
import { stripTypeScriptTypes } from 'node:module';
import { readdirSync, readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
function build(path) {
  const relativePath = relative(root, path);
  const target = join(root, 'dist', relativePath.replace(/\.ts$/, '.js'));
  mkdirSync(dirname(target), { recursive: true });
  if (path.endsWith('.ts')) {
    const js = stripTypeScriptTypes(readFileSync(path, 'utf8'), { mode: 'strip' })
      .replace(/((?:from\s*|import\s*\(|srcUrl\s*\()\s*["'][^"'\n]+)\.ts(["'])/g, '$1.js$2');
    writeFileSync(target, js);
  } else copyFileSync(path, target);
}
function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path);
    else if (entry.isFile() && /\.(ts|js|html)$/.test(entry.name)) build(path);
  }
}
walk(join(root, 'src'));
build(join(root, 'extensions/pi/iseeagents-observer.ts'));
build(join(root, 'packages/sessiongraph/pi-extension/sessiongraph.ts'));
build(join(root, 'scripts/create-public-demo.ts'));
build(join(root, 'scripts/create-graph-fixture.ts'));
