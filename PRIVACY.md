# Privacy

The published repository contains code, documentation, and synthetic examples.
It does not contain the developer's local captures, credentials, personal home
paths, or private project notes. This statement describes the reviewed release;
it is not a guarantee about files a user later imports or generates.

## Local operation

Recorders can observe private activity metadata, source aliases, session IDs,
timestamps, and usage. Raw text persistence is disabled by default in the adapters.
Environment opt-ins such as `ISEEAGENTS_PERSIST_RAW_TEXT` and
`ISEEAGENTS_PERSIST_HARNESS_TEXT` permit additional content. Review captures before
sharing, including when raw-text persistence is off.

The provenance renderer does not embed raw text or read referenced source files
unless the caller explicitly sets `embedSources: true` or uses the CLI's
`--include-source-text` flag. By default, `sourcePath` is omitted and absolute
source aliases are reduced to filenames. Timestamps, IDs, filenames, arbitrary
labels, and other metadata can still identify a person or project.

The browser file picker reads the capture you explicitly choose on your machine.
That local inspection is not an anonymization or publication workflow. Optional
source-text HTML embeds bytes into the output file; distributing the HTML also
distributes those bytes. Reading a current file cannot verify its historic contents.

## Sharing source

Use a reviewed Git snapshot, not a zip of a working directory. `.gitignore` excludes
captures, caches, databases, virtual environments, and build outputs from ordinary
commits. It does not exclude them from filesystem copies and does not protect
files already tracked. Public Git history needs its own review.

`npm run check:public` checks tracked content and `--history` additionally checks
reachable HEAD history for common private metadata. Combine it with a secret
scanner and human review. Never treat a clean scan as proof of complete anonymity.

The Python analyzer has its own [content-redaction boundary](packages/sessiongraph/PRIVACY.md).
