"""Offline export benchmark: PYTHONPATH=src python3 tests/benchmark_export.py.

Compare the original dataclasses.asdict export with Event.public on identical
events. Equality is checked before timing; times are medians of five runs.
"""
from dataclasses import asdict
from statistics import median
from time import perf_counter

from sessiongraph.model import Event


def original(event):
    result = asdict(event)
    result.pop("text")
    return result


def run(count=10000):
    events = [Event(str(i), None, "tool_call", text="omitted" * 100,
                    metadata={"redactions": ["secret"]}) for i in range(count)]
    for event in events[:10]:
        assert original(event) == event.public()
    for name, export in (("original_asdict", original), ("current_public", lambda e: e.public())):
        samples = []
        for _ in range(5):
            start = perf_counter()
            result = [export(event) for event in events]
            samples.append(perf_counter() - start)
            assert len(result) == count
        print(f"{name}: {count} events; median {median(samples):.6f}s")


if __name__ == "__main__":
    run()
