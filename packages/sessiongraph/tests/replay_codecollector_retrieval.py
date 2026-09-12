"""Offline contract replay using the actual CodeCollector producer classes.

PYTHONPATH=src python3 tests/replay_codecollector_retrieval.py
Only fetch is mocked: no network request, browser, or model is started.
"""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sessiongraph.analyze import analyze, compare
from sessiongraph.retrieval import load_retrieval

producer = Path(__file__).resolve().parents[2] / "insane_research_standalone"
sys.path.insert(0, str(producer))
import standalone_fetch
from engine import Attempt, FetchResult


def replay():
    attempts = [
        Attempt("probe", "curl_cffi", "https://example.invalid/private", "original",
                None, "", verdict="blocked", elapsed_s=2),
        Attempt("grid", "curl_cffi", "https://example.invalid/private", "original",
                "chrome", "", verdict="strong_ok", elapsed_s=1),
    ]
    analyses = []
    with TemporaryDirectory() as directory:
        for label, trace in (("baseline", attempts), ("candidate", attempts[1:])):
            result = FetchResult(ok=True, trace=trace, stop_reason="success", content="PRIVATE_BODY")
            with patch.object(standalone_fetch, "fetch", return_value=result):
                payload = standalone_fetch.fetch_for_harness("https://example.invalid/private")
            path = Path(directory) / f"{label}.json"
            path.write_text(json.dumps(payload, indent=2))
            session = load_retrieval(path)
            analysis = analyze(session)
            assert "example.invalid" not in json.dumps(analysis)
            assert "PRIVATE_BODY" not in json.dumps(analysis)
            analyses.append(analysis)
        delta = compare(*analyses)
        assert delta["delta"]["retrieval_attempts"] == -1
        assert delta["delta"]["retrieval_elapsed_s"] == -2
        assert delta["delta"]["retrieval_success"] == 0
        print(json.dumps(delta, indent=2))
        print("PASS: actual producer schema replayed offline; candidate is synthetic, not a measured policy improvement")


if __name__ == "__main__":
    replay()
