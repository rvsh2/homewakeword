from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from homewakeword.registry import ManifestValidationError, load_manifest
from homewakeword.training import (
    TrainingValidationError,
    build_runtime_manifest,
    evaluate_holdouts,
    export_artifact,
    load_training_config,
    validate_training_dataset,
    write_manifest_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.train_custom")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _build_report(
    *,
    config,
    dataset_summary,
    bundle,
    evaluation,
) -> dict[str, object]:
    manifest = load_manifest(bundle.manifest_path)
    inventory = manifest.inventory_record(verify_hash=True)
    return {
        "config": {
            "config_path": str(config.config_path),
            "model_id": config.model_id,
            "wake_word": config.wake_word,
            "version": config.version,
            "threshold": config.threshold,
        },
        "dataset": {
            **asdict(dataset_summary),
            "train_positive_paths": [
                str(path) for path in config.dataset.train_positive_paths
            ],
            "holdout_positive": str(config.dataset.holdout_positive),
            "holdout_negative": str(config.dataset.holdout_negative),
        },
        "artifacts": {
            "output_dir": str(bundle.output_dir),
            "artifact_path": str(bundle.artifact_path),
            "manifest_path": str(bundle.manifest_path),
            "manifest_snippet_path": str(bundle.manifest_snippet_path),
            "artifact_sha256": bundle.artifact_sha256,
        },
        "evaluation": {
            "passed": evaluation.passed,
            "positive": asdict(evaluation.positive),
            "negative": asdict(evaluation.negative),
        },
        "manifest": inventory.as_report_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_training_config(args.config)
        dataset_summary = validate_training_dataset(config)
        bundle = export_artifact(config, dataset_summary, output_dir=args.output_dir)
        runtime_manifest = build_runtime_manifest(
            config,
            artifact_path=bundle.artifact_path,
            artifact_sha256=bundle.artifact_sha256,
        )
        evaluation = evaluate_holdouts(
            runtime_manifest,
            positive_path=config.dataset.holdout_positive,
            negative_path=config.dataset.holdout_negative,
        )
        write_manifest_bundle(config, bundle, evaluation)

        report = _build_report(
            config=config,
            dataset_summary=dataset_summary,
            bundle=bundle,
            evaluation=evaluation,
        )
        report_path = bundle.output_dir / "training_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        if not evaluation.passed:
            print(
                "holdout evaluation failed for exported custom wake-word artifact",
                file=sys.stderr,
            )
            return 1

        print(f"custom training export complete: {bundle.manifest_path}")
        return 0
    except (
        TrainingValidationError,
        ManifestValidationError,
        OSError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
