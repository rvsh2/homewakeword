from __future__ import annotations

import os
from pathlib import Path

from homewakeword.audio import iter_wave_chunks
from homewakeword.config import DetectorConfig, HomeWakeWordConfig, WyomingServerConfig
from homewakeword.events import DetectionEventType
from homewakeword.runtime import HomeWakeWordService, build_service


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "models" / "openwakeword-real" / "manifest.yaml"
POSITIVE_WAV = (
    REPO_ROOT / "tests" / "fixtures" / "openwakeword-benchmark" / "jarvis_0.wav"
)
NEGATIVE_WAV = REPO_ROOT / "tests" / "fixtures" / "stream" / "no_wake_negative.wav"


def _build_openwakeword_service() -> HomeWakeWordService:
    os.environ["HOMEWAKE_ENABLE_ONNX"] = "1"
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                backend="openwakeword",
                manifest_path=MANIFEST_PATH,
                threshold=0.5,
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=0),
        )
    )


def test_openwakeword_backend_lists_real_models() -> None:
    service = _build_openwakeword_service()
    assert service.manifest.backend == "openwakeword"
    assert service.registry.list_wake_words() == (
        "alexa",
        "hey_jarvis",
        "hey_mycroft",
        "hey_rhasspy",
    )


def test_openwakeword_backend_detects_jarvis_benchmark_audio() -> None:
    service = _build_openwakeword_service()
    service.server.start(bind_listener=False)
    try:
        events = [
            service.server.runtime.handle_audio_chunk(chunk)
            for chunk in iter_wave_chunks(POSITIVE_WAV, service.config.audio)
        ]
    finally:
        service.server.stop()

    detections = [
        event for event in events if event.type is DetectionEventType.DETECTION
    ]
    assert detections, (
        "expected at least one detection for public jarvis benchmark audio"
    )
    assert any(event.label == "hey_jarvis" for event in detections)
    assert max(event.decision.score for event in detections) >= 0.5


def test_openwakeword_backend_rejects_negative_audio() -> None:
    service = _build_openwakeword_service()
    service.server.start(bind_listener=False)
    try:
        events = [
            service.server.runtime.handle_audio_chunk(chunk)
            for chunk in iter_wave_chunks(NEGATIVE_WAV, service.config.audio)
        ]
    finally:
        service.server.stop()

    detections = [
        event for event in events if event.type is DetectionEventType.DETECTION
    ]
    assert detections == []
