from __future__ import annotations

from pathlib import Path

import pytest

from homewake.registry import (
    ManifestValidationError,
    ModelRegistry,
    load_manifest,
    load_registry,
)


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "manifests"


def test_load_manifest_parses_valid_tflite_fixture() -> None:
    manifest = load_manifest(FIXTURE_ROOT / "valid_bcresnet_tflite.yaml")

    assert manifest.model_id == "fixture_bcresnet_tflite"
    assert manifest.framework == "tflite"
    assert manifest.backend == "bcresnet"
    assert manifest.model_path == (FIXTURE_ROOT / "fixture_model.tflite").resolve()
    assert manifest.audio.sample_rate_hz == 16_000
    assert manifest.detector_config().threshold == 0.42


def test_load_manifest_allows_frontend_only_fixture_for_replay() -> None:
    manifest = load_manifest(FIXTURE_ROOT / "frontend_only.yaml", require_artifact=False)

    assert manifest.mode == "frontend_only"
    assert manifest.model_path is None
    assert manifest.wake_word == "frontend_only"


def test_load_manifest_rejects_missing_file() -> None:
    with pytest.raises(ManifestValidationError, match="manifest file does not exist"):
        load_manifest(FIXTURE_ROOT / "does_not_exist.yaml")


def test_load_manifest_rejects_missing_artifact() -> None:
    with pytest.raises(ManifestValidationError, match="model artifact does not exist"):
        load_manifest(FIXTURE_ROOT / "invalid_missing_model.yaml")


def test_load_manifest_rejects_unsupported_backend() -> None:
    with pytest.raises(ManifestValidationError, match="unsupported detector backend"):
        load_manifest(FIXTURE_ROOT / "invalid_unsupported_backend.yaml")


def test_load_manifest_rejects_suffix_mismatch() -> None:
    with pytest.raises(ManifestValidationError, match="expects artifact suffix"):
        load_manifest(FIXTURE_ROOT / "invalid_suffix_mismatch.yaml")


def test_load_manifest_rejects_onnx_without_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOMEWAKE_ENABLE_ONNX", raising=False)

    with pytest.raises(ManifestValidationError, match="requires explicit opt-in"):
        load_manifest(FIXTURE_ROOT / "valid_bcresnet_onnx.yaml")


def test_load_manifest_accepts_onnx_with_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOMEWAKE_ENABLE_ONNX", "1")

    manifest = load_manifest(FIXTURE_ROOT / "valid_bcresnet_onnx.yaml")

    assert manifest.framework == "onnx"
    assert manifest.model_path == (FIXTURE_ROOT / "fixture_model.onnx").resolve()


def test_load_registry_resolves_default_manifest() -> None:
    registry = load_registry(FIXTURE_ROOT / "valid_bcresnet_tflite.yaml")

    assert isinstance(registry, ModelRegistry)
    assert registry.resolve("bcresnet").model_id == "fixture_bcresnet_tflite"


def test_model_registry_rejects_wrong_backend() -> None:
    registry = load_registry(FIXTURE_ROOT / "valid_bcresnet_tflite.yaml")

    with pytest.raises(LookupError, match="Unsupported detector backend"):
        registry.resolve("fake")
