"""Real openWakeWord-backed detector adapter for public ONNX/TFLite artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
from openwakeword.model import Model

from homewakeword.audio import AudioChunk, AudioFormatError
from homewakeword.config import AudioInputConfig, DetectorConfig
from homewakeword.detector.base import DetectionDecision, DetectorRuntimeState
from homewakeword.detector.streaming import (
    DetectorLoopCounters,
    StreamingDetectionStateMachine,
)
from homewakeword.registry import ModelManifest, validate_manifest


class OpenWakeWordRuntimeError(RuntimeError):
    """Raised when the openWakeWord-backed runtime cannot be initialized."""


@dataclass(frozen=True, slots=True)
class OpenWakeWordRuntimeHandle:
    framework: str
    model_path: str
    support_paths: tuple[str, ...]


@dataclass(slots=True)
class OpenWakeWordDetector:
    config: DetectorConfig
    manifest: ModelManifest
    audio_config: AudioInputConfig = field(default_factory=AudioInputConfig)
    _runtime: OpenWakeWordRuntimeHandle | None = field(default=None, init=False)
    _model: Model | None = field(default=None, init=False, repr=False)
    _loop: StreamingDetectionStateMachine = field(init=False)
    _is_open: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._loop = StreamingDetectionStateMachine(
            cooldown_seconds=self.config.cooldown.activation_seconds,
            refractory_hold_seconds=self.config.refractory.hold_seconds,
            reset_threshold=self.config.refractory.reset_threshold,
        )

    @property
    def backend_name(self) -> str:
        return "openwakeword"

    @property
    def counters(self) -> DetectorLoopCounters:
        return self._loop.counters

    @property
    def runtime(self) -> OpenWakeWordRuntimeHandle | None:
        return self._runtime

    def _support_assets(self) -> tuple[Path, Path]:
        if self.manifest.model_path is None:
            raise OpenWakeWordRuntimeError(
                "openWakeWord manifest did not resolve a model artifact"
            )
        model_dir = self.manifest.model_path.parent
        if self.manifest.framework == "onnx":
            mel = model_dir / "melspectrogram.onnx"
            emb = model_dir / "embedding_model.onnx"
        else:
            mel = model_dir / "melspectrogram.tflite"
            emb = model_dir / "embedding_model.tflite"
        for asset in (mel, emb):
            if not asset.exists():
                raise OpenWakeWordRuntimeError(
                    f"missing required openWakeWord support asset: {asset}"
                )
        return mel, emb

    def open(self) -> None:
        if self._is_open:
            return
        _ = validate_manifest(self.manifest, require_artifact=True)
        if self.manifest.model_path is None:
            raise OpenWakeWordRuntimeError("openWakeWord manifest missing model_path")
        mel, emb = self._support_assets()
        try:
            self._model = Model(
                wakeword_models=[str(self.manifest.model_path)],
                inference_framework=self.manifest.framework,
                melspec_model_path=str(mel),
                embedding_model_path=str(emb),
                enable_speex_noise_suppression=self.config.enable_speex_noise_suppression,
                vad_threshold=self.config.vad.threshold
                if self.config.vad.enabled
                else 0.0,
            )
        except Exception as exc:  # pragma: no cover - depends on third-party runtime
            self._loop.record_model_load_failure()
            raise OpenWakeWordRuntimeError(str(exc)) from exc
        self._runtime = OpenWakeWordRuntimeHandle(
            framework=self.manifest.framework,
            model_path=str(self.manifest.model_path),
            support_paths=(str(mel), str(emb)),
        )
        self._is_open = True

    def close(self) -> None:
        self._model = None
        self._runtime = None
        self._is_open = False

    def reset(self) -> None:
        self._loop.reset()
        if self._model is not None:
            self._model.reset()

    def process(self, chunk: AudioChunk) -> DetectionDecision:
        if not self._is_open or self._model is None:
            self._loop.record_runtime_failure()
            raise OpenWakeWordRuntimeError("openWakeWord runtime is not open")
        if chunk.sample_rate_hz != self.audio_config.sample_rate_hz:
            self._loop.record_invalid_frame()
            raise AudioFormatError(
                f"unsupported sample rate: expected {self.audio_config.sample_rate_hz} Hz, got {chunk.sample_rate_hz} Hz"
            )
        if chunk.channels != self.audio_config.channels:
            self._loop.record_invalid_frame()
            raise AudioFormatError(
                f"unsupported channel count: expected {self.audio_config.channels}, got {chunk.channels}"
            )
        samples = np.frombuffer(chunk.pcm, dtype=np.int16)
        predictions = cast(dict[str, Any], self._model.predict(samples))
        raw_score = float(predictions.get(self.manifest.model_id, 0.0))
        score = raw_score
        vad_suppressed = False
        vad_score = None
        if self.config.vad.enabled and getattr(self._model, "vad_threshold", 0) > 0:
            vad_buffer = (
                list(self._model.vad.prediction_buffer)[-7:-4]
                if hasattr(self._model, "vad")
                else []
            )
            vad_score = float(max(vad_buffer)) if vad_buffer else 0.0
            if vad_score < self.config.vad.threshold:
                score = 0.0
                vad_suppressed = True
                self._loop.record_vad_suppression()
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
            raw_score=raw_score,
            vad_score=vad_score,
            vad_threshold=self.config.vad.threshold
            if self.config.vad.enabled
            else None,
            vad_suppressed=vad_suppressed,
            state=DetectorRuntimeState(
                cooldown_remaining_seconds=state.cooldown_remaining_seconds,
                refractory_remaining_seconds=state.refractory_remaining_seconds,
                armed=state.armed,
                vad_suppressed=vad_suppressed,
            ),
        )
