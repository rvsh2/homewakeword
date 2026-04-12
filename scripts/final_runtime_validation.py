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
from homewakeword.registry import load_registry
from homewakeword.runtime import build_service
from homewakeword.selftest import run_self_test
from scripts.ha_smoke import ha_smoke
from scripts.replay_stream import main as replay_stream_main
from scripts.validate_release import validate_release
from scripts.validate_repo import validate_repo
from scripts.validate_startup import validate_startup


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADDON_CONFIG = REPO_ROOT / "addon" / "homewakeword" / "config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.final_runtime_validation")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ha-harness", type=Path, default=None)
    parser.add_argument("--addon-image", default="local/homewakeword")
    parser.add_argument("--addon-config", type=Path, default=DEFAULT_ADDON_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def final_runtime_validation(
    manifest_path: Path,
    *,
    addon_config_path: Path,
    ha_harness: Path | None,
    addon_image: str,
) -> dict[str, Any]:
    repo_errors = validate_repo(REPO_ROOT)
    if repo_errors:
        raise ValueError("repo validation failed: " + "; ".join(repo_errors))
    startup_message = validate_startup(manifest_path)
    release_message = validate_release(manifest_path, addon_config_path)
    addon_config_raw = (
        yaml.safe_load(addon_config_path.read_text(encoding="utf-8")) or {}
    )
    if not isinstance(addon_config_raw, dict):
        raise ValueError(f"add-on config root must be a mapping: {addon_config_path}")
    addon_slug_value = addon_config_raw.get("slug")
    if not isinstance(addon_slug_value, str) or not addon_slug_value.strip():
        raise ValueError(f"add-on config is missing a valid slug: {addon_config_path}")
    addon_slug = addon_slug_value
    registry = load_registry(manifest_path, require_artifact=True)
    default_manifest = registry.default_model
    if default_manifest.evaluation is None:
        raise ValueError("default manifest does not define evaluation fixtures")
    service = build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(manifest_path=manifest_path),
            custom_models=CustomModelImportConfig(enabled=False),
            server=WyomingServerConfig(host="127.0.0.1", port=10400),
        )
    )
    limitations: list[str] = []
    with TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        self_test_path = tmp_root / "self-test.json"
        positive_replay_path = tmp_root / "positive.json"
        negative_replay_path = tmp_root / "negative.json"
        ha_smoke_report_path = tmp_root / "ha-smoke.json"
        self_test_result = run_self_test(service, report_path=self_test_path)
        positive_exit = replay_stream_main(
            [
                "--manifest",
                str(manifest_path),
                "--wake-word",
                default_manifest.wake_word,
                "--input",
                str(default_manifest.evaluation.positive_fixture),
                "--expect",
                default_manifest.wake_word,
                "--json-out",
                str(positive_replay_path),
            ]
        )
        negative_exit = replay_stream_main(
            [
                "--manifest",
                str(manifest_path),
                "--wake-word",
                default_manifest.wake_word,
                "--input",
                str(default_manifest.evaluation.negative_fixture),
                "--expect",
                "none",
                "--json-out",
                str(negative_replay_path),
            ]
        )
        if positive_exit != 0 or negative_exit != 0:
            raise ValueError(
                "fixture replay validation failed during final runtime validation"
            )
        ha_harness_report: dict[str, Any] | None = None
        ha_harness_summary: dict[str, Any] = {
            "path": None if ha_harness is None else str(ha_harness),
            "exists": None if ha_harness is None else ha_harness.exists(),
            "executed": False,
        }
        if ha_harness is not None and not ha_harness.exists():
            limitations.append(
                f"Home Assistant harness path is missing in this workspace: {ha_harness}"
            )
        elif ha_harness is None:
            limitations.append("Home Assistant supervised harness was not provided")
        else:
            ha_harness_report = ha_smoke(
                ha_harness,
                addon_slug=addon_slug,
                addon_image=addon_image,
                wyoming_port=10400,
                report_path=ha_smoke_report_path,
                manifest_path=manifest_path,
            )
            subsystems = ha_harness_report.get("subsystems")
            ha_subsystem = (
                subsystems.get("ha_harness") if isinstance(subsystems, dict) else None
            )
            if not isinstance(ha_subsystem, dict):
                raise ValueError(
                    "ha smoke report did not include an ha_harness subsystem"
                )
            ha_harness_summary = {
                **ha_harness_summary,
                "executed": True,
                "verdict": ha_harness_report.get("verdict"),
                "status": ha_subsystem.get("status"),
                "code": ha_subsystem.get("code"),
                "detail": ha_subsystem.get("detail"),
            }
            ha_status = str(ha_subsystem.get("status", "unknown"))
            ha_code = str(ha_subsystem.get("code", "UNKNOWN"))
            ha_detail = str(ha_subsystem.get("detail", ""))
            if ha_status != "pass":
                limitations.append(f"Home Assistant harness {ha_code}: {ha_detail}")
        verdict = "pass"
        if ha_harness_report is not None:
            ha_smoke_verdict = str(ha_harness_report.get("verdict", "pass"))
            if ha_smoke_verdict == "fail":
                verdict = "fail"
            elif ha_smoke_verdict == "blocked":
                verdict = "blocked"
        report = {
            "verdict": verdict,
            "manifest": str(manifest_path),
            "addon_config": str(addon_config_path),
            "addon_image": addon_image,
            "validation": {
                "startup": startup_message,
                "release": release_message,
                "self_test_status": self_test_result.status,
                "positive_replay_exit": positive_exit,
                "negative_replay_exit": negative_exit,
                "ha_smoke_verdict": None
                if ha_harness_report is None
                else ha_harness_report.get("verdict"),
            },
            "default_wake_word": default_manifest.wake_word,
            "self_test": json.loads(self_test_path.read_text(encoding="utf-8")),
            "positive_replay": json.loads(
                positive_replay_path.read_text(encoding="utf-8")
            ),
            "negative_replay": json.loads(
                negative_replay_path.read_text(encoding="utf-8")
            ),
            "ha_harness": ha_harness_summary,
            "limitations": limitations,
        }
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = final_runtime_validation(
            args.manifest,
            addon_config_path=args.addon_config,
            ha_harness=args.ha_harness,
            addon_image=args.addon_image,
        )
    except (LookupError, OSError, ValueError) as exc:
        print(str(exc))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"final runtime validation written: verdict={report['verdict']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
