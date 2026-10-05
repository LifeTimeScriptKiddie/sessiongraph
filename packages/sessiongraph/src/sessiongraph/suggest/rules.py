"""Finding codes → topology rules (suggest-map-v1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MAPPING_VERSION = "suggest-map-v1"
SCHEMA_VERSION = 1

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

# Spine ownership: lower rank wins when severities tie.
SPINE_PRIORITY = {
    "loop_incomplete": -3,
    "loop_telemetry_gap": -2,
    "pipeline_contract": -1,
    "empty_memory_catalog": -1,
    "dead_end": 0,
    "errors": 1,
    "alternating_loop": 2,
    "repeated_action": 3,
    "agent_timeout": 4,
    "loop_bottleneck": 5,
    "user_correction": 6,
    "escalation_deferred": 7,
    "dangling_edges": 8,
}


@dataclass(frozen=True, slots=True)
class TopologyRule:
    code: str
    role: str  # "spine" or "guard"
    topology_move: str
    markdown_nodes: tuple[str, ...]
    markdown_guards: tuple[str, ...]
    expected_metric: str
    claude_phases: tuple[str, ...]
    agentctl_budgets: dict[str, int] = field(default_factory=dict)
    agentctl_headings: tuple[str, ...] = ()
    requires_handoff: bool = False
    requires_classify: bool = False
    requires_preflight: bool = False
    requires_checkpoint: bool = False
    requires_fallback: bool = False
    requires_fast_pass: bool = False
    requires_escalation_gate: bool = False
    requires_retry_budget: bool = False


MAPPING: dict[str, TopologyRule] = {
    "loop_incomplete": TopologyRule(
        code="loop_incomplete", role="guard",
        topology_move="Collect a terminal record before evaluating workflow improvement",
        markdown_nodes=("Start", "CaptureTerminalRecord", "Verify", "Done"),
        markdown_guards=("In-progress or partial capture is not a completed run",),
        expected_metric="loop_terminal_recorded becomes true; verify missing evidence rather than hiding failures",
        claude_phases=("capture-terminal-record",),
        agentctl_headings=("## Capture coverage",),
        requires_preflight=True,
    ),
    "loop_telemetry_gap": TopologyRule(
        code="loop_telemetry_gap", role="guard",
        topology_move="Repair stage failure telemetry before selecting retry or fallback policy",
        markdown_nodes=("Start", "RepairFailureTelemetry", "Verify", "Done"),
        markdown_guards=("Record failureClass for both generator and evaluator; do not infer timeouts from duration",),
        expected_metric="loop_failure_classification_missing reaches zero on fresh replays",
        claude_phases=("repair-failure-telemetry",),
        agentctl_headings=("## Capture coverage",),
        requires_preflight=True,
    ),
    "pipeline_contract": TopologyRule(
        code="pipeline_contract",
        role="spine",
        topology_move="Fix the producer and rerun the unchanged external verification contract",
        markdown_nodes=("Start", "CheckContract", "RepairProducer", "VerifyArtifacts", "Handoff", "Done"),
        markdown_guards=("Keep fixture, verifier and required checks fixed", "Do not replace failed checks with process-success claims"),
        expected_metric="pipeline_checks_required unchanged; pipeline_checks_failed, pipeline_checks_missing and pipeline_checks_unproven reach zero; pipeline_success becomes 1",
        claude_phases=("check-contract", "repair-producer", "verify-artifacts"),
        agentctl_headings=("## Verification contract", "## Check evidence"),
        requires_handoff=True,
    ),
    "repeated_action": TopologyRule(
        code="repeated_action",
        role="spine",
        topology_move="Cap retries; force strategy change after 2 identical attempts",
        markdown_nodes=("Start", "Act", "RetryBudget(2)", "Verify", "Done"),
        markdown_guards=("RetryBudget(2) on repeated signatures", "edge must_change_input after identical attempt"),
        expected_metric="fewer repeated_action findings; tool_calls for same signature capped",
        claude_phases=("bounded-retry", "retry-with-new-hypothesis"),
        agentctl_budgets={"repeatedFailureRounds": 2, "noProgressRounds": 2},
        requires_retry_budget=True,
    ),
    "alternating_loop": TopologyRule(
        code="alternating_loop",
        role="spine",
        topology_move="Checkpoint / strategy fork after second A-B cycle",
        markdown_nodes=("Start", "Act", "Summarize", "PickStrategy", "Verify", "Done"),
        markdown_guards=("After cycle 2 → Summarize → PickStrategy (diamond)",),
        expected_metric="no alternating_loop; strategy choice before further tools",
        claude_phases=("checkpoint", "strategy-fork"),
        requires_checkpoint=True,
    ),
    "errors": TopologyRule(
        code="errors",
        role="spine",
        topology_move="Classify failure before retry; record whether next action changes condition",
        markdown_nodes=("Start", "ClassifyFailure", "Act", "Verify", "Done"),
        markdown_guards=("ClassifyFailure before any Retry",),
        expected_metric="fewer unrecovered errors; no blind retries",
        claude_phases=("classify-then-act", "bounded-retry"),
        requires_classify=True,
    ),
    "dead_end": TopologyRule(
        code="dead_end",
        role="spine",
        topology_move="Require terminal handoff artifact",
        markdown_nodes=("Start", "Act", "Verify", "Handoff", "Done"),
        markdown_guards=("Terminal Handoff schema: state, blocker, nextSafeAction",),
        expected_metric="no dead_end; every stop produces handoff fields",
        claude_phases=("act", "handoff"),
        agentctl_headings=("## Handoff state", "## Blocker", "## Next safe action"),
        requires_handoff=True,
    ),
    "user_correction": TopologyRule(
        code="user_correction",
        role="guard",
        topology_move="Preflight checklist / project instruction injection",
        markdown_nodes=("PreflightChecklist",),
        markdown_guards=("Front node PreflightChecklist from finding evidence IDs only",),
        expected_metric="fewer user_correction events on comparable tasks",
        claude_phases=("preflight",),
        requires_preflight=True,
    ),
    "agent_timeout": TopologyRule(
        code="agent_timeout",
        role="spine",
        topology_move="Bounded fallback edge; preserve completed branches",
        markdown_nodes=("Start", "ParallelWork", "FallbackAdapter", "Verify", "Done"),
        markdown_guards=("timeout → fallback_adapter", "preserve completed branches"),
        expected_metric="no agent_timeout; wall clock on slow stage tighter",
        claude_phases=("parallel-work", "fallback"),
        agentctl_budgets={"wallClockSeconds": 300},
        requires_fallback=True,
    ),
    "loop_bottleneck": TopologyRule(
        code="loop_bottleneck",
        role="spine",
        topology_move="Faster first-pass + conditional escalate",
        markdown_nodes=("Start", "FastPass", "Escalate?", "Verify", "Done"),
        markdown_guards=("FastPass → optional Escalate",),
        expected_metric="lower loop_duration_ms without more retries",
        claude_phases=("fast-pass", "escalate"),
        requires_fast_pass=True,
    ),
    "dangling_edges": TopologyRule(
        code="dangling_edges",
        role="guard",
        topology_move="Don't invent lineage; require complete branch load",
        markdown_nodes=(),
        markdown_guards=("Warning: incomplete graph; skip deep lineage", "analyze complete branch only"),
        expected_metric="dangling_edges cleared by loading complete branch",
        claude_phases=(),
    ),
    "escalation_deferred": TopologyRule(
        code="escalation_deferred",
        role="guard",
        topology_move="Explicit escalation stage",
        markdown_nodes=("EscalationGate",),
        markdown_guards=("Node EscalationGate gated on prior failure",),
        expected_metric="escalation is explicit and gated, not silent-deferred",
        claude_phases=("browser-escalation",),
        requires_escalation_gate=True,
    ),
    "high_abstain_rate": TopologyRule(
        code="high_abstain_rate",
        role="spine",
        topology_move="Improve retrieval coverage before adding more thin clients",
        markdown_nodes=("Start", "SeedAcceptedMemories", "TuneEvidenceGates", "VerifyTurnRate", "Done"),
        markdown_guards=("Do not disable abstain policy to inflate answer rate",),
        expected_metric="turn_abstain_rate decreases on comparable queries without policy regression",
        claude_phases=("seed-memory", "tune-retrieval"),
        agentctl_headings=("## Memory plane topology", "## Evidence coverage"),
    ),
    "review_backlog": TopologyRule(
        code="review_backlog",
        role="spine",
        topology_move="Operator review cadence for proposed team memories",
        markdown_nodes=("Start", "ReviewQueue", "AcceptOrCorrect", "VerifyDepth", "Done"),
        markdown_guards=("Human approve before commit",),
        expected_metric="proposed_pending_total stays below team threshold",
        claude_phases=("memory-review", "accept"),
        agentctl_headings=("## Review cadence", "## Proposed queue"),
    ),
    "empty_memory_catalog": TopologyRule(
        code="empty_memory_catalog",
        role="spine",
        topology_move="Bootstrap accepted catalog before scaling gateway clients",
        markdown_nodes=("Start", "BootstrapMemories", "AcceptBaseline", "VerifyTurns", "Done"),
        markdown_guards=("No worker writes without operator accept path",),
        expected_metric="accepted_total > 0 with stable turn traffic",
        claude_phases=("bootstrap-memory", "accept-baseline"),
        agentctl_headings=("## Bootstrap memories", "## Accept path"),
    ),
    "postgres_migration_candidate": TopologyRule(
        code="postgres_migration_candidate",
        role="guard",
        topology_move="Plan Postgres cutover on the memory VM",
        markdown_nodes=("Start", "CapacityReview", "MigrateStore", "VerifyHA", "Done"),
        markdown_guards=("Single writer on VM until cutover verified",),
        expected_metric="postgres backend with migrations applied; no SQLite split-brain",
        claude_phases=("capacity-review", "postgres-migrate"),
        agentctl_headings=("## Backend topology", "## Migration plan"),
    ),
    "no_gateway_traffic": TopologyRule(
        code="no_gateway_traffic",
        role="guard",
        topology_move="Verify clients hit AGENTCTL_GATEWAY_URL and audit logging",
        markdown_nodes=("Start", "VerifyGatewayUrl", "SmokeTurn", "VerifyAudit", "Done"),
        markdown_guards=("SSH memory remote is not the team Q&A path",),
        expected_metric="audit_event_count > 0 in nightly export window",
        claude_phases=("verify-gateway", "smoke-turn"),
        agentctl_headings=("## Client routing", "## Audit path"),
    ),
}

HEALTHY_RULE = TopologyRule(
    code="healthy",
    role="spine",
    topology_move="Healthy linear template",
    markdown_nodes=("Start", "Do", "Verify", "Done"),
    markdown_guards=(),
    expected_metric="maintain workflow_health; no new findings",
    claude_phases=("do", "verify"),
)


# Heuristic checks that human labels have verified (docs/VERIFY.md). Empty until one passes.
VERIFIED_HEURISTICS: frozenset[str] = frozenset()
