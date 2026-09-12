# SessionGraph

A local-first workbench for inspecting coding-agent sessions: activity timelines,
recorded context provenance, and workflow graph analysis in one repository.

The Python SessionGraph analyzer and TypeScript iseeagents recorder/viewer are
included together. The event format keeps its `iseeagents.context.v1` name for
compatibility. No OpenSession code or service is included.

## Try the synthetic demo

Requires Node.js 24 or newer. The recorder and viewer use Node's built-in modules;
no npm dependency installation or account is needed.

```sh
git clone https://github.com/LifeTimeScriptKiddie/sessiongraph.git
cd sessiongraph
npm run demo
```

Open `.sessiongraph/demo/provenance.html` in a browser. The demo uses invented
events and source labels; it never imports your sessions or reads your instructions.
The default view is an activity timeline with event details. Switch to Provenance
to inspect recorded relationships, missing observations, and request/response links.

## Use in Pi

Install the package and start a new Pi session (Node.js 24+):

```sh
pi install git:github.com/LifeTimeScriptKiddie/sessiongraph
```

The package loads the recorder and `/sessiongraph` command together. Recording
starts for sessions where the package is enabled; complete a turn to populate a graph.
Type `/sessiongraph` for a menu, or use:

| Command | Result |
|---|---|
| `/sessiongraph open` | Build and open the current session's activity/provenance graph |
| `/sessiongraph view` | Build HTML without launching a browser, useful over SSH |
| `/sessiongraph report` | Analyze the saved Pi session and write a Markdown report |
| `/sessiongraph status` | Check capture availability and Python analyzer setup |
| `/sessiongraph help` | Show commands and privacy reminders |

Graph viewing needs no Python. Reports require the Python analyzer; if it is
missing, the command shows an exact `uv ... sync --frozen` setup command for the
installed package. It recognizes that package's virtual environment automatically,
or uses `sessiongraph` on PATH. Nothing installs Python dependencies automatically.

Outputs are stored under `.sessiongraph/<session-file-stem>/`; captures are under
`.iseeagents/`. Each graph uses only the current session's capture. Older sessions
without a capture can still be analyzed with `report`. Reports analyze Pi's native
log; the graph displays the recorder's context evidence. Both remain local and
may contain private metadata. HTML omits raw text and local source-file reads.

The package integration is tested against Pi 0.85.1. npm/catalog publication is
separate from this Git installation route.

## Analyze a session

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```sh
uv --directory packages/sessiongraph sync --extra graph --frozen
uv --directory packages/sessiongraph run --frozen sessiongraph analyze tests/fixtures/pi-loop.jsonl --out .sessiongraph/example
```

The example report is written under `packages/sessiongraph/.sessiongraph/example/`.
For a selected real session, pass its absolute path instead of the fixture.
The analyzer is also independently installable from `packages/sessiongraph/`.
See the [analyzer guide](packages/sessiongraph/README.md) for comparison,
scorecards, graph metrics, pipeline verification, and optional visualization.

## Capture and inspect provenance

```sh
# Select an existing Codex rollout explicitly. Output paths must be fresh.
npm run ingest:codex -- /path/to/rollout.jsonl --out .iseeagents/capture.jsonl
npm run export:sessiongraph -- .iseeagents/capture.jsonl --out .iseeagents/analysis-input.jsonl
npm run graph -- .iseeagents/capture.jsonl --out .iseeagents/view.html
```

Pi and Claude adapters are also included. They are opt-in and have different
observation coverage. See [adapter boundaries](docs/adapter-boundaries.md) and
[the inspector guide](docs/provenance-inspector.md). No hooks, background service,
broker connections, or model calls are installed by cloning or running the demo.

## Privacy and evidence boundaries

- This repository contains source code and synthetic fixtures, not real session captures.
- Runtime captures and derived databases are ignored by Git. They may still contain
  private metadata; do not share a whole working folder or `.git` directory.
- HTML generation defaults to no raw text, no source-file reads, and no explicit
  source paths. Source aliases that are absolute paths are reduced to filenames.
  Other metadata and custom labels are not guaranteed anonymous.
- `npm run graph -- ... --include-source-text` explicitly permits embedding recorded
  text and reading referenced local instruction/skill files. Treat that HTML as private.
- Files read during rendering show their current contents, not proof of what the
  agent saw earlier. A recorded match or graph edge does not establish model attention.
- Capture gaps, absent responses, and unknown usage remain visible rather than inferred.

Read [PRIVACY.md](PRIVACY.md) before exporting real sessions.

## Repository layout

| Path | Purpose |
|---|---|
| `src/`, `extensions/` | iseeagents recorder, adapters, activity and provenance viewer |
| `packages/sessiongraph/` | Independently packaged Python analyzer |
| `contracts/` | Versioned analysis and experiment interfaces |
| `tests/`, `fixtures/` | Synthetic recorder/viewer acceptance checks |
| `examples/provenance.html` | Prebuilt synthetic viewer demo |

## Development checks

```sh
npm test
npm run check:public
uv --directory packages/sessiongraph run --extra dev --frozen python -m unittest discover -s tests -q
npm run test:integration
uv --directory packages/sessiongraph run --extra dev --frozen python -m build --no-isolation
```

The lockfile retains existing runtime dependency versions and adds a pinned
`setuptools==80.9.0` build backend. That release predates the 14-day resolution
cooldown; the build-tool refresh used a fixed 2026-08-28 UTC cutoff. The public-source guard checks tracked file names and common private
metadata patterns; it is not a complete secret detector. Release review also uses
a credential scan and inspects synthetic artifacts.

## License

MIT. See [LICENSE](LICENSE). Public project attribution is retained. The combined
workbench is a cleaned source snapshot; private development history is not included.
