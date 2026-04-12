"""Wyoming protocol-facing runtime shell.

This module deliberately depends on detector interfaces rather than any concrete
BC-ResNet implementation details so protocol code stays swappable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from homewake.audio import AudioChunk
from homewake.config import HomeWakeConfig, WyomingServerConfig
from homewake.detector.base import WakeWordDetector
from homewake.events import DetectionEvent, DetectionEventType
from homewake.health import ComponentHealth, HealthStatus, RuntimeHealth


@dataclass(slots=True)
class WyomingRuntime:
    """Binds protocol configuration to a detector contract."""

    config: HomeWakeConfig
    detector: WakeWordDetector

    def handle_audio_chunk(self, chunk: AudioChunk) -> DetectionEvent:
        """Translate one detector decision into a structured runtime event."""

        decision = self.detector.process(chunk)
        if decision.detected:
            event_type = DetectionEventType.DETECTION
        elif decision.state.cooldown_remaining_seconds > 0:
            event_type = DetectionEventType.SUPPRESSED_COOLDOWN
        elif decision.state.refractory_remaining_seconds > 0:
            event_type = DetectionEventType.SUPPRESSED_REFRACTORY
        else:
            event_type = DetectionEventType.SCORED

        return DetectionEvent(
            type=event_type,
            detector_backend=self.detector.backend_name,
            occurred_at=datetime.now(tz=timezone.utc),
            decision=decision,
        )

    def health(self) -> RuntimeHealth:
        """Expose protocol and detector health without reaching into internals."""

        return RuntimeHealth(
            overall=HealthStatus.READY,
            components=(
                ComponentHealth(name="server", status=HealthStatus.READY),
                ComponentHealth(name="detector", status=HealthStatus.READY),
            ),
        )


@dataclass(slots=True)
class WyomingServer:
    """Thin protocol-facing shell for future Wyoming transport integration."""

    config: WyomingServerConfig
    runtime: WyomingRuntime

    @classmethod
    def from_runtime(cls, runtime: WyomingRuntime) -> "WyomingServer":
        return cls(config=runtime.config.server, runtime=runtime)
