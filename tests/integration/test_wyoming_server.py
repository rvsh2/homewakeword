# pyright: reportMissingImports=false
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

from homewakeword.audio import iter_wave_chunks
from homewakeword.cli import main
from homewakeword.config import (
    DetectorConfig,
    HomeWakeWordConfig,
    VADConfig,
    WyomingServerConfig,
)
from homewakeword.runtime import HomeWakeWordService, build_service
from wyoming.audio import AudioChunk as WyomingAudioChunk
from wyoming.audio import AudioStart, AudioStop
from wyoming.client import AsyncClient
from wyoming.info import Describe, Info
from wyoming.wake import Detect, Detection, NotDetected


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifests" / "ok_nabu_detector.yaml"
POSITIVE_WAV = FIXTURE_ROOT / "stream" / "ok_nabu_positive.wav"


def _build_fixture_service() -> HomeWakeWordService:
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                manifest_path=MANIFEST_PATH,
                enable_speex_noise_suppression=False,
                vad=VADConfig(enabled=False),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=0),
        )
    )


async def _describe(uri: str) -> Info:
    async with AsyncClient.from_uri(uri) as client:
        await client.write_event(Describe().event())
        event = await client.read_event()
        assert event is not None
        return Info.from_event(event)


async def _detect(
    uri: str, service: HomeWakeWordService, *, positive: bool
) -> Detection | NotDetected:
    async with AsyncClient.from_uri(uri) as client:
        await client.write_event(Detect(names=["ok_nabu"]).event())
        await client.write_event(
            AudioStart(
                rate=service.config.audio.sample_rate_hz,
                width=service.config.audio.sample_width_bytes,
                channels=service.config.audio.channels,
            ).event()
        )
        input_path = (
            POSITIVE_WAV
            if positive
            else FIXTURE_ROOT / "stream" / "no_wake_negative.wav"
        )
        for chunk in iter_wave_chunks(input_path, service.config.audio):
            await client.write_event(
                WyomingAudioChunk(
                    rate=chunk.sample_rate_hz,
                    width=chunk.sample_width_bytes,
                    channels=chunk.channels,
                    audio=chunk.pcm,
                ).event()
            )
        await client.write_event(AudioStop().event())

        while True:
            event = await client.read_event()
            assert event is not None
            if Detection.is_type(event.type):
                return Detection.from_event(event)
            if NotDetected.is_type(event.type):
                return NotDetected.from_event(event)


def test_wyoming_server_starts_and_stops_cleanly() -> None:
    service = _build_fixture_service()
    server = service.server

    assert server.is_running is False
    assert server.health().overall.value == "degraded"

    server.start()
    try:
        assert server.is_running is True
        assert server.health().overall.value == "ready"
        assert server.uri.startswith("tcp://127.0.0.1:")
    finally:
        server.stop()

    assert server.is_running is False
    assert server.health().overall.value == "degraded"


def test_wyoming_server_reports_loaded_wake_words_from_registry() -> None:
    service = _build_fixture_service()
    server = service.server

    server.start()
    try:
        description = server.describe()
        info = asyncio.run(_describe(description.uri))

        assert description.uri.startswith("tcp://127.0.0.1:")
        assert [wake_word.name for wake_word in description.wake_words] == ["ok_nabu"]
        assert len(info.wake) == 1
        assert [model.name for model in info.wake[0].models] == ["ok_nabu"]
    finally:
        server.stop()


def test_wyoming_server_emits_protocol_detection_event_over_tcp() -> None:
    service = _build_fixture_service()
    server = service.server

    server.start()
    try:
        result = asyncio.run(_detect(server.describe().uri, service, positive=True))
        assert isinstance(result, Detection)
        assert result.name == "ok_nabu"
        assert result.timestamp is not None
    finally:
        server.stop()


def test_wyoming_server_emits_not_detected_over_tcp() -> None:
    service = _build_fixture_service()
    server = service.server

    server.start()
    try:
        result = asyncio.run(_detect(server.describe().uri, service, positive=False))
        assert isinstance(result, NotDetected)
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
    startup_resources = cast(dict[str, object], payload["startup_resources"])
    loaded_models = cast(list[dict[str, object]], payload["loaded_models"])
    startup_health = cast(dict[str, object], payload["startup_health"])
    shutdown_health = cast(dict[str, object], payload["shutdown_health"])
    startup_duration_ms = cast(float, payload["startup_duration_ms"])
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["health_status"] == "ready"
    assert startup_duration_ms > 0.0
    assert cast(int, startup_resources["rss_bytes"]) > 0
    assert payload["loaded_wake_words"] == ["ok_nabu"]
    assert loaded_models[0]["provenance_status"] == "approved"
    assert payload["detection_emitted"] is True
    assert startup_health["overall"] == "ready"
    assert startup_health["classification"] == "healthy"
    assert shutdown_health["overall"] == "degraded"
    assert shutdown_health["classification"] == "degraded"
