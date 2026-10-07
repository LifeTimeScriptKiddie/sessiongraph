"""Human-readable rationale for a suggested workflow."""

"""Deterministic session → suggested workflow compiler (suggest-map-v1)."""

from typing import Any

from .rules import MAPPING_VERSION, TopologyRule
from .select import _falsification, held_back


def control_plane_recommendations(plan: dict[str, Any]) -> list[str]:
    """Advise-only mapping of the suggested topology onto graph-engineering primitives.

    SessionGraph does not govern execution. These lines recommend what an external
    supervisor (agentctl, harness, human) should make explicit: nodes, edges, state,
    routes, joins, and exit rules.
    """
    if plan.get("skipped"):
        return [
            "No trusted findings drove a topology change; keep observing traces before "
            "formalizing edges, joins, or exit rules.",
        ]

    primary: TopologyRule = plan["primary_rule"]
    guards: list[TopologyRule] = list(plan.get("guard_rules") or [])
    rules = [primary, *guards]
    nodes = " → ".join(primary.markdown_nodes) if primary.markdown_nodes else "Start → Do → Verify → Done"

    needs_handoff = primary.requires_handoff or any(g.requires_handoff for g in guards)
    needs_classify = primary.requires_classify or any(g.requires_classify for g in guards)
    needs_retry = primary.requires_retry_budget or any(g.requires_retry_budget for g in guards)
    needs_checkpoint = primary.requires_checkpoint or any(g.requires_checkpoint for g in guards)
    needs_fallback = primary.requires_fallback or any(g.requires_fallback for g in guards)
    needs_escalation = primary.requires_escalation_gate or any(g.requires_escalation_gate for g in guards)
    needs_preflight = primary.requires_preflight or any(g.requires_preflight for g in guards)

    lines = [
        f"**Nodes** — Treat these as the smallest meaningful work units (not one giant agent): `{nodes}`.",
        f"**Edges** — Make the next legal transition explicit after each unit: {primary.topology_move}.",
    ]

    state_bits = [
        "Keep durable task state outside chat (goal, artifacts, evidence, retry count, next eligible actions).",
    ]
    if needs_handoff:
        state_bits.append(
            "On stop, require a terminal handoff contract (`state`, `blocker`, `nextSafeAction`).",
        )
    if needs_checkpoint:
        state_bits.append("Checkpoint before strategy forks so resume does not redo completed work.")
    if primary.code == "pipeline_contract":
        state_bits.append(
            "Producer may repair artifacts; keep fixture/verifier/required checks fixed (read/write contract).",
        )
    lines.append("**State** — " + " ".join(state_bits))

    route_bits = [
        "Model may classify; the supervisor should pick the consequence (retry, escalate, stop, continue).",
    ]
    if needs_preflight:
        route_bits.append("Front-load a preflight checklist before tool work.")
    if needs_classify:
        route_bits.append("Do not retry until failure class is recorded.")
    if needs_escalation:
        route_bits.append("Route high-impact or deferred escalation through an explicit EscalationGate.")
    lines.append("**Routes** — " + " ".join(route_bits))

    if needs_fallback:
        join = (
            "Parallel or timed-out branches need a join: required outputs, field ownership, "
            "and whether partial results may proceed; preserve completed branches on fallback."
        )
    else:
        join = (
            "Prefer one worker per shared artifact unless branches are independent; "
            "if you fan out later, define merge ownership before starting the second worker."
        )
    lines.append(f"**Joins** — {join}")

    exits = [
        "Name terminal conditions: verified success, failed validation, human approval, timeout/budget, max retries, unsafe action.",
    ]
    if needs_retry:
        exits.append("Cap identical retries (RetryBudget) and require a changed hypothesis/input.")
    if needs_handoff:
        exits.append("Dead-end stops must emit handoff fields, not silent silence.")
    if any(r.code == "agent_timeout" for r in rules):
        exits.append("Timeout is an exit/fallback edge, not an unbounded wait.")
    lines.append("**Exit rules** — " + " ".join(exits))
    lines.append(
        "**Operator boundary** — SessionGraph recommends only; agentctl/harness/human apply, "
        "park on quota, approve, or cancel."
    )
    return lines


def _because(codes: set[str], *wanted: str) -> str:
    hit = [c for c in wanted if c in codes]
    if not hit:
        return ""
    return " because " + ", ".join(f"`{c}`" for c in hit)


