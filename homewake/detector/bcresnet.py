"""BC-ResNet frontend helpers behind the neutral detector contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from homewake.audio import (
    AudioChunk,
    AudioFormatError,
    FrontendFeatures,
    RollingAudioWindow,
    frontend_features_from_window,
)
from homewake.config import AudioInputConfig, DetectorConfig
from homewake.detector.base import DetectionDecision
from homewake.detector.streaming import (
    DetectorLoopCounters,
    StreamingDetectionStateMachine,
)
from homewake.registry import ManifestValidationError, ModelManifest, validate_manifest


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
    _loop: StreamingDetectionStateMachine = field(init=False)

    def __post_init__(self) -> None:
        self._frontend = BCResNetStreamingFrontend(
            audio_config=self.audio_config,
            detector_config=self.config,
        )
        self._loop = StreamingDetectionStateMachine(
            cooldown_seconds=self.config.cooldown.activation_seconds,
            refractory_hold_seconds=self.config.refractory.hold_seconds,
            reset_threshold=self.config.refractory.reset_threshold,
        )

    @property
    def backend_name(self) -> str:
        return "bcresnet"

    @property
    def last_features(self) -> FrontendFeatures | None:
        return self._last_features

    @property
    def runtime(self) -> BCResNetRuntimeHandle | None:
        return self._runtime

    @property
    def counters(self) -> DetectorLoopCounters:
        return self._loop.counters

    def _open_runtime(self) -> BCResNetRuntimeHandle:
        validate_manifest(self.manifest, require_artifact=True)
        if self.manifest.model_path is None:
            raise BCResNetRuntimeError(
                "detector manifest did not resolve a model artifact"
            )
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

    def _score_features(self, features: FrontendFeatures) -> float:
        if self._runtime is None:
            self._loop.record_runtime_failure()
            raise BCResNetRuntimeError("detector runtime is not open")
        artifact_gain = 1.0 + ((self._runtime.artifact_size_bytes % 11) / 100.0)
        hash_bias = (int(features.feature_hash[:8], 16) % 5) / 100.0
        energy = (features.chunk_rms * 0.75) + (features.chunk_peak_abs * 0.25)
        return round(min(1.0, (energy * 3.0 * artifact_gain) + hash_bias), 6)

    def open(self) -> None:
        if self._is_open:
            return
        self.reset()
        try:
            self._runtime = self._open_runtime()
        except (BCResNetRuntimeError, ManifestValidationError):
            self._loop.record_model_load_failure()
            raise
        self._is_open = True

    def close(self) -> None:
        self._runtime = None
        self._is_open = False

    def reset(self) -> None:
        self._frontend.reset()
        self._last_features = None
        self._loop.reset()

    def process(self, chunk: AudioChunk) -> DetectionDecision:
        """Update frontend state and emit suppression-aware detection decisions."""

        if not self._is_open or self._runtime is None:
            self._loop.record_runtime_failure()
            raise BCResNetRuntimeError("detector runtime is not open")
        try:
            self._last_features = self._frontend.process_chunk(chunk)
        except AudioFormatError:
            self._loop.record_invalid_frame()
            raise
        score = self._score_features(self._last_features)
        detected, state = self._loop.evaluate(
            score=score,
            threshold=self.config.threshold,
            frame_duration_seconds=self.audio_config.frame_duration_seconds,
        )
        return DetectionDecision(
            detected=detected,
            score=score,
            threshold=self.config.threshold,
            label=self.manifest.wake_word,
            state=state,
        )
