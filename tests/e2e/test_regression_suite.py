# pyright: reportMissingImports=false
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import yaml
from wyoming.client import AsyncClient
from wyoming.info import Describe, Info

from scripts.ha_smoke import (
    DEFAULT_HARNESS,
    _prepare_supervisor_share,
    _resolve_registry_service_host,
    ha_smoke,
    run_replay_probe,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence"
FIXTURE_MANIFEST = (
    REPO_ROOT / "tests" / "fixtures" / "manifests" / "ok_nabu_detector.yaml"
)
PYTHON_EXECUTABLE = Path(sys.executable)


def test_supervised_harness_shape_is_present() -> None:
    raw = yaml.safe_load(DEFAULT_HARNESS.read_text(encoding="utf-8")) or {}

    assert isinstance(raw, dict)
    services = raw.get("services")
    assert isinstance(services, dict)
    assert {"ha_supervisor", "homeassistant", "addon_registry"}.issubset(services)
    supervisor = services["ha_supervisor"]
    assert supervisor["privileged"] is True
    assert supervisor["environment"]["SUPERVISOR_MACHINE"] == "generic-x86-64"
    assert (
        supervisor["environment"]["SUPERVISOR_SHARE"]
        == "/opt/homewakeword/.sisyphus/ha-supervised/share"
    )
    assert any("/var/run/docker.sock" in str(entry) for entry in supervisor["volumes"])
    assert any(
        "/opt/homewakeword/.sisyphus/ha-supervised/share" in str(entry)
        for entry in supervisor["volumes"]
    )
    assert _resolve_registry_service_host(raw) == "localhost.localdomain:5000"
    registry = services["addon_registry"]
    assert registry["environment"]["REGISTRY_HTTP_ADDR"] == "0.0.0.0:80"
    assert "5000:80" in registry["ports"]


def test_smoke_report_emits_explicit_subsystem_results() -> None:
    report_path = EVIDENCE_ROOT / "test-task10-ha-smoke.json"

    report = ha_smoke(
        DEFAULT_HARNESS,
        addon_slug="homewakeword",
        addon_image="local/homewakeword",
        wyoming_port=10400,
        report_path=report_path,
    )

    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    subsystems = persisted["subsystems"]
    assert report["verdict"] == persisted["verdict"]
    assert set(subsystems) == {
        "audio_replay",
        "detector_runtime",
        "wyoming_service",
        "addon_packaging",
        "artifact_loading",
        "ha_harness",
    }
    assert subsystems["audio_replay"]["status"] == "pass"
    assert subsystems["detector_runtime"]["status"] == "pass"
    assert subsystems["wyoming_service"]["status"] in {"pass", "fail"}
    assert subsystems["addon_packaging"]["status"] in {"pass", "blocked", "fail"}
    assert subsystems["ha_harness"]["status"] in {"pass", "blocked", "fail"}
    assert subsystems["ha_harness"]["code"] in {
        "HA_HARNESS_UNAVAILABLE",
        "HA_HARNESS_INVALID",
        "HA_HARNESS_MISSING",
        "HA_HARNESS_BOOT_BLOCKED",
        "HA_HARNESS_REPOSITORY_UNAVAILABLE",
        "HA_HARNESS_INSTALL_FAILED",
        "HA_HARNESS_START_BLOCKED",
        "HA_HARNESS_SUPERVISOR_FLOW_BLOCKED",
        "HA_HARNESS_ADDON_STARTED",
        "NOT_RUN",
    }
    assert Path(persisted["artifacts"]["replay_positive"]).exists()
    assert Path(persisted["artifacts"]["replay_negative"]).exists()
    assert Path(persisted["artifacts"]["wyoming_self_test"]).exists()


def test_prepare_supervisor_share_creates_nested_share_tree() -> None:
    with TemporaryDirectory() as tmpdir:
        share_root = Path(tmpdir) / "share-root"
        _prepare_supervisor_share(share_root, addon_install_slug="local_homewakeword")

        assert (share_root / "share").is_dir()
        assert (share_root / "addons" / "data" / "local_homewakeword").is_dir()
        assert (share_root / "cid_files" / "addon_local_homewakeword.cid").is_file()


def test_missing_artifact_is_classified_as_artifact_loading() -> None:
    with TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        broken_manifest = tmp_root / "broken-manifest.yaml"
        _ = broken_manifest.write_text(
            (
                "model_id: broken_fixture\n"
                "wake_word: ok_nabu\n"
                "version: 0.0.1\n"
                "backend: bcresnet\n"
                "framework: tflite\n"
                "model_path: missing-model.tflite\n"
                "threshold: 0.55\n"
                "provenance:\n"
                "  source: fixture://tests/missing-model.tflite\n"
                "  training_recipe: fixture-ok-nabu\n"
                "  training_recipe_version: 0.0.1\n"
                "  artifact_sha256: b96fed2b844b770ae57ffdef4bc264dea5eb77ce9dd96bcbaf163cf72cbe4282\n"
                "  license: CC-BY-4.0\n"
                "  provenance_status: approved\n"
                "audio:\n"
                "  sample_rate_hz: 16000\n"
                "  sample_width_bytes: 2\n"
                "  channels: 1\n"
                "  frame_samples: 1280\n"
                "  window_seconds: 1.0\n"
                "frontend:\n"
                "  n_fft: 512\n"
                "  win_length: 480\n"
                "  hop_length: 160\n"
                "  n_mels: 40\n"
                "  f_min_hz: 20.0\n"
                "  f_max_hz: 7600.0\n"
                "  log_floor: 1.0e-6\n"
                "  context_seconds: 1.0\n"
            ),
            encoding="utf-8",
        )
        result = run_replay_probe(
            broken_manifest,
            wake_word="ok_nabu",
            input_path=REPO_ROOT
            / "tests"
            / "fixtures"
            / "stream"
            / "ok_nabu_positive.wav",
            expect="ok_nabu",
            json_out=tmp_root / "broken-replay.json",
            log_path=tmp_root / "broken-replay.log",
        )

    assert result["status"] == "fail"
    assert result["subsystem"] == "artifact_loading"
    assert result["code"] == "ARTIFACT_LOADING_FAILURE"
    assert "model artifact does not exist" in str(result["detail"])


def test_cli_serve_exposes_real_wyoming_tcp_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    process = subprocess.Popen(
        [
            str(PYTHON_EXECUTABLE),
            "-m",
            "homewakeword.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--manifest",
            str(FIXTURE_MANIFEST),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 20.0
        ready_line = ""
        assert process.stdout is not None
        while time.time() < deadline:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue
            ready_line = line.strip()
            if ready_line.startswith(f"ready: uri=tcp://127.0.0.1:{port}"):
                break

        assert ready_line.startswith(f"ready: uri=tcp://127.0.0.1:{port}")

        async def _fetch_info() -> Info:
            async with AsyncClient.from_uri(f"tcp://127.0.0.1:{port}") as client:
                await client.write_event(Describe().event())
                event = await client.read_event()
                assert event is not None
                return Info.from_event(event)

        info = asyncio.run(_fetch_info())
        assert [model.name for model in info.wake[0].models] == ["ok_nabu"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
