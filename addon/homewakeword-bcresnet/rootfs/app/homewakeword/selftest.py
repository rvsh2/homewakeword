"""Non-interactive self-test helpers for the packaged Wyoming service."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

from homewakeword.audio import AudioChunk, floats_to_pcm16le
from homewakeword.registry import ModelInventoryRecord
from homewakeword.runtime import HomeWakeWordService, build_runtime_report


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    """Structured self-test outcome for health/reporting."""

    status: str
    health_status: str
    loaded_wake_words: tuple[str, ...]
    loaded_models: tuple[ModelInventoryRecord, ...]
    imported_wake_words: tuple[str, ...]
    import_rejections: tuple[str, ...]
    detection_emitted: bool
    detection_wake_word: str | None
    service_uri: str
    config: dict[str, object]
    startup_duration_ms: float
    startup_resources: dict[str, object]
    startup_health: dict[str, object]
    shutdown_health: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "health_status": self.health_status,
            "loaded_wake_words": list(self.loaded_wake_words),
            "loaded_models": [model.as_report_dict() for model in self.loaded_models],
            "imported_wake_words": list(self.imported_wake_words),
            "import_rejections": list(self.import_rejections),
            "detection_emitted": self.detection_emitted,
            "detection_wake_word": self.detection_wake_word,
            "service_uri": self.service_uri,
            "config": self.config,
            "startup_duration_ms": self.startup_duration_ms,
            "startup_resources": self.startup_resources,
            "startup_health": self.startup_health,
            "shutdown_health": self.shutdown_health,
        }


def _loud_chunk(service: HomeWakeWordService) -> AudioChunk:
    samples = [0.9] * service.config.audio.frame_samples
    return AudioChunk(
        pcm=floats_to_pcm16le(samples),
        sample_rate_hz=service.config.audio.sample_rate_hz,
        sample_width_bytes=service.config.audio.sample_width_bytes,
        channels=service.config.audio.channels,
    )


def run_self_test(
    service: HomeWakeWordService, report_path: Path | None = None
) -> SelfTestResult:
    """Exercise startup, describe, audio, detection, and shutdown paths."""

    server = service.server
    detection_event = None
    startup_started = time.perf_counter()
    server.start()
    startup_duration_ms = round((time.perf_counter() - startup_started) * 1000.0, 3)
    try:
        startup_health = build_runtime_report(
            service,
            startup_duration_ms=startup_duration_ms,
        )
        for _ in range(4):
            detection_event = server.handle_audio_chunk(_loud_chunk(service))
            if detection_event is not None:
                break
    finally:
        server.stop()

    shutdown_health = build_runtime_report(service)
    startup_diagnostics = startup_health.get("diagnostics")
    startup_resources = (
        {}
        if not isinstance(startup_diagnostics, dict)
        else startup_diagnostics.get("process_resources", {})
    )
    if not isinstance(startup_resources, dict):
        startup_resources = {}
    result = SelfTestResult(
        status="ok" if detection_event is not None else "failed",
        health_status=str(startup_health["overall"]),
        loaded_wake_words=tuple(
            wake_word.name for wake_word in server.describe().wake_words
        ),
        loaded_models=service.inventory,
        imported_wake_words=service.custom_imports.imported_wake_words,
        import_rejections=service.custom_imports.rejected,
        detection_emitted=detection_event is not None,
        detection_wake_word=None
        if detection_event is None
        else detection_event.wake_word,
        service_uri=server.uri,
        config=service.config_echo,
        startup_duration_ms=startup_duration_ms,
        startup_resources=startup_resources,
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
