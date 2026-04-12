from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from homewake.config import DetectorConfig, HomeWakeConfig, WyomingServerConfig
from homewake.runtime import HomeWakeService, build_service
from homewake.selftest import run_self_test


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifests" / "ok_nabu_detector.yaml"


def _build_fixture_service() -> HomeWakeService:
    return build_service(
        HomeWakeConfig(
            detector=DetectorConfig(manifest_path=MANIFEST_PATH),
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
    startup_health = cast(dict[str, object], payload["startup_health"])
    shutdown_health = cast(dict[str, object], payload["shutdown_health"])
    startup_diagnostics = cast(dict[str, object], startup_health["diagnostics"])

    assert result.status == "ok"
    assert payload["health_status"] == "ready"
    assert loaded_models[0]["wake_word"] == "ok_nabu"
    assert loaded_models[0]["license"] == "CC-BY-4.0"
    assert loaded_models[0]["hash_verified"] is True
    assert loaded_models[0]["release_approved"] is True
    assert startup_health["overall"] == "ready"
    assert shutdown_health["overall"] == "degraded"
    assert startup_diagnostics["service_uri"] == "tcp://127.0.0.1:10400"
    assert startup_diagnostics["loaded_model_count"] == 1
