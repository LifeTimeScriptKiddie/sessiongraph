from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .model import Event, Session


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    summary: str
    evidence: list[str]
    recommendation: str


CORRECTION_TERMS = (
    "no,", "not what i", "that's wrong", "that is wrong", "try again", "you missed",
    "stop", "instead", "still failing", "doesn't work", "does not work",
)


def _repeated(events: list[Event], minimum: int = 3, window: int = 8) -> list[Finding]:
    findings: list[Finding] = []
    actions = [event for event in events if event.kind == "tool_call"]
    failed_calls = {
        event.parent_id for event in events
        if event.kind == "tool_result" and event.is_error and event.parent_id
    }
    successful_calls = {
        event.parent_id for event in events
        if event.kind == "tool_result" and not event.is_error and event.parent_id
    }
    emitted: set[str] = set()
    for end in range(len(actions)):
        start = max(0, end - window + 1)
        group = [event for event in actions[start:end + 1] if event.signature == actions[end].signature]
        failures = sum(event.id in failed_calls for event in group)
        recovered = any(event.id in successful_calls for event in group)
        if (
            len(group) >= minimum and failures >= minimum - 1 and not recovered
            and actions[end].signature not in emitted
        ):
            emitted.add(actions[end].signature)
            findings.append(Finding(
                "repeated_action", "warning",
                f"Repeated {actions[end].name or 'tool'} action {len(group)} times in a short window",
                [event.id for event in group],
                "Add an explicit retry budget and require a changed hypothesis or input after two identical attempts.",
            ))
    return findings


def _alternating(events: list[Event]) -> list[Finding]:
    actions = [event for event in events if event.kind == "tool_call"]
    failed_calls = {
        event.parent_id for event in events
        if event.kind == "tool_result" and event.is_error and event.parent_id
    }
    for index in range(3, len(actions)):
        chunk = actions[index - 3:index + 1]
        sigs = [event.signature for event in chunk]
        if (
            sigs[0] == sigs[2] and sigs[1] == sigs[3] and sigs[0] != sigs[1]
            and sum(event.id in failed_calls for event in chunk) >= 2
        ):
            return [Finding(
                "alternating_loop", "warning", "Detected an A-B-A-B tool-call loop",
                [event.id for event in chunk],
                "Introduce a checkpoint after the second cycle: summarize evidence, select a new strategy, or ask the user.",
            )]
    return []


def _quality(events: list[Event]) -> list[Finding]:
    findings: list[Finding] = []
    # An errored tool result is "recovered" when the same tool signature
    # succeeds later in the session: transient failures (a search that finds
    # nothing, a test that fails then passes) are normal and should not raise a
    # finding. Non-tool aborts have no recovery path and always count. This
    # keeps the signal on failures the run never got past, instead of a raw
    # error tally that fires on nearly every real session.
    call_signature = {event.id: event.signature for event in events if event.kind == "tool_call"}
    last_success: dict[str, int] = {}
    for index, event in enumerate(events):
        if event.kind == "tool_result" and not event.is_error and event.parent_id in call_signature:
            last_success[call_signature[event.parent_id]] = index

    def _recovered(index: int, event: Event) -> bool:
        if event.kind == "tool_result" and event.parent_id in call_signature:
            return last_success.get(call_signature[event.parent_id], -1) > index
        return False

    errors = [event for event in events if event.is_error]
    unrecovered = [
        event for index, event in enumerate(events)
        if event.is_error and not _recovered(index, event)
    ]
    if unrecovered:
        recovered = len(errors) - len(unrecovered)
        summary = f"Observed {len(unrecovered)} unrecovered error(s)"
        if recovered:
            summary += f" ({len(errors)} total; {recovered} later recovered by a retry of the same tool)"
        findings.append(Finding(
            "errors", "warning", summary,
            [event.id for event in unrecovered[:10]],
            "Classify failures before retrying and record whether the next action changes the failing condition.",
        ))
    corrections = [
        event for event in events
        if event.role == "user" and any(term in event.text.lower() for term in CORRECTION_TERMS)
    ]
    if corrections:
        findings.append(Finding(
            "user_correction", "info", f"Detected {len(corrections)} likely user correction turns",
            [event.id for event in corrections[:10]],
            "Convert repeated corrections into a concise project instruction or pre-flight checklist, then compare future sessions.",
        ))
    if events and events[-1].is_error:
        findings.append(Finding(
            "dead_end", "critical", "Session ended on an error or abort",
            [events[-1].id],
            "Require a terminal handoff containing current state, blocker, and one safe next action.",
        ))
    return findings


def _agentctl_quality(events: list[Event]) -> list[Finding]:
    findings: list[Finding] = []
    timeouts = [
        event for event in events
        if event.kind in {"loop_generate", "loop_evaluate"}
        and str(event.metadata.get("failureClass", "")).lower() == "timeout"
    ]
    if timeouts:
        findings.append(Finding(
            "agent_timeout", "warning",
            f"Observed {len(timeouts)} timed-out agentctl loop stage(s)",
            [event.id for event in timeouts[:10]],
            "Record the failed adapter, preserve completed branches, and retry through a bounded fallback edge.",
        ))
    timed = [
        event for event in events
        if isinstance(event.metadata.get("durationMs"), (int, float))
        and not isinstance(event.metadata.get("durationMs"), bool)
        and event.metadata["durationMs"] >= 0
    ]
    total_duration = sum(event.metadata["durationMs"] for event in timed)
    durations: Counter[str] = Counter()
    for event in timed:
        durations[event.kind.removeprefix("loop_")] += event.metadata["durationMs"]
    if total_duration >= 30_000 and durations:
        slowest, slowest_duration = durations.most_common(1)[0]
        share = slowest_duration / total_duration
        if share >= 0.75:
            evidence = [event.id for event in timed if event.kind == f"loop_{slowest}"]
            findings.append(Finding(
                "loop_bottleneck", "info",
                f"The {slowest} stage consumed {share:.0%} of recorded agent time",
                evidence[:10],
                "Test a faster first-pass stage or conditional escalation while holding the acceptance threshold fixed.",
            ))
    return findings


