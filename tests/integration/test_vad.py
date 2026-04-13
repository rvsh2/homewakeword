from __future__ import annotations

from pathlib import Path
from typing import cast

from homewakeword.audio import AudioChunk
from homewakeword.audio import iter_wave_chunks
from homewakeword.config import (
    DetectorConfig,
    HomeWakeWordConfig,
    VADConfig,
    WyomingServerConfig,
)
from homewakeword.events import DetectionEventType
from homewakeword.detector.bcresnet import BCResNetDetector
from homewakeword.runtime import HomeWakeWordService, build_service


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifests" / "ok_nabu_detector.yaml"
POSITIVE_WAV = FIXTURE_ROOT / "stream" / "ok_nabu_positive.wav"
NEGATIVE_WAV = FIXTURE_ROOT / "stream" / "no_wake_negative.wav"


def _build_vad_service() -> HomeWakeWordService:
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                manifest_path=MANIFEST_PATH,
                threshold=0.05,
                enable_speex_noise_suppression=False,
                vad=VADConfig(enabled=True, threshold=0.2),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=0),
        )
    )


def test_vad_enabled_preserves_positive_spoken_detection() -> None:
    service = _build_vad_service()
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
    assert len(detections) == 1
    assert detections[0].label == "ok_nabu"


def test_vad_enabled_suppresses_non_speech_negative_stream() -> None:
    service = _build_vad_service()
    service.server.start(bind_listener=False)
    try:
        silent_chunk = AudioChunk(
            pcm=b"\x00"
            * (
                service.config.audio.frame_samples
                * service.config.audio.sample_width_bytes
            ),
            sample_rate_hz=service.config.audio.sample_rate_hz,
            sample_width_bytes=service.config.audio.sample_width_bytes,
            channels=service.config.audio.channels,
        )
        events = [
            service.server.runtime.handle_audio_chunk(silent_chunk) for _ in range(8)
        ]
        detector = cast(BCResNetDetector, service.server.runtime.detector)
        counters = detector.counters
    finally:
        service.server.stop()

    detections = [
        event for event in events if event.type is DetectionEventType.DETECTION
    ]
    vad_suppressed = [
        event for event in events if event.type is DetectionEventType.SUPPRESSED_VAD
    ]
    assert detections == []
    assert len(vad_suppressed) > 0
    assert counters.vad_suppressions > 0


def test_speex_noise_suppression_keeps_positive_detection_working() -> None:
    service = build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                manifest_path=MANIFEST_PATH,
                threshold=0.05,
                enable_speex_noise_suppression=True,
                vad=VADConfig(enabled=False),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=0),
        )
    )
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
    assert len(detections) == 1
    assert detections[0].label == "ok_nabu"
