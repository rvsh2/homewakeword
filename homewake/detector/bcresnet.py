"""BC-ResNet frontend helpers behind the neutral detector contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from homewake.audio import (
    AudioChunk,
    FrontendFeatures,
    RollingAudioWindow,
    frontend_features_from_window,
)
from homewake.config import AudioInputConfig, DetectorConfig
from homewake.detector.base import DetectionDecision, DetectorRuntimeState
from homewake.registry import ModelManifest


@dataclass(slots=True)
class BCResNetStreamingFrontend:
    """Consumes 80 ms PCM chunks and emits deterministic task-3 diagnostics."""

    audio_config: AudioInputConfig = field(default_factory=AudioInputConfig)
    detector_config: DetectorConfig = field(default_factory=DetectorConfig)
    _window: RollingAudioWindow = field(init=False)

    def __post_init__(self) -> None:
        self._window = RollingAudioWindow(self.audio_config)

    def reset(self) -> None:
        self._window.reset()

    def process_chunk(self, chunk: AudioChunk) -> FrontendFeatures:
        window = self._window.append(chunk)
        return frontend_features_from_window(
            window=window,
            sample_rate_hz=self.audio_config.sample_rate_hz,
            frontend_config=self.detector_config.frontend,
        )


@dataclass(slots=True)
class BCResNetDetector:
    """Placeholder BC-ResNet runtime adapter with task-3 frontend state only."""

    config: DetectorConfig
    manifest: ModelManifest
    audio_config: AudioInputConfig = field(default_factory=AudioInputConfig)
    _is_open: bool = False
    _frontend: BCResNetStreamingFrontend = field(init=False)
    _last_features: FrontendFeatures | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._frontend = BCResNetStreamingFrontend(
            audio_config=self.audio_config,
            detector_config=self.config,
        )

    @property
    def backend_name(self) -> str:
        return 'bcresnet'

    @property
    def last_features(self) -> FrontendFeatures | None:
        return self._last_features

    def open(self) -> None:
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def reset(self) -> None:
        self._frontend.reset()
        self._last_features = None

    def process(self, chunk: AudioChunk) -> DetectionDecision:
        """Update frontend state and return a deterministic non-detection result."""

        self._last_features = self._frontend.process_chunk(chunk)
        return DetectionDecision(
            detected=False,
            score=round(self._last_features.chunk_rms, 6),
            threshold=self.config.threshold,
            label=self.manifest.wake_word,
            state=DetectorRuntimeState(),
        )
