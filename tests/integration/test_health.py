from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from homewakeword.config import (
    DetectorConfig,
    HomeWakeWordConfig,
    VADConfig,
    WyomingServerConfig,
)
from homewakeword.runtime import HomeWakeWordService, build_service
from homewakeword.selftest import run_self_test


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifests" / "ok_nabu_detector.yaml"


def _build_fixture_service() -> HomeWakeWordService:
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                manifest_path=MANIFEST_PATH,
                enable_speex_noise_suppression=False,
                vad=VADConfig(enabled=False),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=10400),
        )
    )


def test_health_payload_includes_compact_inventory_and_config_echo() -> None:
    service = _build_fixture_service()

    payload = service.server.health().as_dict()
    inventory = cast(list[dict[str, object]], payload["inventory"])
    config = cast(dict[str, object], payload["config"])

    assert payload["overall"] == "degraded"
    assert [
        component["name"]
        for component in cast(list[dict[str, str]], payload["components"])
    ] == ["server", "detector", "provenance"]
    assert inventory[0]["wake_word"] == "ok_nabu"
    assert inventory[0]["provenance_status"] == "approved"
    assert inventory[0]["hash_verified"] is True
    assert "expected_sha256" not in inventory[0]
    assert cast(dict[str, object], config["detector"])["backend"] == "bcresnet"


def test_self_test_report_includes_inventory_provenance_and_diagnostics(
    tmp_path: Path,
) -> None:
    service = _build_fixture_service()
    report_path = tmp_path / "health-report.json"

    result = run_self_test(service, report_path=report_path)
    payload = cast(
        dict[str, object], json.loads(report_path.read_text(encoding="utf-8"))
    )
    loaded_models = cast(list[dict[str, object]], payload["loaded_models"])
    startup_resources = cast(dict[str, object], payload["startup_resources"])
    startup_health = cast(dict[str, object], payload["startup_health"])
    shutdown_health = cast(dict[str, object], payload["shutdown_health"])
    startup_diagnostics = cast(dict[str, object], startup_health["diagnostics"])
    startup_process_resources = cast(
        dict[str, object], startup_diagnostics["process_resources"]
    )
    startup_duration_ms = cast(float, payload["startup_duration_ms"])

    assert result.status == "ok"
    assert payload["health_status"] == "ready"
    assert startup_duration_ms > 0.0
    assert cast(int, startup_resources["rss_bytes"]) > 0
    assert loaded_models[0]["wake_word"] == "ok_nabu"
    assert loaded_models[0]["license"] == "CC-BY-4.0"
    assert loaded_models[0]["hash_verified"] is True
    assert loaded_models[0]["release_approved"] is True
    assert startup_health["overall"] == "ready"
    assert startup_health["classification"] == "healthy"
    assert shutdown_health["overall"] == "degraded"
    assert shutdown_health["classification"] == "degraded"
    assert startup_diagnostics["service_uri"] == "tcp://127.0.0.1:10400"
    assert startup_diagnostics["loaded_model_count"] == 1
    assert startup_diagnostics["startup_duration_ms"] == startup_duration_ms
    assert cast(int, startup_process_resources["rss_bytes"]) > 0
