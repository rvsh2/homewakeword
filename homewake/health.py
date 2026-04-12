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


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """Aggregate health snapshot for the HomeWake runtime."""

    overall: HealthStatus
    components: tuple[ComponentHealth, ...]
