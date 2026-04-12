from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import yaml

from homewake.registry import ManifestValidationError, load_registry


class ReleaseValidationError(ValueError):
    """Raised when release packaging metadata is not safe to ship."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.validate_release")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--addon-config", type=Path, required=True)
    return parser


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ReleaseValidationError(f"malformed YAML: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReleaseValidationError(f"YAML root must be a mapping: {path}")
    return raw


def _validate_addon_release_shape(addon_config_path: Path, *, backend: str) -> str:
    config = _load_yaml(addon_config_path)
    options = config.get("options")
    schema = config.get("schema")
    if not isinstance(options, dict):
        raise ReleaseValidationError("add-on config options must be a mapping")
    if not isinstance(schema, dict):
        raise ReleaseValidationError("add-on config schema must be a mapping")
    if "manifest" not in options or "manifest" not in schema:
        raise ReleaseValidationError("add-on config must expose a manifest option")
    if "detector_backend" not in options:
        raise ReleaseValidationError(
            "add-on config must expose detector_backend in options"
        )

    manifest_option = options["manifest"]
    if not isinstance(manifest_option, str) or not manifest_option.strip():
        raise ReleaseValidationError(
            "add-on manifest option must be a non-empty string"
        )
    if not manifest_option.startswith("/app/models/"):
        raise ReleaseValidationError(
            "add-on manifest option must point at packaged /app/models/ content"
        )
    if Path(manifest_option).name != "manifest.yaml":
        raise ReleaseValidationError(
            "add-on manifest option must target packaged manifest.yaml"
        )

    detector_backend = options["detector_backend"]
    if detector_backend != backend:
        raise ReleaseValidationError(
            "add-on detector_backend does not match manifest backend: "
            f"{detector_backend!r} != {backend!r}"
        )
    return manifest_option


def validate_release_targets(
    manifest_path: Path,
    addon_config_path: Path,
) -> tuple[list[dict[str, object]], str]:
    registry = load_registry(manifest_path, require_artifact=True)
    inventory = [
        record.as_report_dict() for record in registry.inventory(verify_hash=True)
    ]
    manifest_option = _validate_addon_release_shape(
        addon_config_path,
        backend=registry.default_model.backend,
    )
    for record in inventory:
        if record["provenance_status"] != "approved":
            raise ManifestValidationError(
                "release manifest requires provenance_status=approved; "
                f"got {record['provenance_status']!r} for model '{record['model_id']}'"
            )
        if record["hash_verified"] is not True:
            raise ManifestValidationError(
                "release manifest hash verification failed for model "
                f"'{record['model_id']}'"
            )
    return inventory, manifest_option


def validate_release(manifest_path: Path, addon_config_path: Path) -> str:
    inventory, manifest_option = validate_release_targets(
        manifest_path,
        addon_config_path,
    )
    if len(inventory) == 1:
        record = inventory[0]
        return (
            "release validation passed: "
            f"model={record['model_id']} wake_word={record['wake_word']} "
            f"sha256={record['expected_sha256']} addon_manifest={manifest_option}"
        )
    return (
        "release validation passed: "
        f"models={len(inventory)} addon_manifest={manifest_option}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(validate_release(args.manifest, args.addon_config))
    except (
        ManifestValidationError,
        ReleaseValidationError,
        LookupError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
