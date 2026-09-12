# Input provenance inspector

## What is visible

The inspector reads a selected `iseeagents.context.v1` JSONL capture. It groups source
observations, linked transformations, payload snapshots and recorded responses.
Multiple source observations and summary ancestors remain separate, versioned nodes.
Other source observations in the same session may include later reads; their position
does not mean they were used in the selected request. They are labeled inclusion
unproven unless a matching edge exists.

Click a source or request to inspect every recorded relationship, source version,
boundary and byte span. A summary-ancestor edge never becomes direct request inclusion.
No edge exposes model-internal reasoning or proves which input influenced the result.
Response nodes show metadata, not raw answer text. Missing response events remain
"Output not recorded" even when token usage exists.

The exact matcher verifies source and payload version identifiers before comparing
a source string to an explicitly selected text field. It persists UTF-8 byte spans,
the JSON pointer and identifiers, never the strings. Repeated matches or identical
sources can be ambiguous; the viewer does not convert these into additive token
allocation. Provider counters are displayed individually as recorded; their scope
depends on the adapter. Cached tokens are not extra input usage.

## Local commands

```sh
npm run graph -- CAPTURE.jsonl --out /tmp/iseeagents-provenance.html
# Optional process/graph findings from SessionGraph:
npm run graph -- CAPTURE.jsonl --out /tmp/iseeagents-provenance.html --analysis ANALYSIS.json
```

Open the file in a browser. Prefer the **embedded** HTML from `npm run graph` so you do not need the picker. The **default home view** is the chronological **activity tape** (top) with a **detail pane** (bottom). Use the **Provenance** toggle for the older four-lane inspector.

### Optional source text

Default HTML exports omit raw text and explicit local source paths, and do not
read referenced files. Absolute source aliases are reduced to filenames. Other
metadata remains visible, so an export is not automatically anonymous.

For private local inspection only, add `--include-source-text` to `npm run graph`.
This permits embedding recorded raw text and reading instruction/skill files from
resolved local paths. The programmatic equivalent is `embedSources: true`.
The resulting HTML contains those bytes and should be treated as private.

Text read from disk is the current file, not verified historic request content.
An observed byte-match record is separate evidence and does not prove attention.
Capture-level content opt-ins are `ISEEAGENTS_PERSIST_RAW_TEXT=1` and
`ISEEAGENTS_PERSIST_HARNESS_TEXT=1`; they are independent of the renderer opt-in.


## Evaluation and interpretation check

Open **Check your interpretation** for five questions about unlinked files,
provisional capture, summary ancestry, usage-only output and semantic influence.
The answer stays local. **Save my result** downloads the participant's choices,
timestamp, dataset and score; no identifier is collected and no result is sent.

No participant has been tested as part of implementation. Automated tests exercising
5/5 and 0/5 answers verify the questionnaire's behavior, not human accuracy.
Browser layout, light/dark/mobile and assistive-technology QA are still pending:
the available browser connector returned no browser. Minimal DOM tests cover request
selection, evidence details, file loading/error states and questionnaire scoring.

For a real usability study, freeze this build and fixture, have users independently
answer before revealing scores, and record per-question correctness plus explanations.
Use an alternate fixture to test transfer after familiarization. Report participant
count and denominators. Do not pool repeated attempts from the same person as
independent users or treat knowledge of the terminology as proof they can read the graph.