def harness_layer_recommendations(plan: dict[str, Any]) -> list[str]:
    """Advise-only mapping onto the seven-layer long-run harness (beamnxw / Opus article).

    SessionGraph does not run the harness. These lines recommend what agentctl, the
    cockpit, or a human should set up before a long model run so work leaves openable
    results, inspectable evidence, and resumable progress.
    """
    if plan.get("skipped"):
        return [
            "No trusted findings drove a topology change; use the seven-layer checklist in "
            "`agentctl/dev/docs/LONG-RUN-HARNESS.md` before the next long run.",
        ]

    primary: TopologyRule = plan["primary_rule"]
    guards: list[TopologyRule] = list(plan.get("guard_rules") or [])
    codes = {primary.code, *(g.code for g in guards)}
    needs_escalation = primary.requires_escalation_gate or any(g.requires_escalation_gate for g in guards)

    l2 = (
        "**L2 Procedure** — Name an observable saved artifact per step; keep "
        "`delegate --dry-route` / `orchestrate --dry-plan` (prep) separate from `--run` / `--approve`."
    )
    if needs_escalation or "escalation_deferred" in codes:
        l2 += _because(codes, "escalation_deferred") or " because escalation must stay gated"

    l3 = (
        "**L3 Source access** — Open only the lanes/tools the step needs; on failure preserve "
        "identifier + `failureClass` before any retry."
    )
    l3 += _because(codes, "errors", "loop_telemetry_gap")

    l4 = (
        "**L4 Execution** — Destructive or outward writes need an explicit `--approve`; "
        "treat timeout/quota as park-or-fallback edges (job cancel / quota wait), not blind restarts."
    )
    l4 += _because(codes, "agent_timeout", "escalation_deferred")

    l5 = (
        "**L5 Evidence reviewer** — After the main pass, run a separate read-only review that "
        "returns claim→source findings against saved files/outputs (not the chat); main corrects."
    )
    l5 += _because(codes, "pipeline_contract", "dead_end")

    l6 = (
        "**L6 Effort** — Main writing on sonnet (or codex with ordinary effort); deep review on "
        "opus (or codex high/max). `effort` is a codex/daybreak knob only — do not invent a Claude effort flag."
    )
    l6 += _because(codes, "loop_bottleneck")

    l7 = (
        "**L7 Completion proof** — Done means saved deliverables + verification artifacts "
        "(not a chat summary); update the checkpoint/handoff so the next session can resume."
    )
    l7 += _because(codes, "dead_end", "pipeline_contract")

    return [
        "**L1 Workspace facts** — Keep standing facts in `AGENTS.md` / accepted memories; "
        "put goal, state, blockers, and nextAction in `agentctl memory checkpoint` (task-ephemeral).",
        l2,
        l3,
        l4,
        l5,
        l6,
        l7,
        "**Operator boundary** — SessionGraph recommends only; agentctl/harness/human apply, "
        "park on quota, approve, or cancel.",
    ]


def render_rationale(plan: dict[str, Any], analysis: dict[str, Any]) -> str:
    lines = [
        "# Suggest-workflow rationale",
        "",
        f"- Mapping: `{MAPPING_VERSION}`",
        f"- Primary finding: `{plan.get('primary_finding') or 'healthy'}`",
        f"- Findings used: {', '.join(f'`{c}`' for c in plan.get('findings_used') or []) or '(none)'}",
        f"- Held back (unverified heuristic checks): "
        f"{', '.join(f'`{c}`' for c in held_back(list(analysis.get('findings') or []))) or '(none)'}",
        f"- Session workflow_health: **{(analysis.get('metrics') or {}).get('workflow_health', '?')}/100**",
        "",
        "## Applied rules",
        "",
    ]
    primary: TopologyRule = plan["primary_rule"]
    lines.extend([
        f"### Spine: `{primary.code}`",
        "",
        f"- Topology move: {primary.topology_move}",
        f"- Expected metric movement: {primary.expected_metric}",
        "",
    ])
    for rule in plan.get("guard_rules") or []:
        lines.extend([
            f"### Guard: `{rule.code}`",
            "",
            f"- Topology move: {rule.topology_move}",
            f"- Expected metric movement: {rule.expected_metric}",
            "",
        ])
    if plan.get("skipped"):
        lines.extend([
            "## Skipped",
            "",
            "No findings from trusted checks and `--include-healthy` was not set. No topology change suggested.",
            "",
        ])

    lines.extend([
        "## Control-plane recommendations (advise only)",
        "",
        "Framed as graph engineering primitives (nodes, edges, state, routes, joins, exits). "
        "SessionGraph does **not** govern execution; it recommends what to make explicit.",
        "",
    ])
    for item in control_plane_recommendations(plan):
        lines.append(f"- {item}")
    lines.append("")

    lines.extend([
        "## Harness layers (advise only)",
        "",
        "Framed as the seven-layer long-run harness (workspace facts → procedure → sources → "
        "execution → evidence reviewer → effort → completion proof). "
        "SessionGraph does **not** run this harness; it recommends what to set up before a long model job.",
        "",
    ])
    for item in harness_layer_recommendations(plan):
        lines.append(f"- {item}")
    lines.append("")

    lines.extend([
        "## Experiment",
        "",
        "Re-run a comparable task with this workflow applied and verify the target metrics.",
        _falsification(plan),
        "Rollback: discard the artifact directory and restore the prior workflow.",
        "",
    ])
    return "\n".join(lines)
