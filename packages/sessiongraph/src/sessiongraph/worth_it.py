"""Worth-it gate: should this workflow be engineered, cheaply fixed, or left alone?

Graph or loop engineering costs design time, evaluation runs and harness
complexity. It pays only for workflows that repeat, recur across days, and have
a real problem (failures, high cost, or erratic execution). Everything else gets
"observe" with the reasons, so the user knows why nothing changed.

Verdicts, per workflow family:
- observe:   not enough evidence, or cheap and stable. Visualize only.
- cheap_fix: a setting or routing change with a clear expected saving (for
             example, run lookup-shaped requests at low effort). No new loop.
- engineer:  repeated and problematic. Codify it (skill, slash command, task
             graph, checklist) and measure before and after.
"""

from __future__ import annotations

from typing import Any

# Evidence bar (agentctl's graph improve uses >= 3 graphs; a workflow needs more to be called "repeated").
THRESHOLDS: dict[str, float] = {
    "min_requests": 5,
    "min_sessions": 3,
    "min_days": 2,
    # engineer when runs end on errors they did not recover from...
    "unrecovered_rate": 0.1,
    "unrecovered_min": 3,
    # ...or when execution is erratic AND error-prone on non-trivial work (erratic alone is normal for long tasks)
    "erratic_entropy": 1.5,
    "erratic_dominant_share": 0.5,
    "erratic_friction_rate": 0.3,
    "erratic_min_steps": 6,
    # cheap fix for lookups
    "lookup_min_share": 0.15,
    "lookup_min_tokens": 250,
}

LOOKUP_FAMILIES = {"lookup", "answer-only"}


def judge_family(fam: dict[str, Any], effort_evidence: dict[str, Any] | None = None, t: dict[str, float] = THRESHOLDS,
                 lookup_share: float | None = None) -> dict[str, Any]:
    """Verdict, reasons and (when not observe) a recommendation with its success metric."""
    name = fam["family"]
    base = fam.get("base_family", name)  # without the `<repo>/` prefix of a per-repo family
    reasons: list[str] = []
    n, sessions, days = fam["requests"], fam["sessions"], fam["days"]
    evidence_ok = n >= t["min_requests"] and sessions >= t["min_sessions"] and days >= t["min_days"]
    if not evidence_ok:
        reasons.append(
            f"not enough evidence: {n} request(s) in {sessions} session(s) over {days} day(s); "
            f"needs {int(t['min_requests'])} requests, {int(t['min_sessions'])} sessions, {int(t['min_days'])} days"
        )
        return {"verdict": "observe", "reasons": reasons, "recommendation": None}

    metric_base = f"families.{name}"
    if base in LOOKUP_FAMILIES:
        share = lookup_share if lookup_share is not None else fam["share"]
        if share < t["lookup_min_share"] or (fam.get("median_output_tokens") or 0) < t["lookup_min_tokens"]:
            reasons.append(f"question-answering is {round(share * 100)}% of requests at a median {fam.get('median_output_tokens') or 0} output tokens: too small to tune")
            return {"verdict": "observe", "reasons": reasons, "recommendation": None}
        what = "answered without tools" if base == "answer-only" else "answered by reading only (explore)"
        reasons.append(f"{round(share * 100)}% of all requests are question-answering; this family ({what}) is "
                       f"{round(fam['share'] * 100)}%, median {fam['median_output_tokens']} output tokens each")
        saving = None
        if effort_evidence:
            levels = {lv["effort"]: lv for lv in effort_evidence.get("levels", [])}
            low = levels.get("low")
            top = max((lv for lv in levels.values() if lv is not low), key=lambda lv: lv.get("medianOutputTokens") or 0, default=None)
            if low and top and low.get("passRate") is not None and top.get("passRate") is not None and low["passRate"] >= top["passRate"]:
                saving = 1 - (low["medianOutputTokens"] or 0) / max(1, top["medianOutputTokens"] or 1)
                reasons.append(
                    f"effort sweep: low passed {round(low['passRate'] * 100)}% vs {top['effort']} {round(top['passRate'] * 100)}% "
                    f"with {round(saving * 100)}% fewer output tokens"
                )
        return {
            "verdict": "cheap_fix",
            "reasons": reasons,
            "recommendation": {
                "id": "lookups-low-effort" + (f"-{name.split('/', 1)[0]}" if base != name else ""),
                "change": "Run lookup-shaped requests at low effort (or on a fast lane): in Claude Code, `/effort low` "
                          "for question-answering sessions or a lower default `effortLevel`; in agentctl, delegate "
                          "lookups with effort low.",
                "surfaces": ["claude-code: effortLevel / /effort", "agentctl: delegate effort", "codex: model_reasoning_effort"],
                "expected": f"output tokens per lookup down{f' about {round(saving * 100)}%' if saving else ''}; error rate unchanged",
                "metric": {"key": f"{metric_base}.median_output_tokens", "direction": "down"},
                "guard": {"key": f"{metric_base}.error_rate", "direction": "not_up"},
            },
        }

    problems: list[str] = []
    unrecovered = fam.get("unrecovered_rate", 0)
    if unrecovered >= t["unrecovered_rate"] and fam["ended_in_error"] >= t["unrecovered_min"]:
        problems.append(f"{fam['ended_in_error']} run(s) ({round(unrecovered * 100)}%) ended on an error they did not recover from")
    erratic = (fam["variant_entropy"] >= t["erratic_entropy"] and fam["dominant_share"] < t["erratic_dominant_share"]
               and fam["median_steps"] >= t["erratic_min_steps"])
    friction = fam.get("friction_rate", fam["error_rate"])
    if erratic and friction >= t["erratic_friction_rate"]:
        where = ", ".join(f"{k} {v}" for k, v in list((fam.get("error_phases") or {}).items())[:3])
        problems.append(f"erratic with friction: {fam['variant_count']} shapes (the most common only {round(fam['dominant_share'] * 100)}%), "
                        f"{round(friction * 100)}% of runs had a non-test tool fail ({where}), median {fam['median_steps']} steps")
    if not problems:
        notes = []
        if fam["error_rate"]:
            notes.append(f"{round(fam['error_rate'] * 100)}% of runs hit a tool error, {round(friction * 100)}% outside tests and builds, and recovered")
        if erratic:
            notes.append(f"shapes vary ({fam['variant_count']}), which is normal for open-ended work")
        reasons.append(f"repeats ({n} requests, {sessions} sessions, {days} days) without an unrecovered-failure problem; nothing to engineer"
                       + (f" ({'; '.join(notes)})" if notes else ""))
        return {"verdict": "observe", "reasons": reasons, "recommendation": None}

    reasons.extend(problems)
    dominant = fam.get("typical_path") or (fam["variants"][0]["shape"] if fam["variants"] else [])
    surface = ("the skill itself" if base.startswith("skill:") else "the slash command" if base.startswith("/")
               else "a skill or slash command that fixes the dominant path")
    key = "unrecovered_rate" if unrecovered >= t["unrecovered_rate"] and fam["ended_in_error"] >= t["unrecovered_min"] else "friction_rate"
    return {
        "verdict": "engineer",
        "reasons": reasons,
        "recommendation": {
            "id": f"codify-{name.strip('/').replace(':', '-').replace('/', '-')}",
            "change": f"Codify the '{name}' workflow in {surface}: typical path {' > '.join(dominant) or '(none)'}, "
                      "with an explicit verification step and a stop rule for repeated errors.",
            "surfaces": ["claude-code: skill / slash command / CLAUDE.md", "codex: AGENTS.md / skill", "cursor: rule", "agentctl: task template"],
            "expected": f"{key.replace('_', ' ')} down without more steps per run",
            "metric": {"key": f"{metric_base}.{key}", "direction": "down"},
            "guard": {"key": f"{metric_base}.median_steps", "direction": "not_up"},
        },
    }


