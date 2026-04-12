"""Runtime configuration contracts for HomeWake."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CooldownConfig:
    """Controls suppression after a successful detection."""

    activation_seconds: float = 1.5


@dataclass(frozen=True, slots=True)
class RefractoryConfig:
    """Controls suppression while scores remain hot after a trigger."""

    hold_seconds: float = 0.5
    reset_threshold: float = 0.2


@dataclass(frozen=True, slots=True)
class AudioInputConfig:
    """Defines expected PCM audio input characteristics."""

    sample_rate_hz: int = 16_000
    sample_width_bytes: int = 2
    channels: int = 1
    frame_samples: int = 1_280


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Detector backend selection and thresholding."""

    backend: str = "bcresnet"
    threshold: float = 0.5
    manifest_path: Path | None = None
    cooldown: CooldownConfig = field(default_factory=CooldownConfig)
    refractory: RefractoryConfig = field(default_factory=RefractoryConfig)


@dataclass(frozen=True, slots=True)
class WyomingServerConfig:
    """Protocol-facing network settings."""

    host: str = "127.0.0.1"
    port: int = 10_700


@dataclass(frozen=True, slots=True)
class HomeWakeConfig:
    """Top-level application configuration passed between layers."""

    audio: AudioInputConfig = field(default_factory=AudioInputConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    server: WyomingServerConfig = field(default_factory=WyomingServerConfig)
