"""Non-interactive self-test helpers for the packaged Wyoming service."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from homewake.audio import AudioChunk, floats_to_pcm16le
from homewake.runtime import HomeWakeService


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    """Structured self-test outcome for health/reporting."""

    status: str
    health_status: str
    loaded_wake_words: tuple[str, ...]
    detection_emitted: bool
    detection_wake_word: str | None
    service_uri: str
    startup_health: dict[str, object]
    shutdown_health: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "health_status": self.health_status,
            "loaded_wake_words": list(self.loaded_wake_words),
            "detection_emitted": self.detection_emitted,
            "detection_wake_word": self.detection_wake_word,
            "service_uri": self.service_uri,
            "startup_health": self.startup_health,
            "shutdown_health": self.shutdown_health,
        }


def _loud_chunk(service: HomeWakeService) -> AudioChunk:
    samples = [0.9] * service.config.audio.frame_samples
    return AudioChunk(
        pcm=floats_to_pcm16le(samples),
        sample_rate_hz=service.config.audio.sample_rate_hz,
        sample_width_bytes=service.config.audio.sample_width_bytes,
        channels=service.config.audio.channels,
    )


def run_self_test(
    service: HomeWakeService, report_path: Path | None = None
) -> SelfTestResult:
    """Exercise startup, describe, audio, detection, and shutdown paths."""

    server = service.server
    detection_event = None
    server.start()
    try:
        startup_health = server.health().as_dict()
        for _ in range(4):
            detection_event = server.handle_audio_chunk(_loud_chunk(service))
            if detection_event is not None:
                break
    finally:
        server.stop()

    shutdown_health = server.health().as_dict()
    result = SelfTestResult(
        status="ok" if detection_event is not None else "failed",
        health_status="ok" if startup_health["overall"] == "ready" else "failed",
        loaded_wake_words=tuple(
            wake_word.name for wake_word in server.describe().wake_words
        ),
        detection_emitted=detection_event is not None,
        detection_wake_word=None
        if detection_event is None
        else detection_event.wake_word,
        service_uri=server.uri,
        startup_health=startup_health,
        shutdown_health=shutdown_health,
    )
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _ = report_path.write_text(
            json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if detection_event is None:
        raise RuntimeError("self-test did not emit a detection event")
    return result
