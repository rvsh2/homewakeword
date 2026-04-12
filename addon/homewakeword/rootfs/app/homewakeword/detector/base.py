"""Detector-neutral interfaces for HomeWakeWord wake word backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from homewakeword.audio import AudioChunk


@dataclass(frozen=True, slots=True)
class DetectorRuntimeState:
    """State snapshot exposing cooldown and refractory timing."""

    cooldown_remaining_seconds: float = 0.0
    refractory_remaining_seconds: float = 0.0
    armed: bool = True
    vad_suppressed: bool = False


@dataclass(frozen=True, slots=True)
class DetectionDecision:
    """Backend-neutral detector output for one chunk of audio."""

    detected: bool
    score: float
    threshold: float
    label: str
    raw_score: float | None = None
    vad_score: float | None = None
    vad_threshold: float | None = None
    vad_suppressed: bool = False
    state: DetectorRuntimeState = field(default_factory=DetectorRuntimeState)


class WakeWordDetector(Protocol):
    """Contract that all runtime wake word detectors must satisfy."""

    @property
    def backend_name(self) -> str:
        """Returns the detector backend identifier."""

        ...

    def open(self) -> None:
        """Allocates backend resources."""

        ...

    def close(self) -> None:
        """Releases backend resources."""

        ...

    def reset(self) -> None:
        """Clears any buffered or refractory state."""

        ...

    def process(self, chunk: AudioChunk) -> DetectionDecision:
        """Consumes a chunk of PCM audio and returns one decision."""

        ...
