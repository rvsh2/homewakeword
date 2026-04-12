"""Runtime health structures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    """Health states for runtime components."""

    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """Health snapshot for one runtime component."""

    name: str
    status: HealthStatus
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """Aggregate health snapshot for the HomeWake runtime."""

    overall: HealthStatus
    components: tuple[ComponentHealth, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "overall": self.overall.value,
            "components": [component.as_dict() for component in self.components],
        }
