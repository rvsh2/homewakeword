"""Deterministic local artifact export for custom wake-word training."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from shutil import copy2

import yaml

from homewakeword.registry import EvaluationStatus
from homewakeword.training.evaluate import EvaluationSummary
from homewakeword.training.manifest import (
    CustomTrainingConfig,
    DatasetSummary,
    build_training_manifest_mapping,
)


@dataclass(frozen=True, slots=True)
class ExportBundle:
    output_dir: Path
    artifact_path: Path
    manifest_path: Path
    manifest_snippet_path: Path
    fixtures_dir: Path
    positive_fixture_path: Path
    negative_fixture_path: Path
    artifact_sha256: str


def _artifact_payload(
    config: CustomTrainingConfig,
    dataset_summary: DatasetSummary,
) -> bytes:
    payload = {
        "format": "homewakeword-bcresnet-custom-export",
        "model": {
            "model_id": config.model_id,
            "wake_word": config.wake_word,
            "version": config.version,
            "threshold": config.threshold,
        },
        "dataset": asdict(dataset_summary),
        "frontend": {
            "sample_rate_hz": config.audio.sample_rate_hz,
            "frame_samples": config.audio.frame_samples,
            "window_seconds": config.audio.window_seconds,
            "n_mels": config.frontend.n_mels,
            "context_seconds": config.frontend.context_seconds,
        },
        "inputs": {
            "train_positive_paths": [
                str(path) for path in config.dataset.train_positive_paths
            ],
            "holdout_positive": str(config.dataset.holdout_positive),
            "holdout_negative": str(config.dataset.holdout_negative),
        },
    }
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    return b"HOMEWAKE_BCRESNET_CUSTOM_EXPORT\n" + body + b"\n"


def export_artifact(
    config: CustomTrainingConfig,
    dataset_summary: DatasetSummary,
    *,
    output_dir: Path,
) -> ExportBundle:
    resolved_output_dir = output_dir.resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = resolved_output_dir / config.export.artifact_name
    artifact_bytes = _artifact_payload(config, dataset_summary)
    artifact_path.write_bytes(artifact_bytes)
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()

    fixtures_dir = resolved_output_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    positive_fixture_path = fixtures_dir / config.dataset.holdout_positive.name
    negative_fixture_path = fixtures_dir / config.dataset.holdout_negative.name
    copy2(config.dataset.holdout_positive, positive_fixture_path)
    copy2(config.dataset.holdout_negative, negative_fixture_path)

    return ExportBundle(
        output_dir=resolved_output_dir,
        artifact_path=artifact_path,
        manifest_path=resolved_output_dir / "manifest.yaml",
        manifest_snippet_path=resolved_output_dir / "manifest_snippet.yaml",
        fixtures_dir=fixtures_dir,
        positive_fixture_path=positive_fixture_path,
        negative_fixture_path=negative_fixture_path,
        artifact_sha256=artifact_sha256,
    )


def write_manifest_bundle(
    config: CustomTrainingConfig,
    bundle: ExportBundle,
    evaluation: EvaluationSummary,
) -> None:
    evaluation_status = (
        EvaluationStatus.VALIDATED if evaluation.passed else EvaluationStatus.PENDING
    )
    manifest_mapping = build_training_manifest_mapping(
        config,
        artifact_name=bundle.artifact_path.name,
        artifact_sha256=bundle.artifact_sha256,
        evaluation_status=evaluation_status,
        positive_fixture_path=bundle.positive_fixture_path.relative_to(bundle.output_dir),
        negative_fixture_path=bundle.negative_fixture_path.relative_to(bundle.output_dir),
    )
    rendered = yaml.safe_dump(manifest_mapping, sort_keys=False)
    bundle.manifest_path.write_text(rendered, encoding="utf-8")
    bundle.manifest_snippet_path.write_text(rendered, encoding="utf-8")