def analyze(session: Session) -> dict[str, Any]:
    events = session.events
    children: dict[str, list[str]] = defaultdict(list)
    ids = {event.id for event in events}
    dangling: list[str] = []
    for event in events:
        if event.parent_id:
            children[event.parent_id].append(event.id)
            if event.parent_id not in ids:
                dangling.append(event.id)
    branches = {parent: values for parent, values in children.items() if len(values) > 1}
    tool_counts = Counter(event.name or "unknown" for event in events if event.kind == "tool_call")
    usage: Counter[str] = Counter()
    for event in events:
        usage.update(event.usage)
    findings = _repeated(events) + _alternating(events) + _quality(events)
    if session.format == "agentctl-loop-v1":
        findings += _agentctl_quality(events)
    if session.format == "pipeline-v1" and not session.metadata["pipeline_success"]:
        failures = [event.id for event in events if event.is_error]
        findings.append(Finding(
            "pipeline_contract", "critical", "Declared pipeline verification contract is not satisfied",
            failures[:10] or ["result"],
            "Inspect failed or missing stage/check evidence; repair the producer while keeping the fixture, "
            "verifier and required checks fixed. A successful process exit is insufficient.",
        ))
    if session.format == "retrieval-v1" and session.metadata.get("retrieval_escalation_deferred"):
        findings.append(Finding(
            "escalation_deferred", "warning", "Retrieval requires browser escalation",
            ["result"], "Check the recorded escalation requirement before treating this source as complete.",
        ))
    if dangling:
        findings.append(Finding(
            "dangling_edges", "info", f"Graph has {len(dangling)} events whose parent is absent",
            dangling[:10], "Load the complete session branch when lineage analysis matters.",
        ))
    score = max(0, 100 - sum({"info": 3, "warning": 12, "critical": 30}[f.severity] for f in findings))
    loop_durations: Counter[str] = Counter()
    if session.format == "agentctl-loop-v1":
        for event in events:
            duration = event.metadata.get("durationMs")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                loop_durations[event.kind.removeprefix("loop_")] += duration
    return {
        "schema_version": 1,
        "session": {
            "id": session.id, "source": Path(session.source).name,
            "format": session.format, "metadata": session.metadata,
        },
        "metrics": {
            "events": len(events), "edges": sum(bool(event.parent_id) for event in events),
            "branches": len(branches), "tool_calls": sum(tool_counts.values()),
            "tool_counts": dict(tool_counts), "usage": dict(usage), "workflow_health": score,
            **(session.metadata if session.format in {"retrieval-v1", "pipeline-v1"} else {}),
            **({
                "loop_iterations": max((event.metadata.get("iteration", 0) for event in events), default=0),
                "loop_retries": sum(
                    event.kind == "loop_decision" and event.metadata.get("action") == "retry"
                    for event in events
                ),
                "loop_status": session.metadata.get("status"),
                "loop_duration_ms": sum(loop_durations.values()),
                "loop_stage_duration_ms": dict(loop_durations),
            } if session.format == "agentctl-loop-v1" else {}),
        },
        "findings": [asdict(finding) for finding in findings],
        "graph": {
            "nodes": [{"id": event.id, "kind": event.kind, "role": event.role, "name": event.name,
                       "signature": event.signature, "is_error": event.is_error} for event in events],
            "edges": [{"from": event.parent_id, "to": event.id} for event in events if event.parent_id],
        },
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_metrics, after_metrics = before["metrics"], after["metrics"]
    pipeline = "pipeline-v1" in {before["session"]["format"], after["session"]["format"]}
    if pipeline:
        if before["session"]["format"] != after["session"]["format"]:
            raise ValueError("pipeline comparison requires two pipeline-v1 analyses")
        for field in ("fixture_sha256", "verifier_sha256", "contract_sha256"):
            left = before["session"].get("metadata", {}).get(field)
            right = after["session"].get("metadata", {}).get(field)
            if not left or left != right:
                raise ValueError(f"pipeline comparison requires matching {field}")
    keys = ["events", "tool_calls", "branches", "workflow_health"]
    keys.extend(
        key for key in ("loop_iterations", "loop_retries", "loop_duration_ms",
                        "retrieval_attempts", "retrieval_unsuccessful_attempts", "retrieval_elapsed_s",
                        "retrieval_success", "retrieval_escalation_deferred")
        if key in before_metrics or key in after_metrics
    )
    if pipeline:
        keys.extend(("pipeline_checks_required", "pipeline_checks_passed", "pipeline_checks_failed",
                     "pipeline_checks_missing", "pipeline_stages_completed", "pipeline_stages_missing",
                     "pipeline_timeouts", "pipeline_duration_ms", "pipeline_success"))
    return {
        "schema_version": 1,
        "before": before["session"]["id"], "after": after["session"]["id"],
        "delta": {key: after_metrics.get(key, 0) - before_metrics.get(key, 0) for key in keys},
        "finding_delta": len(after.get("findings", [])) - len(before.get("findings", [])),
        **({"comparable": True, "comparison_scope": "same fixture, verifier and declared contract; reported checks only",
            "before_source_sha256": before["session"]["metadata"].get("source_sha256"),
            "after_source_sha256": after["session"]["metadata"].get("source_sha256")}
           if pipeline else {}),
    }
