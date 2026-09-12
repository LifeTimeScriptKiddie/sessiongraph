import { createHmac, createHash, randomUUID } from "node:crypto";

export function newEventId(): string {
  return randomUUID();
}

export function hmacKeyFromEnv(env: NodeJS.ProcessEnv = process.env): Buffer {
  const raw = env.ISEEAGENTS_HMAC_KEY;
  if (!raw) {
    // Ephemeral per-process key when unset — identifiers stay local-session only.
    return createHash("sha256").update(`iseeagents-ephemeral:${process.pid}`).digest();
  }
  return createHash("sha256").update(raw).digest();
}

export function keyedId(kind: string, material: string, key: Buffer): string {
  return createHmac("sha256", key).update(`${kind}:${material}`).digest("hex").slice(0, 32);
}

export function contentVersionKey(bytes: string | Buffer, key: Buffer): string {
  const h = createHmac("sha256", key).update(bytes).digest("hex").slice(0, 32);
  return `cv_${h}`;
}

export function looksSecretLike(text: string): boolean {
  if (/sk-[a-zA-Z0-9]{20,}/.test(text)) return true;
  if (/-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----/.test(text)) return true;
  if (/api[_-]?key\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}/i.test(text)) return true;
  if (/Bearer\s+[a-zA-Z0-9\-._~+/]+=*/.test(text)) return true;
  return false;
}
