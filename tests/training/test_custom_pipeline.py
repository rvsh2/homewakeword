from __future__ import annotations

import json
from pathlib import Path

import yaml

from homewake.registry import load_manifest
from scripts.train_custom import main


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "training"


def test_custom_pipeline_exports_runtime_manifest_and_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "custom-train"

    exit_code = main(
        [
            "--config",
            str(FIXTURE_ROOT / "custom_model.yaml"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "custom_fixture_homewake.tflite").exists()
    assert (output_dir / "manifest.yaml").exists()
    assert (output_dir / "manifest_snippet.yaml").exists()
    assert (output_dir / "training_report.json").exists()

    manifest = load_manifest(output_dir / "manifest.yaml")
    assert manifest.model_id == "custom_fixture_homewake"
    assert manifest.wake_word == "hey_homewake_custom"
    assert (
        manifest.model_path == (output_dir / "custom_fixture_homewake.tflite").resolve()
    )
    assert manifest.provenance is not None
    assert manifest.provenance.provenance_status.value == "unverifiable"
    assert manifest.evaluation is not None
    assert manifest.evaluation.status.value == "validated"

    report = json.loads(
        (output_dir / "training_report.json").read_text(encoding="utf-8")
    )
    assert report["evaluation"]["passed"] is True
    assert report["evaluation"]["positive"]["detection_count"] == 1
    assert report["evaluation"]["negative"]["detection_count"] == 0
    assert report["manifest"]["hash_verified"] is True


def test_custom_pipeline_fails_fast_for_incomplete_dataset(
    tmp_path: Path,
    capsys,
) -> None:
    config = yaml.safe_load(
        (FIXTURE_ROOT / "custom_model.yaml").read_text(encoding="utf-8")
    )
    stream_root = FIXTURE_ROOT.parent / "stream"
    config["dataset"]["train_positive_paths"] = [
        str((stream_root / "okay_nabu_positive.wav").resolve()),
        str((stream_root / "hey_jarvis_positive.wav").resolve()),
    ]
    config["dataset"]["holdout_positive"] = str(
        (stream_root / "alexa_positive.wav").resolve()
    )
    config["dataset"]["holdout_negative"] = "missing_negative.wav"
    broken_config_path = tmp_path / "broken_model.yaml"
    broken_config_path.write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )

    output_dir = tmp_path / "broken-output"
    exit_code = main(
        [
            "--config",
            str(broken_config_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 1
    assert "holdout negative WAV does not exist" in capsys.readouterr().err
    assert not (output_dir / "manifest.yaml").exists()
