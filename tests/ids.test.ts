import { it } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { hmacKeyFromEnv, keyedId } from "../src/ids.ts";

it("default identifier keys stay stable within the process", () => {
  assert.deepEqual(hmacKeyFromEnv({}), hmacKeyFromEnv({}));
  assert.equal(hmacKeyFromEnv({}).length, 32);
});
it("separate processes do not derive the same key from a reused process ID", () => {
  const script = `Object.defineProperty(process, 'pid', { value: 12345 });
    const { hmacKeyFromEnv } = await import(${JSON.stringify(new URL('../src/ids.ts', import.meta.url).href)});
    console.log(hmacKeyFromEnv({}).toString('hex'));`;
  const run = () => execFileSync(process.execPath, ["--experimental-strip-types", "--input-type=module", "-e", script], { encoding: "utf8" }).trim();
  assert.notEqual(run(), run());
});
it("explicit identifier keys retain deterministic matching", () => {
  const key = hmacKeyFromEnv({ ISEEAGENTS_HMAC_KEY: "synthetic-test-key" });
  assert.equal(keyedId("source", "sample", key), keyedId("source", "sample", hmacKeyFromEnv({ ISEEAGENTS_HMAC_KEY: "synthetic-test-key" })));
});
