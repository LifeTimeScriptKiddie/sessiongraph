# Contributing to SessionGraph

Thanks for helping. SessionGraph is deliberately small, dependency-free, and
privacy-first — contributions should keep it that way.

## Ground rules

- **No runtime dependencies.** The package must run on the Python standard
  library alone (`dependencies = []`). Dev-only tooling goes in the `dev`
  optional-dependency group. NetworkX and PyVis remain opt-in through the
  `graph` and `visual` extras.
- **Never execute session data.** Session content is untrusted input; parse it,
  never run it. See [SECURITY.md](SECURITY.md).
- **Content-free by default.** New output must not leak transcript or
  tool-argument content unless `--include-content` is set, and even then it
  passes through redaction.
- **Deterministic and offline.** No network calls, no model calls.

## Development

```bash
cd sessiongraph
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[dev]"

# tests + compile check (what CI runs)
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## Pull requests

- Add or update tests for any behavior change (detectors especially).
- Keep findings evidence-backed (event IDs / fingerprints), not speculative.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Do not attach real session transcripts to issues or PRs — use a minimal
  synthetic reproducer.
