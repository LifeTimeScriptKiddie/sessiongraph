# Privacy model

Session transcripts can contain proprietary code, personal data, filesystem paths, and credentials. SessionGraph therefore processes files locally, makes no network calls, does not retain the raw input, replaces the recorded working directory with a fingerprint, reduces the source path to its filename, and omits message/tool content from output by default.

`--include-content` is an explicit escape hatch. Included content is sanitized with pattern-based and structural redaction, but no detector is perfect. Review artifacts before sharing them. Stable content fingerprints can also be vulnerable to guessing when the original value comes from a very small known set; treat reports as sensitive metadata.

The Pi extension executes with the user's permissions because that is Pi's extension model. It passes only an input session path and output directory to the locally installed CLI. The optional agentctl flow receives a copied report rather than the transcript, and must be invoked explicitly.

This project analyzes workflows, not workers. Do not use its heuristic score for employee ranking, discipline, or individual performance decisions.
