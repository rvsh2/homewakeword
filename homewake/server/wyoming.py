"""Wyoming protocol-facing runtime shell.

This module deliberately depends on detector interfaces rather than any concrete
BC-ResNet implementation details so protocol code stays swappable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Self

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


@dataclass(frozen=True, slots=True)
class WyomingWakeWord:
    """Protocol-facing wake word metadata reported by the service boundary."""

    name: str


@dataclass(frozen=True, slots=True)
class WyomingServiceDescription:
    """Static service metadata for Wyoming-style discovery/describe flows."""

    uri: str
    wake_words: tuple[WyomingWakeWord, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "wake_words": [wake_word.name for wake_word in self.wake_words],
        }


@dataclass(frozen=True, slots=True)
class WyomingDetectionEvent:
    """Protocol-level wake detection payload emitted by the Wyoming layer."""

    type: str
    wake_word: str
    service_uri: str
    occurred_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "type": self.type,
            "wake_word": self.wake_word,
            "service_uri": self.service_uri,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass(slots=True)
class WyomingServer:
    """Thin protocol-facing shell for Wyoming-style startup and event emission."""

    config: WyomingServerConfig
    runtime: WyomingRuntime
    loaded_wake_words: tuple[str, ...] = ()
    _running: bool = False

    @classmethod
    def from_runtime(
        cls, runtime: WyomingRuntime, *, loaded_wake_words: tuple[str, ...] = ()
    ) -> Self:
        return cls(
            config=runtime.config.server,
            runtime=runtime,
            loaded_wake_words=loaded_wake_words,
        )

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uri(self) -> str:
        return f"tcp://{self.config.host}:{self.config.port}"

    def start(self) -> None:
        self.runtime.detector.open()
        self._running = True

    def stop(self) -> None:
        try:
            self.runtime.detector.close()
        finally:
            self._running = False

    def describe(self) -> WyomingServiceDescription:
        return WyomingServiceDescription(
            uri=self.uri,
            wake_words=tuple(
                WyomingWakeWord(name=wake_word) for wake_word in self.loaded_wake_words
            ),
        )

    def handle_audio_chunk(self, chunk: AudioChunk) -> WyomingDetectionEvent | None:
        event = self.runtime.handle_audio_chunk(chunk)
        if event.type is not DetectionEventType.DETECTION:
            return None
        return WyomingDetectionEvent(
            type=event.type.value,
            wake_word=event.label,
            service_uri=self.uri,
            occurred_at=event.occurred_at,
        )

    def health(self) -> RuntimeHealth:
        if self._running and self.loaded_wake_words:
            server_status = HealthStatus.READY
            detector_status = HealthStatus.READY
            overall = HealthStatus.READY
        elif self.loaded_wake_words:
            server_status = HealthStatus.DEGRADED
            detector_status = HealthStatus.DEGRADED
            overall = HealthStatus.DEGRADED
        else:
            server_status = HealthStatus.FAILED
            detector_status = HealthStatus.FAILED
            overall = HealthStatus.FAILED

        return RuntimeHealth(
            overall=overall,
            components=(
                ComponentHealth(name="server", status=server_status),
                ComponentHealth(name="detector", status=detector_status),
            ),
        )
