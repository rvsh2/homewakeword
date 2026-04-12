from __future__ import annotations

from pathlib import Path

from scripts.validate_startup import main, validate_startup


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "manifests"


def test_validate_startup_passes_for_valid_tflite_manifest() -> None:
    message = validate_startup(FIXTURE_ROOT / "valid_bcresnet_tflite.yaml")

    assert "startup validation passed" in message
    assert "framework=tflite" in message


def test_validate_startup_main_fails_for_missing_artifact(capsys) -> None:
    exit_code = main(["--manifest", str(FIXTURE_ROOT / "invalid_missing_model.yaml")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "model artifact does not exist" in captured.err
