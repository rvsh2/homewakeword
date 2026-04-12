from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

from homewakeword.config import (
    CustomModelImportConfig,
    DetectorConfig,
    HomeWakeWordConfig,
    WyomingServerConfig,
)
from homewakeword.runtime import build_service
from homewakeword.selftest import run_self_test
from homewakeword.registry import load_registry
from scripts.validate_release import validate_release, validate_release_targets
from scripts.validate_startup import validate_startup


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "models" / "manifest.yaml"
DEFAULT_ADDON_CONFIG = REPO_ROOT / "addon" / "homewakeword" / "config.yaml"
DEFAULT_OUTPUT = REPO_ROOT / ".sisyphus" / "evidence" / "task-14-release.json"
NO_HA_BUILDER_TOOL = "NO_HA_BUILDER_TOOL"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.release_dry_run")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--addon-config", type=Path, default=DEFAULT_ADDON_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image-tag", default="local/homewakeword")
    return parser


def _load_addon_config(path: Path) -> dict[str, object]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"add-on config root must be a mapping: {path}")
    return raw


def release_dry_run(
    manifest_path: Path,
    addon_config_path: Path,
    output_path: Path,
    *,
    image_tag: str,
) -> dict[str, Any]:
    startup_message = validate_startup(manifest_path)
    release_message = validate_release(manifest_path, addon_config_path)
    release_targets, manifest_option = validate_release_targets(
        manifest_path,
        addon_config_path,
    )
    registry = load_registry(manifest_path, require_artifact=True)
    addon_config = _load_addon_config(addon_config_path)
    service = build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(manifest_path=manifest_path),
            custom_models=CustomModelImportConfig(enabled=False),
            server=WyomingServerConfig(host="127.0.0.1", port=10400),
        )
    )
    with TemporaryDirectory() as tmpdir:
        self_test_path = Path(tmpdir) / "self-test.json"
        self_test_result = run_self_test(service, report_path=self_test_path)
        self_test_payload = json.loads(self_test_path.read_text(encoding="utf-8"))

    report = {
        "verdict": "pass",
        "dry_run": True,
        "published": False,
        "manifest": str(manifest_path),
        "addon_config": str(addon_config_path),
        "default_model": registry.default_model.wake_word,
        "validation": {
            "startup": startup_message,
            "release": release_message,
            "self_test_status": self_test_result.status,
        },
        "publish_plan": {
            "manifest_option": manifest_option,
            "assets": release_targets,
            "image": {
                "template": addon_config.get("image"),
                "local_tag": image_tag,
                "publish": False,
            },
        },
        "environment_limitations": [
            {
                "code": NO_HA_BUILDER_TOOL,
                "status": "blocked",
                "detail": "Official Home Assistant builder tooling is not available in this workspace; the dry-run stops before any publish/build release step.",
            }
        ],
        "self_test": self_test_payload,
        "inventory_summary": [
            {
                "wake_word": record.wake_word,
                "artifact": record.artifact_name,
                "release_approved": record.release_approved,
                "hash_verified": record.hash_verified,
            }
            for record in registry.inventory(verify_hash=True)
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = release_dry_run(
            args.manifest,
            args.addon_config,
            args.output,
            image_tag=args.image_tag,
        )
    except (LookupError, OSError, ValueError) as exc:
        print(str(exc))
        return 1
    publish_plan = report["publish_plan"]
    print(
        f"release dry-run succeeded: assets={len(publish_plan['assets'])} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
