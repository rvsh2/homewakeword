from __future__ import annotations

from pathlib import Path

from homewakeword.config import (
    CustomModelImportConfig,
    DetectorConfig,
    HomeWakeWordConfig,
    WyomingServerConfig,
)
from homewakeword.runtime import build_service
from scripts.train_custom import main as train_custom_main


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
TRAINING_CONFIG = FIXTURE_ROOT / "training" / "custom_model.yaml"
REPO_PACK_MANIFEST = Path(__file__).resolve().parents[2] / "models" / "manifest.yaml"


def _build_service(
    *,
    custom_models: bool,
    custom_model_dir: Path,
    openwakeword_compat: bool = False,
    openwakeword_model_dir: Path | None = None,
):
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(manifest_path=REPO_PACK_MANIFEST),
            custom_models=CustomModelImportConfig(
                enabled=custom_models,
                directory=custom_model_dir,
                openwakeword_compat_enabled=openwakeword_compat,
                openwakeword_directory=(
                    custom_model_dir
                    if openwakeword_model_dir is None
                    else openwakeword_model_dir
                ),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=10400),
        )
    )


def _export_bundle(output_dir: Path) -> Path:
    exit_code = train_custom_main(
        [
            "--config",
            str(TRAINING_CONFIG),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0
    return output_dir


def test_runtime_imports_valid_custom_bundle_and_advertises_it(tmp_path: Path) -> None:
    bundle_dir = _export_bundle(tmp_path / "primary" / "homewake_custom")

    service = _build_service(
        custom_models=True,
        custom_model_dir=tmp_path / "primary",
    )

    assert "hey_homewakeword_custom" in service.registry.list_wake_words()
    assert "hey_homewakeword_custom" in [
        wake_word.name for wake_word in service.server.describe().wake_words
    ]
    assert any(record.wake_word == "hey_homewakeword_custom" for record in service.inventory)
    assert service.custom_imports.loaded_manifest_paths == (
        (bundle_dir / "manifest.yaml").resolve(),
    )
    assert service.custom_imports.rejected == ()


def test_runtime_rejects_manifestless_tflite_imports(tmp_path: Path) -> None:
    primary_dir = tmp_path / "primary"
    primary_dir.mkdir(parents=True, exist_ok=True)
    (primary_dir / "bare_model.tflite").write_bytes(b"bare-custom-model")

    service = _build_service(
        custom_models=True,
        custom_model_dir=primary_dir,
    )

    assert "bare_model" not in service.registry.list_wake_words()
    assert all(record.artifact_name != "bare_model.tflite" for record in service.inventory)
    assert any(
        "sibling manifest.yaml" in message and "bare_model.tflite" in message
        for message in service.custom_imports.rejected
    )


def test_openwakeword_compatibility_path_requires_explicit_opt_in(tmp_path: Path) -> None:
    compat_root = tmp_path / "openwakeword"
    _ = _export_bundle(compat_root / "bundle")

    without_compat = _build_service(
        custom_models=True,
        custom_model_dir=tmp_path / "primary",
        openwakeword_compat=False,
        openwakeword_model_dir=compat_root,
    )
    assert "hey_homewakeword_custom" not in without_compat.registry.list_wake_words()

    with_compat = _build_service(
        custom_models=True,
        custom_model_dir=tmp_path / "primary",
        openwakeword_compat=True,
        openwakeword_model_dir=compat_root,
    )
    assert "hey_homewakeword_custom" in with_compat.registry.list_wake_words()
