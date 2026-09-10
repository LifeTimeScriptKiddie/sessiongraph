from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Event:
    id: str
    parent_id: str | None
    kind: str
    role: str | None = None
    name: str | None = None
    timestamp: str | int | float | None = None
    text: str = ""
    signature: str = ""
    is_error: bool = False
    usage: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public(self, include_content: bool = False) -> dict[str, Any]:
        # Scalar fields are immutable; only the mutable maps need copying.
        # Avoid walking every dataclass field and preparing omitted content.
        value = {
            "id": self.id, "parent_id": self.parent_id, "kind": self.kind,
            "role": self.role, "name": self.name, "timestamp": deepcopy(self.timestamp),
            "signature": self.signature, "is_error": self.is_error,
            "usage": self.usage.copy(), "metadata": deepcopy(self.metadata),
        }
        if include_content:
            value["text"] = self.text
        return value


@dataclass(slots=True)
class Session:
    id: str
    source: str
    format: str
    events: list[Event]
    metadata: dict[str, Any] = field(default_factory=dict)
