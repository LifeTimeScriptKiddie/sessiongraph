# Public source release

This repository combines the SessionGraph Python analyzer with the iseeagents
recorder, adapters, and provenance viewer. The analyzer moved from the repository
root to `packages/sessiongraph/`; its Python module and CLI names are unchanged.

## What is included

- Source code, contracts, synthetic tests, and synthetic HTML examples.
- MIT licensing with the existing public project attribution retained.
- Locked Python dependencies and an empty-dependency Node workspace lockfile.
- A default HTML export that omits raw text and explicit source paths, and does
  not read local source files without an explicit content opt-in.

## What is excluded

Runtime captures, personal home-directory paths, local databases, private project
notes, private development commits, and developer environments are not included.
Existing public repository history was inspected before the combined snapshot
was added. The source snapshot does not require importing a private Git history.

## Verification

Run the commands in the root README. The public-source check is a pattern guard,
not a comprehensive secret scanner. A release review must also inspect credential
scanner findings and any generated examples. Hash identifiers in `sourceKey` and
`contentVersionKey` can trigger generic API-key heuristics; review their field
context rather than suppressing all key-shaped values.

The current synthetic viewer is covered by automated interaction checks. Visual
inspection in a real browser was unavailable in the release environment.

## Contributing

Use the root tests for capture/viewer changes and the packaged Python tests for
analysis changes. Run `npm run test:integration` for event-contract changes.
Keep fixtures synthetic and never attach real session captures to a public issue.
Public source sharing does not make user-generated captures anonymous.
