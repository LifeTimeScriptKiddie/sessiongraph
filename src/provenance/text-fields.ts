/** Explicit common provider text fields. Metadata and role strings are excluded. */
export function payloadTextPointers(payload: unknown): string[] {
  if (!payload || typeof payload !== "object") return typeof payload === "string" ? [""] : [];
  const pointers: string[] = [];
  const addContent = (value: unknown, path: string) => {
    if (typeof value === "string") pointers.push(path);
    else if (Array.isArray(value)) value.forEach((part, i) => {
      if (part && typeof part === "object" && ["text", "input_text", "output_text"].includes(part.type) && typeof part.text === "string") pointers.push(`${path}/${i}/text`);
    });
  };
  const p = payload as Record<string, unknown>;
  addContent(p.system, "/system");
  if (typeof p.input === "string") pointers.push("/input");
  for (const field of ["messages", "input"]) if (Array.isArray(p[field]))
    (p[field] as unknown[]).forEach((message, index) => {
      if (message && typeof message === "object") addContent((message as Record<string, unknown>).content, `/${field}/${index}/content`);
    });
  return pointers;
}
