from __future__ import annotations

from pathlib import Path

import pytest

from homewakeword.registry import ManifestValidationError, validate_release_manifest
from scripts.validate_release import main, validate_release


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "manifests"
ADDON_CONFIG = (
    Path(__file__).resolve().parents[2] / "addon" / "homewakeword-bcresnet" / "config.yaml"
)


def test_validate_release_manifest_passes_with_verified_hash() -> None:
    inventory = validate_release_manifest(FIXTURE_ROOT / "valid_bcresnet_tflite.yaml")

    assert inventory.release_approved is True
    assert inventory.hash_verified is True
    assert inventory.license == "CC-BY-4.0"


def test_validate_release_manifest_rejects_unapproved_provenance() -> None:
    with pytest.raises(ManifestValidationError, match="provenance_status=approved"):
        validate_release_manifest(FIXTURE_ROOT / "unapproved_provenance.yaml")


def test_validate_release_passes_for_repo_addon_and_fixture_manifest() -> None:
    message = validate_release(
        FIXTURE_ROOT / "valid_bcresnet_tflite.yaml",
        ADDON_CONFIG,
    )

    assert "release validation passed" in message
    assert "sha256=" in message


def test_validate_release_main_fails_for_missing_hash(capsys) -> None:
    exit_code = main(
        [
            "--manifest",
            str(FIXTURE_ROOT / "missing_hash.yaml"),
            "--addon-config",
            str(ADDON_CONFIG),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "artifact_sha256" in captured.err
