from __future__ import annotations

import json
from pathlib import Path

from scripts.release_dry_run import main, release_dry_run


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.yaml"
ADDON_CONFIG = REPO_ROOT / "addon" / "homewake-bcresnet" / "config.yaml"


def test_release_dry_run_reports_non_destructive_publish_plan(tmp_path: Path) -> None:
    output_path = tmp_path / "release-dry-run.json"

    report = release_dry_run(
        MANIFEST_PATH,
        ADDON_CONFIG,
        output_path,
        image_tag="local/homewake-bcresnet:test",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert payload["dry_run"] is True
    assert payload["published"] is False
    assert payload["publish_plan"]["image"]["publish"] is False
    assert payload["publish_plan"]["assets"]
    assert payload["environment_limitations"][0]["code"] == "NO_HA_BUILDER_TOOL"
    assert payload["validation"]["self_test_status"] == "ok"


def test_release_dry_run_main_succeeds_with_explicit_output(tmp_path: Path) -> None:
    output_path = tmp_path / "release-dry-run.json"

    exit_code = main(["--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
