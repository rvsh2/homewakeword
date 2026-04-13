"""Runtime configuration contracts for HomeWakeWord."""

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
    window_seconds: float = 1.0

    @property
    def frame_duration_seconds(self) -> float:
        return self.frame_samples / self.sample_rate_hz

    @property
    def window_samples(self) -> int:
        return int(round(self.sample_rate_hz * self.window_seconds))


@dataclass(frozen=True, slots=True)
class LogMelFrontendConfig:
    """Frozen task-3 frontend knobs for BC-ResNet-oriented streaming."""

    n_fft: int = 512
    win_length: int = 480
    hop_length: int = 160
    n_mels: int = 40
    f_min_hz: float = 20.0
    f_max_hz: float = 7_600.0
    log_floor: float = 1e-6
    context_seconds: float = 1.0

    def window_samples(self, sample_rate_hz: int) -> int:
        return int(round(sample_rate_hz * self.context_seconds))


@dataclass(frozen=True, slots=True)
class DetectorConfig:
    """Detector backend selection and thresholding."""

    backend: str = "bcresnet"
    threshold: float = 0.5
    manifest_path: Path | None = None
    cooldown: CooldownConfig = field(default_factory=CooldownConfig)
    refractory: RefractoryConfig = field(default_factory=RefractoryConfig)
    frontend: LogMelFrontendConfig = field(default_factory=LogMelFrontendConfig)
    enable_speex_noise_suppression: bool = True
    vad: "VADConfig" = field(default_factory=lambda: VADConfig())


@dataclass(frozen=True, slots=True)
class VADConfig:
    """Optional Silero-style VAD gating configuration."""

    enabled: bool = True
    threshold: float = 0.5
    n_threads: int = 1
    model_path: Path | None = None


@dataclass(frozen=True, slots=True)
class CustomModelImportConfig:
    """Filesystem import settings for validated custom model bundles."""

    enabled: bool = False
    directory: Path = Path("/share/homewakeword/models")
    openwakeword_compat_enabled: bool = False
    openwakeword_directory: Path = Path("/share/openwakeword")


@dataclass(frozen=True, slots=True)
class WyomingServerConfig:
    """Protocol-facing network settings."""

    host: str = "127.0.0.1"
    port: int = 10_700


@dataclass(frozen=True, slots=True)
class HomeWakeWordConfig:
    """Top-level application configuration passed between layers."""

    audio: AudioInputConfig = field(default_factory=AudioInputConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    custom_models: CustomModelImportConfig = field(
        default_factory=CustomModelImportConfig
    )
    server: WyomingServerConfig = field(default_factory=WyomingServerConfig)
