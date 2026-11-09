"""Content-free failure tags shared with agentctl A1 (TS failureTaxonomy)."""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

SCHEMA = "sessiongraph.failure-tags.v1"

WRITE_NEEDS = frozenset({"canModifyRepo", "canWriteFiles", "canRunShell", "write", "shell"})
WRITE_LANES = frozenset({"codex_write", "claude_write", "local_write"})

# Keep in sync with agentctl FailureClassSchema (src/schema/result.ts).
KNOWN_FAILURE_CLASSES = frozenset({
    "none",
    "error",
    "timeout",
    "cancelled",
    "parse_error",
    "transport_error",
    "usage_limit",
    "provider_refusal",
    "not_configured",
    "nonzero_exit",
})


class FailureTag(str, Enum):
    PROVIDER_AUP = "provider_aup"
    AUP_BLOCK_ON_WRITE = "aup_block_on_write"
    DECOMPOSED_TO_LUNA = "decomposed_to_luna"
    STAYED_ON_DAYBREAK = "stayed_on_daybreak"
    EMPTY_SUCCESS = "empty_success"
    MODEL_DRIFT_CANDIDATE = "model_drift_candidate"
    POLICY_REMAP = "policy_remap"
    USAGE_LIMIT = "usage_limit"
    LEGACY_RELABEL = "legacy_relabel"


_SAFEGUARD_RE = re.compile(r"safeguards flagged this session", re.I)
_CYBER_DETAIL_RE = re.compile(r"Details:\s*`\[cyber\]`", re.I)


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _category_of(rec: dict[str, Any]) -> str | None:
    direct = rec.get("api_refusal_category")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    stop = _as_dict(rec.get("stop_details"))
    if stop and isinstance(stop.get("category"), str) and stop["category"].strip():
        return stop["category"].strip()
    msg = _as_dict(rec.get("message"))
    if msg:
        msg_stop = _as_dict(msg.get("stop_details"))
        if msg_stop and isinstance(msg_stop.get("category"), str) and msg_stop["category"].strip():
            return msg_stop["category"].strip()
    return None


def refusal_from_record(rec: dict[str, Any]) -> dict[str, Any] | None:
    if rec.get("subtype") == "model_refusal_no_fallback":
        return {"provider": "claude", "category": _category_of(rec), "via": "structured"}
    if isinstance(rec.get("api_refusal_category"), str) and rec["api_refusal_category"].strip():
        return {"provider": "claude", "category": rec["api_refusal_category"].strip(), "via": "structured"}
    if rec.get("stop_reason") == "refusal" or rec.get("terminal_reason") == "refusal":
        return {"provider": "claude", "category": _category_of(rec), "via": "structured"}
    stop = _as_dict(rec.get("stop_details"))
    if stop and stop.get("type") == "refusal":
        return {"provider": "claude", "category": _category_of(rec), "via": "structured"}
    msg = _as_dict(rec.get("message"))
    if msg:
        msg_stop = _as_dict(msg.get("stop_details"))
        if (msg_stop and msg_stop.get("type") == "refusal") or msg.get("stop_reason") == "refusal":
            return {"provider": "claude", "category": _category_of(rec), "via": "structured"}
    return None


def _prefer(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any] | None:
    if not a:
        return b
    if not b:
        return a
    if a.get("category") and not b.get("category"):
        return a
    if b.get("category") and not a.get("category"):
        return b
    return a


def scan_json_blob(blob: str) -> dict[str, Any] | None:
    """Parse JSON / JSONL for structured refusal signals. Never treats prose as authoritative."""
    trimmed = blob.strip()
    if not trimmed:
        return None
    best: dict[str, Any] | None = None

    def consider(raw: Any) -> None:
        nonlocal best
        if isinstance(raw, list):
            for item in raw:
                consider(item)
            return
        rec = _as_dict(raw)
        if rec:
            best = _prefer(best, refusal_from_record(rec))

    try:
        consider(json.loads(trimmed))
    except json.JSONDecodeError:
        pass
    for line in trimmed.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            consider(json.loads(line))
        except json.JSONDecodeError:
            continue
    if best:
        return best
    # Clipped / invalid-control evidence: fixed structured field phrases only.
    if (
        '"subtype": "model_refusal_no_fallback"' in trimmed
        or '"subtype":"model_refusal_no_fallback"' in trimmed
        or '"stop_reason": "refusal"' in trimmed
        or '"stop_reason":"refusal"' in trimmed
        or '"type": "refusal"' in trimmed
        or '"type":"refusal"' in trimmed
    ):
        cat_m = re.search(r'"api_refusal_category"\s*:\s*"([^"]+)"', trimmed) or re.search(
            r'"category"\s*:\s*"([^"]+)"', trimmed
        )
        return {"provider": "claude", "category": cat_m.group(1) if cat_m else None, "via": "structured"}
    return None


