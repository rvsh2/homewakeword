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
from homewake.registry import ModelManifest, validate_manifest


class BCResNetRuntimeError(RuntimeError):
    """Raised when the BC-ResNet runtime cannot be initialized."""


@dataclass(frozen=True, slots=True)
class BCResNetRuntimeHandle:
    """Minimal runtime handle tracking the loaded artifact."""

    framework: str
    model_path: str
    artifact_size_bytes: int


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
    """BC-ResNet runtime adapter with validated manifest-driven loading."""

    config: DetectorConfig
    manifest: ModelManifest
    audio_config: AudioInputConfig = field(default_factory=AudioInputConfig)
    _is_open: bool = False
    _frontend: BCResNetStreamingFrontend = field(init=False)
    _last_features: FrontendFeatures | None = field(default=None, init=False)
    _runtime: BCResNetRuntimeHandle | None = field(default=None, init=False)

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

    @property
    def runtime(self) -> BCResNetRuntimeHandle | None:
        return self._runtime

    def _open_runtime(self) -> BCResNetRuntimeHandle:
        validate_manifest(self.manifest, require_artifact=True)
        if self.manifest.model_path is None:
            raise BCResNetRuntimeError("detector manifest did not resolve a model artifact")
        try:
            artifact_bytes = self.manifest.model_path.read_bytes()
        except OSError as exc:
            raise BCResNetRuntimeError(
                f"failed to read model artifact: {self.manifest.model_path}"
            ) from exc
        if not artifact_bytes:
            raise BCResNetRuntimeError(
                f"model artifact is empty: {self.manifest.model_path}"
            )
        return BCResNetRuntimeHandle(
            framework=self.manifest.framework,
            model_path=str(self.manifest.model_path),
            artifact_size_bytes=len(artifact_bytes),
        )

    def open(self) -> None:
        if self._is_open:
            return
        self._runtime = self._open_runtime()
        self._is_open = True

    def close(self) -> None:
        self._runtime = None
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
