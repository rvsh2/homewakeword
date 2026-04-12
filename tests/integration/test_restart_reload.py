from __future__ import annotations

from pathlib import Path
import time
from typing import cast

import yaml

from homewakeword.audio import iter_wave_chunks
from homewakeword.config import DetectorConfig, HomeWakeWordConfig, WyomingServerConfig
from homewakeword.detector.bcresnet import BCResNetRuntimeError
from homewakeword.registry import ManifestValidationError
from homewakeword.runtime import (
    build_service,
    build_runtime_report,
    build_startup_failure_report,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
STREAM_ROOT = FIXTURE_ROOT / "stream"
MANIFEST_ROOT = FIXTURE_ROOT / "manifests"
BASE_MANIFEST = MANIFEST_ROOT / "restart_swap_okay_nabu.yaml"
VALID_SWAP_MANIFEST = MANIFEST_ROOT / "restart_swap_hey_jarvis.yaml"
INVALID_SWAP_MANIFEST = MANIFEST_ROOT / "restart_swap_invalid_missing_artifact.yaml"


def _build_config(manifest_path: Path, *, port: int = 10400) -> HomeWakeWordConfig:
    return HomeWakeWordConfig(
        detector=DetectorConfig(manifest_path=manifest_path),
        server=WyomingServerConfig(host="127.0.0.1", port=port),
    )


def _replay(service, input_path: Path, *, expect: str) -> None:
    reset = getattr(service.server.runtime.detector, "reset", None)
    if callable(reset):
        reset()
    detected_labels: list[str] = []
    for chunk in iter_wave_chunks(input_path, service.config.audio):
        detection = service.server.handle_audio_chunk(chunk)
        if detection is not None:
            detected_labels.append(detection.wake_word)
    if expect == "none":
        assert detected_labels == []
    else:
        assert detected_labels == [expect]


def _materialize_manifest(source_manifest: Path, target_manifest: Path) -> None:
    raw = yaml.safe_load(source_manifest.read_text(encoding="utf-8")) or {}
    assert isinstance(raw, dict)
    model_path = raw.get("model_path")
    if isinstance(model_path, str) and not Path(model_path).is_absolute():
        raw["model_path"] = str((source_manifest.parent / model_path).resolve())
    evaluation = raw.get("evaluation")
    if isinstance(evaluation, dict):
        for key in ("positive_fixture", "negative_fixture"):
            value = evaluation.get(key)
            if isinstance(value, str) and not Path(value).is_absolute():
                evaluation[key] = str((source_manifest.parent / value).resolve())
    target_manifest.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )


def test_repeated_service_start_stop_resets_runtime_state_and_reports_resources() -> (
    None
):
    service = build_service(_build_config(BASE_MANIFEST))

    startup_durations: list[float] = []
    for _ in range(3):
        started = time.perf_counter()
        service.server.start()
        startup_duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
        startup_durations.append(startup_duration_ms)
        startup_health = build_runtime_report(
            service,
            startup_duration_ms=startup_duration_ms,
            notes=["test=repeated_start_stop"],
        )
        diagnostics = cast(dict[str, object], startup_health["diagnostics"])
        resources = cast(dict[str, object], diagnostics["process_resources"])

        assert startup_health["overall"] == "ready"
        assert startup_health["classification"] == "healthy"
        assert diagnostics["startup_duration_ms"] == startup_duration_ms
        assert cast(int, resources["rss_bytes"]) > 0
        assert cast(float, resources["user_cpu_seconds"]) >= 0
        _replay(service, STREAM_ROOT / "okay_nabu_positive.wav", expect="okay_nabu")
        service.server.stop()
        shutdown_health = build_runtime_report(
            service, notes=["test=repeated_start_stop"]
        )
        assert shutdown_health["overall"] == "degraded"
        assert shutdown_health["classification"] == "degraded"

    assert max(startup_durations) < 250.0


def test_valid_model_restart_loads_replaced_manifest_from_same_path(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "runtime-manifest.yaml"
    _materialize_manifest(BASE_MANIFEST, manifest_path)

    original_service = build_service(_build_config(manifest_path, port=10410))
    original_service.server.start()
    try:
        assert [
            wake_word.name
            for wake_word in original_service.server.describe().wake_words
        ] == ["okay_nabu"]
        _replay(
            original_service, STREAM_ROOT / "okay_nabu_positive.wav", expect="okay_nabu"
        )
    finally:
        original_service.server.stop()

    _materialize_manifest(VALID_SWAP_MANIFEST, manifest_path)
    replacement_service = build_service(_build_config(manifest_path, port=10411))
    replacement_service.server.start()
    try:
        health = build_runtime_report(
            replacement_service,
            notes=["test=valid_model_restart"],
        )
        assert [
            wake_word.name
            for wake_word in replacement_service.server.describe().wake_words
        ] == ["hey_jarvis"]
        assert replacement_service.manifest.wake_word == "hey_jarvis"
        assert health["overall"] == "ready"
        assert health["classification"] == "healthy"
        _replay(
            replacement_service,
            STREAM_ROOT / "hey_jarvis_positive.wav",
            expect="hey_jarvis",
        )
    finally:
        replacement_service.server.stop()


def test_invalid_model_swap_fails_safely_and_preserves_active_service(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "runtime-manifest.yaml"
    _materialize_manifest(VALID_SWAP_MANIFEST, manifest_path)
    active_config = _build_config(manifest_path, port=10420)
    active_service = build_service(active_config)
    active_service.server.start()
    try:
        _replay(
            active_service, STREAM_ROOT / "hey_jarvis_positive.wav", expect="hey_jarvis"
        )
        _materialize_manifest(INVALID_SWAP_MANIFEST, manifest_path)
        started = time.perf_counter()
        with_raised = False
        failure: BaseException | None = None
        try:
            _ = build_service(_build_config(manifest_path, port=10421))
        except (
            BCResNetRuntimeError,
            ManifestValidationError,
            LookupError,
            OSError,
        ) as exc:
            with_raised = True
            failure = exc
        assert with_raised is True
        assert failure is not None
        failure_report = build_startup_failure_report(
            _build_config(manifest_path, port=10421),
            error=failure,
            startup_duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
            notes=["test=invalid_model_swap"],
        )

        assert active_service.server.is_running is True
        assert failure_report["overall"] == "failed"
        assert failure_report["classification"] == "unhealthy"
        failure_diagnostics = cast(dict[str, object], failure_report["diagnostics"])
        failure_resources = cast(
            dict[str, object], failure_diagnostics["process_resources"]
        )
        assert "startup_error" in failure_diagnostics
        assert cast(int, failure_resources["rss_bytes"]) > 0
        _replay(
            active_service, STREAM_ROOT / "hey_jarvis_positive.wav", expect="hey_jarvis"
        )
        active_health = build_runtime_report(
            active_service, notes=["test=invalid_model_swap"]
        )
        assert active_health["overall"] == "ready"
        assert active_health["classification"] == "healthy"
    finally:
        active_service.server.stop()
