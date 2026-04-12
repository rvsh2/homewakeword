"""Runtime health structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from homewakeword.registry import ModelInventoryRecord


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
    """Aggregate health snapshot for the HomeWakeWord runtime."""

    overall: HealthStatus
    components: tuple[ComponentHealth, ...]
    inventory: tuple[ModelInventoryRecord, ...] = ()
    config: dict[str, object] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)

    def as_dict(self, *, include_details: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "overall": self.overall.value,
            "components": [component.as_dict() for component in self.components],
        }
        if self.inventory:
            serializer = "as_report_dict" if include_details else "as_public_dict"
            payload["inventory"] = [
                getattr(record, serializer)() for record in self.inventory
            ]
        if self.config:
            payload["config"] = self.config
        if include_details and self.diagnostics:
            payload["diagnostics"] = self.diagnostics
        return payload


def _combine_status(*statuses: HealthStatus) -> HealthStatus:
    order = {
        HealthStatus.READY: 0,
        HealthStatus.DEGRADED: 1,
        HealthStatus.FAILED: 2,
    }
    return max(statuses, key=order.__getitem__)


def build_runtime_health(
    *,
    running: bool,
    loaded_wake_words: tuple[str, ...],
    inventory: tuple[ModelInventoryRecord, ...] = (),
    config: dict[str, object] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> RuntimeHealth:
    """Create a compact, safe runtime health payload from neutral structures."""

    if not loaded_wake_words or not inventory:
        server_status = HealthStatus.FAILED
        detector_status = HealthStatus.FAILED
        provenance_status = HealthStatus.FAILED
    else:
        server_status = HealthStatus.READY if running else HealthStatus.DEGRADED
        detector_status = HealthStatus.READY if running else HealthStatus.DEGRADED
        provenance_issue = any(
            record.mode == "detector"
            and (
                record.provenance_status != "approved" or record.hash_verified is False
            )
            for record in inventory
        )
        provenance_status = (
            HealthStatus.DEGRADED if provenance_issue else HealthStatus.READY
        )

    overall = _combine_status(server_status, detector_status, provenance_status)
    return RuntimeHealth(
        overall=overall,
        components=(
            ComponentHealth(
                name="server",
                status=server_status,
                detail="running" if running else "stopped",
            ),
            ComponentHealth(
                name="detector",
                status=detector_status,
                detail=f"loaded_wake_words={len(loaded_wake_words)}",
            ),
            ComponentHealth(
                name="provenance",
                status=provenance_status,
                detail=f"tracked_models={len(inventory)}",
            ),
        ),
        inventory=inventory,
        config={} if config is None else config,
        diagnostics={} if diagnostics is None else diagnostics,
    )
