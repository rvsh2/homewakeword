"""Offline holdout evaluation for exported custom wake-word artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import TYPE_CHECKING

from homewakeword.audio import iter_wave_chunks
from homewakeword.config import HomeWakeWordConfig, VADConfig
from homewakeword.detector.bcresnet import BCResNetDetector
from homewakeword.events import DetectionEventType
from homewakeword.server.wyoming import WyomingRuntime

if TYPE_CHECKING:
    from homewakeword.registry import ModelManifest


@dataclass(frozen=True, slots=True)
class DetectionSummary:
    path: str
    detection_count: int
    detected_labels: tuple[str, ...]
    chunk_count: int


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    positive: DetectionSummary
    negative: DetectionSummary

    @property
    def passed(self) -> bool:
        return (
            self.positive.detection_count == 1
            and len(self.positive.detected_labels) == 1
            and self.negative.detection_count == 0
        )


def _run_detection(manifest: ModelManifest, *, input_path) -> DetectionSummary:
    detector_config = replace(
        manifest.detector_config(),
        enable_speex_noise_suppression=False,
        vad=VADConfig(enabled=False),
    )
    detector = BCResNetDetector(
        config=detector_config,
        manifest=manifest,
        audio_config=manifest.audio,
    )
    runtime = WyomingRuntime(
        config=HomeWakeWordConfig(audio=manifest.audio, detector=detector_config),
        detector=detector,
    )
    detector.open()
    try:
        events = [
            runtime.handle_audio_chunk(chunk)
            for chunk in iter_wave_chunks(input_path, manifest.audio)
        ]
    finally:
        detector.close()
    detections = tuple(
        event.label for event in events if event.type is DetectionEventType.DETECTION
    )
    return DetectionSummary(
        path=str(input_path),
        detection_count=len(detections),
        detected_labels=detections,
        chunk_count=len(events),
    )


def evaluate_holdouts(
    manifest: ModelManifest,
    *,
    positive_path,
    negative_path,
) -> EvaluationSummary:
    return EvaluationSummary(
        positive=_run_detection(manifest, input_path=positive_path),
        negative=_run_detection(manifest, input_path=negative_path),
    )
