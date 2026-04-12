from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from homewake.audio import iter_wave_chunks
from homewake.cli import main
from homewake.config import DetectorConfig, HomeWakeConfig, WyomingServerConfig
from homewake.runtime import HomeWakeService, build_service


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifests" / "ok_nabu_detector.yaml"
POSITIVE_WAV = FIXTURE_ROOT / "stream" / "ok_nabu_positive.wav"


def _build_fixture_service() -> HomeWakeService:
    return build_service(
        HomeWakeConfig(
            detector=DetectorConfig(manifest_path=MANIFEST_PATH),
            server=WyomingServerConfig(host="127.0.0.1", port=10400),
        )
    )


def test_wyoming_server_starts_and_stops_cleanly() -> None:
    service = _build_fixture_service()
    server = service.server

    assert server.is_running is False
    assert server.health().overall.value == "degraded"

    server.start()
    try:
        assert server.is_running is True
        assert server.health().overall.value == "ready"
    finally:
        server.stop()

    assert server.is_running is False
    assert server.health().overall.value == "degraded"


def test_wyoming_server_reports_loaded_wake_words_from_registry() -> None:
    service = _build_fixture_service()

    description = service.server.describe()

    assert description.uri == "tcp://127.0.0.1:10400"
    assert [wake_word.name for wake_word in description.wake_words] == ["ok_nabu"]


def test_wyoming_server_emits_protocol_detection_event() -> None:
    service = _build_fixture_service()
    server = service.server

    server.start()
    try:
        detection_event = None
        for chunk in iter_wave_chunks(POSITIVE_WAV, service.config.audio):
            detection_event = server.handle_audio_chunk(chunk) or detection_event
        assert detection_event is not None
        assert detection_event.type == "detection"
        assert detection_event.wake_word == "ok_nabu"
        assert detection_event.service_uri == "tcp://127.0.0.1:10400"
    finally:
        server.stop()


def test_self_test_cli_writes_health_and_wake_word_report(tmp_path: Path) -> None:
    report_path = tmp_path / "wyoming-self-test.json"

    exit_code = main(
        [
            "serve",
            "--self-test",
            "--manifest",
            str(MANIFEST_PATH),
            "--report",
            str(report_path),
        ]
    )

    payload = cast(
        dict[str, object], json.loads(report_path.read_text(encoding="utf-8"))
    )
    startup_health = cast(dict[str, object], payload["startup_health"])
    shutdown_health = cast(dict[str, object], payload["shutdown_health"])
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["health_status"] == "ok"
    assert payload["loaded_wake_words"] == ["ok_nabu"]
    assert payload["detection_emitted"] is True
    assert startup_health["overall"] == "ready"
    assert shutdown_health["overall"] == "degraded"
