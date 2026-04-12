"""Structured detection events shared across runtime layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from homewakeword.detector.base import DetectionDecision


class DetectionEventType(StrEnum):
    """Event categories emitted by the runtime."""

    DETECTION = "detection"
    SUPPRESSED_COOLDOWN = "suppressed_cooldown"
    SUPPRESSED_REFRACTORY = "suppressed_refractory"
    SCORED = "scored"


@dataclass(frozen=True, slots=True)
class DetectionEvent:
    """Structured event envelope for detector decisions."""

    type: DetectionEventType
    detector_backend: str
    occurred_at: datetime
    decision: DetectionDecision

    @property
    def label(self) -> str:
        return self.decision.label