def refusal_from_ask_text(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text:
        return None
    if _SAFEGUARD_RE.search(text) or _CYBER_DETAIL_RE.search(text):
        return {"provider": "claude", "category": "cyber", "via": "text"}
    return None


def _ask_view(record: dict[str, Any]) -> dict[str, Any]:
    ask = _as_dict(record.get("ask")) or {}
    return {
        "agent": ask.get("agent", record.get("agent")),
        "model": ask.get("model", record.get("model")),
        "ok": ask.get("ok", record.get("ok")),
        "failureClass": ask.get("failureClass", record.get("failureClass")),
        "tags": ask.get("tags", record.get("tags")),
        "refusal": ask.get("refusal", record.get("refusal")),
        "evidence": ask.get("evidence"),
        "text": ask.get("text"),
        "steppedDown": ask.get("steppedDown", record.get("steppedDown")),
        "role": ask.get("role", record.get("role")),
        "needs": ask.get("needs", record.get("needs")),
        "policy_remap": ask.get("policy_remap", record.get("policy_remap")),
        "plan_ref": ask.get("plan_ref", record.get("plan_ref")),
    }


def classify_agentctl(record: dict[str, Any]) -> list[str]:
    """Return sorted FailureTag values for an allow-listed agentctl job/result record."""
    view = _ask_view(record)
    tags: set[str] = set()
    existing = view.get("tags")
    if isinstance(existing, list):
        tags.update(str(t) for t in existing if isinstance(t, str))

    fc = view.get("failureClass")
    fc_s = str(fc) if isinstance(fc, str) else None
    refusal = _as_dict(view.get("refusal"))
    legacy = False

    if not refusal and isinstance(view.get("evidence"), str):
        found = scan_json_blob(view["evidence"])
        if found:
            refusal = found
            if fc_s == "usage_limit":
                legacy = True
    if not refusal:
        found = refusal_from_ask_text(view.get("text"))
        if found:
            refusal = found
            if fc_s == "usage_limit":
                legacy = True

    if fc_s == "provider_refusal" or refusal:
        tags.add(FailureTag.PROVIDER_AUP.value)
    if fc_s == "usage_limit" and FailureTag.PROVIDER_AUP.value not in tags:
        tags.add(FailureTag.USAGE_LIMIT.value)
    if fc_s == "usage_limit" and FailureTag.PROVIDER_AUP.value in tags:
        # Relabeled historical misuse: drop usage_limit tag.
        tags.discard(FailureTag.USAGE_LIMIT.value)
        legacy = True
    if legacy:
        tags.add(FailureTag.LEGACY_RELABEL.value)

    if view.get("policy_remap") or record.get("policy_remap"):
        tags.add(FailureTag.POLICY_REMAP.value)

    role = view.get("role") if isinstance(view.get("role"), str) else None
    needs_raw = view.get("needs")
    needs: set[str] = set()
    if isinstance(needs_raw, (list, set, tuple)):
        needs = {str(n) for n in needs_raw}
    agent = view.get("agent") if isinstance(view.get("agent"), str) else None
    write_lane = bool(agent and agent in WRITE_LANES)
    if FailureTag.PROVIDER_AUP.value in tags:
        if write_lane or needs & WRITE_NEEDS or role == "nuance_decompose":
            tags.add(FailureTag.AUP_BLOCK_ON_WRITE.value)

    plan_ref = _as_dict(view.get("plan_ref"))
    model = view.get("model") if isinstance(view.get("model"), str) else None
    ok = view.get("ok") is True
    if role == "nuance_decompose" and plan_ref and agent == "codex_write" and model == "gpt-6-luna" and ok:
        tags.add(FailureTag.DECOMPOSED_TO_LUNA.value)
    if role == "nuance_decompose" and (
        (plan_ref and plan_ref.get("class") == "hot")
        or (model and "daybreak" in model)
    ):
        tags.add(FailureTag.STAYED_ON_DAYBREAK.value)
    if role == "security_whole" and model and "daybreak" in model:
        tags.add(FailureTag.STAYED_ON_DAYBREAK.value)

    # empty_success is computed in agentctl; SessionGraph only preserves the tag if present.
    _ = ok

    if record.get("model_drift_candidate") or "model_drift_candidate" in tags:
        tags.add(FailureTag.MODEL_DRIFT_CANDIDATE.value)

    return sorted(tags)
