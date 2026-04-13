from __future__ import annotations

from pathlib import Path

from homewakeword.audio import iter_wave_chunks
from homewakeword.config import (
    DetectorConfig,
    HomeWakeWordConfig,
    VADConfig,
    WyomingServerConfig,
)
from homewakeword.events import DetectionEventType
from homewakeword.runtime import build_service


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "models" / "bcresnet-real" / "manifest.yaml"
POSITIVE_WAV = (
    REPO_ROOT / "tests" / "fixtures" / "openwakeword-benchmark" / "jarvis_0.wav"
)
NEGATIVE_WAV = REPO_ROOT / "tests" / "fixtures" / "stream" / "no_wake_negative.wav"


def _build_bcresnet_service() -> object:
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                backend="bcresnet",
                manifest_path=MANIFEST_PATH,
                threshold=0.00001,
                enable_speex_noise_suppression=False,
                vad=VADConfig(enabled=False),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=0),
        )
    )


def test_bcresnet_real_backend_detects_jarvis_benchmark_audio() -> None:
    service = _build_bcresnet_service()
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
        "expected at least one BC-ResNet detection for benchmark jarvis audio"
    )
    assert any(event.label == "hey_jarvis" for event in detections)


def test_bcresnet_real_backend_rejects_negative_audio() -> None:
    service = _build_bcresnet_service()
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
