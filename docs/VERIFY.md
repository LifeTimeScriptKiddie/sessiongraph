# Verify detectors before trusting them

SessionGraph never takes an agent's output as given, and that includes its own detectors. A detector is code that answers yes or no for one event. Its answer can become a finding only after human labels show how often it is right.

| Step | What happens | Output |
| --- | --- | --- |
| Check | Code answers yes or no per turn, from recorded fields only | `flags` per detector |
| Label | A human labels every flagged turn and a random sample of unflagged ones | `label`, `labeled_by: human` |
| Verify | Precision on the flagged turns; recall estimated from the sample | `verified`, `unverified` or `insufficient_labels` |
| Recommend | Only verified detectors may drive a recommendation | (next step) |

## Run it

```sh
sessiongraph label-corrections --claude-code ~/.claude/projects --out corrections.jsonl
sessiongraph label corrections.jsonl            # interactive; y / n / s / q
sessiongraph verify-detectors corrections.jsonl --require behavior
```

`verify-detectors` exits 0 only when every `--require`d detector is verified. The defaults are at least 10 labeled hits, precision ≥ 0.8 and estimated recall ≥ 0.5.

## Who wrote the turn

A `user`-role turn isn't always a person. Author comes from recorded fields, never from the text:

| Author | Recorded evidence |
| --- | --- |
| human | `origin.kind: human`, `promptSource: typed/queued` |
| agent | `entrypoint: sdk-cli` or `promptSource: sdk` (headless runs such as agentctl), peer messages |
| system | `isMeta`, task notifications, auto-continuation, compaction summaries |
| unknown | no marker: never judged as human |

## User-correction detectors

| Detector | Yes when |
| --- | --- |
| `keyword_any_author` | A correction word appears in any user turn. This is the current `analyze` rule, kept as the baseline |
| `keyword_human` | The same rule, human turns only |
| `behavior` | The human stopped the previous run (an interrupt, or a `user-rejected` tool call), or the agent ran `git restore/checkout --/revert/reset --hard/stash` within 5 tool calls after the turn |

Classifier denials and safety interrupts do not count as a human stopping the agent.

## Why labels must come from a human

If an agent writes the ground truth, the agent is being trusted again. Only rows with `labeled_by: human` count, plus rows that code settles as "no" because a human didn't type the turn (`labeled_by: code`). Any other labels, including a `code` label on a human turn, are reported as `ignored_non_human_labels`. `sessiongraph label` refuses to run without a terminal. That stops a pipe or an agent, but not someone editing the file by hand.

## Privacy

Sheets and reports hold transcript paths, turn IDs, authors and yes/no flags, and never turn text. `label` re-reads the text from the transcript while you label. Transcript paths are local metadata, so keep sheets private.