def judge(mined: dict[str, Any], effort_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply the gate to every family; summarize what to do overall."""
    verdicts = []
    lookup_share: dict[str | None, float] = {}  # per repo when families are split by repo
    for f in mined.get("families", []):
        if f.get("base_family", f["family"]) in LOOKUP_FAMILIES:
            lookup_share[f.get("repo")] = lookup_share.get(f.get("repo"), 0) + f["share"]
    for fam in mined.get("families", []):
        v = judge_family(fam, effort_evidence, lookup_share=lookup_share.get(fam.get("repo")))
        fam.update(v)
        verdicts.append(v["verdict"])
    counts = {k: verdicts.count(k) for k in ("observe", "cheap_fix", "engineer")}
    if counts["engineer"]:
        headline = f"{counts['engineer']} workflow(s) are worth engineering"
    elif counts["cheap_fix"]:
        headline = "No workflow is worth graph or loop engineering yet; a cheap fix applies"
    else:
        headline = "Graph or loop engineering is not worth applying yet: keep observing"
    mined["gate"] = {"thresholds": THRESHOLDS, "counts": counts, "headline": headline}
    return mined


def read_metric(doc: dict[str, Any], key: str) -> float | None:
    """`families.<name>.<field>` from a workflows document."""
    parts = key.split(".")
    if len(parts) < 3 or parts[0] != "families":
        return None
    name, field_name = ".".join(parts[1:-1]), parts[-1]
    for fam in doc.get("families", []):
        if fam.get("family") == name:
            value = fam.get(field_name)
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _rename(key: str, family: str | None) -> str:
    """`families.<old>.<field>` -> `families.<family>.<field>` (the after side of a codified skill)."""
    parts = key.split(".")
    return f"families.{family}.{parts[-1]}" if family and len(parts) >= 3 and parts[0] == "families" else key


def compare(before: dict[str, Any], after: dict[str, Any], recommendation: dict[str, Any],
            after_family: str | None = None) -> dict[str, Any]:
    """Keep or roll back one recommendation: its metric must move its way and its guard must hold.

    after_family reads the after side from another family, e.g. `skill:<name>` once a codified
    skill anchors the requests that used to land in the mined family.
    """
    gates = []
    for role in ("metric", "guard"):
        spec = recommendation.get(role)
        if not spec:
            continue
        b, a = read_metric(before, spec["key"]), read_metric(after, _rename(spec["key"], after_family))
        if b is None or a is None:
            gates.append({"gate": role, "key": spec["key"], "pass": False, "detail": "missing in before or after"})
            continue
        ok = a < b if spec["direction"] == "down" else a <= b if spec["direction"] == "not_up" else a > b
        gates.append({"gate": role, "key": spec["key"], "before": b, "after": a, "pass": ok})
    parts = recommendation.get("metric", {}).get("key", "").split(".")
    fam = ".".join(parts[1:-1])
    comparable = True
    if fam:
        nb = read_metric(before, f"families.{fam}.requests") or 0
        na = read_metric(after, f"families.{after_family or fam}.requests") or 0
        comparable = na >= THRESHOLDS["min_requests"] and nb >= THRESHOLDS["min_requests"]
        gates.append({"gate": "comparable workload", "before": nb, "after": na, "pass": comparable})
    passed = bool(gates) and all(g["pass"] for g in gates)
    return {"verdict": "keep" if passed else "roll back or collect more runs", "pass": passed, "gates": gates}
