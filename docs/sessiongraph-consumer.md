# SessionGraph consumer seam

The versioned JSON shape is documented by
`contracts/sessiongraph-generic-event.v1.schema.json`. Each exported event keeps
all declared parents and supplies a `parent_relations` map. Current relations are:

- `recorded_parent`: producer-declared event ancestry
- `response_to`: response associated with a captured request
- `match_source` / `match_request`: the two parents of an inclusion-evidence event
- `summary_ancestor`: source event named in compaction or summary lineage

The inclusion event remains evidence between its two parents. Consumers must not
reinterpret either incoming edge alone as proof that the model used or attended
to the source text.

**Seam version:** `iseeagents.sessiongraph.seam.v2`
**Provenance schema:** `iseeagents.context.v1` (unchanged source of truth in JSONL)

## Intent

Join **context provenance** (iseeagents) to **session/loop health** (SessionGraph) without renaming or mutating SessionGraph’s core `Event` / `Session` model.

| Store | Role |
|---|---|
| `<session>.jsonl` (iseeagents) | Append-only source of truth |
| Derived SQLite index | Rebuildable query surface |
| SessionGraph generic JSONL export | Content-free analysis input |
| SessionGraph `analysis.json` | Health graph; node `id` = provenance `eventId` |

## Export

```bash
node --experimental-strip-types -e '
import { exportJsonlForSessionGraph } from "./src/sessiongraph/export.ts";
exportJsonlForSessionGraph(".iseeagents/SESSION.jsonl", "/tmp/sg-iseeagents.jsonl");
'
sessiongraph analyze /tmp/sg-iseeagents.jsonl --out /tmp/sg-out
```

Exported lines use SessionGraph’s **generic** JSONL fields (`id`, `parent_id`, `parent_ids`, `kind`, `role`, `name`, `timestamp`, `content`, `usage`, …).
`content` is always empty by default. Extra `iseeagents` join metadata is attached for tooling; SessionGraph’s `parse_generic` ignores unknown keys safely.

`kind` values are `iseeagents_<observation>` (e.g. `iseeagents_load`, `iseeagents_usage`).

## Join keys

| iseeagents | SessionGraph |
|---|---|
| `eventId` | `Event.id` / `graph.nodes[].id` |
| `sessionId` | `Session.id` (export basename / stem) |
| `requestId` / `attemptId` | inside export sidecar `iseeagents.*` + SQLite index |
| Union of `parentEventIds` and `lineageEventIds` | `parent_ids`; every declared parent is preserved |
| First declared parent, or null | `parent_id` for compatibility; `parent_ids: []` explicitly declares a root |

Programmatic join: `joinSessionGraphAnalysis(analysis, provenanceEvents)`.

Duplicate event IDs fail export/join rather than silently picking a row. Use a
SessionGraph revision that supports `parent_ids`: older versions lose secondary
parents and invent sequential edges for explicit null roots. The fixed 19-event
fixture retained 7/14 edges and added 11 false edges with the original pair;
seam v2 plus the updated parser preserves 14/14 and adds none.

SessionGraph's generic edges mean declared relationships. The richer iseeagents
projection distinguishes `observed_text_match`, `summary_ancestor`, `response_to`
and `recorded_parent`. Inclusion records carry evidence for edges rather than
appearing as duplicate source nodes. Exact byte spans are relative to the named
UTF-8 text field selected by JSON pointer, not to the whole serialized request.

The optional `inclusion` and `response` observations extend the v1 context vocabulary;
older readers that enumerate observation kinds need an update. No dataclass fork
or raw-text transfer is required in SessionGraph. A recorded match is still a
producer assertion supported by its capture record, not independent transport or
semantic-attention verification.

## Inspector

```bash
npm run graph -- .iseeagents/SESSION.jsonl --out /tmp/provenance.html --analysis /tmp/sg-out/analysis.json
```

Open the generated HTML locally. It embeds a content-free projection and optional
SessionGraph findings. A local file picker accepts another capture without network
requests and clears the previous SessionGraph attachment. SessionGraph findings
are not source-inclusion confidence scores.

## Non-goals

- Do not treat SessionGraph findings as proof of prompt inclusion.
- Do not fork SessionGraph schemas to carry full provenance.
- Do not put raw prompt text into the export by default.
