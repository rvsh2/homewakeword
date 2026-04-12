from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HACS_CONFIG = REPO_ROOT / "hacs.json"
INTEGRATION_ROOT = REPO_ROOT / "custom_components" / "homewakeword"


def test_hacs_repository_metadata_exposes_custom_integration_repo() -> None:
    payload = json.loads(HACS_CONFIG.read_text(encoding="utf-8"))

    assert payload["name"] == "HomeWakeWord"
    assert payload["render_readme"] is True
    assert payload["homeassistant"]


def test_helper_integration_scaffold_exists_for_hacs_install() -> None:
    expected_paths = [
        INTEGRATION_ROOT / "__init__.py",
        INTEGRATION_ROOT / "manifest.json",
        INTEGRATION_ROOT / "const.py",
        INTEGRATION_ROOT / "config_flow.py",
        INTEGRATION_ROOT / "strings.json",
        INTEGRATION_ROOT / "translations" / "en.json",
    ]

    for path in expected_paths:
        assert path.exists(), (
            f"missing helper integration path: {path.relative_to(REPO_ROOT)}"
        )


def test_manifest_declares_config_flow_without_runtime_dependencies() -> None:
    payload = json.loads(
        (INTEGRATION_ROOT / "manifest.json").read_text(encoding="utf-8")
    )

    assert payload["domain"] == "homewakeword"
    assert payload["name"] == "HomeWakeWord"
    assert payload["config_flow"] is True
    assert payload["requirements"] == []
    assert payload["documentation"].endswith("#hacs-helper-integration")


def test_helper_integration_copy_keeps_addon_and_wyoming_flow_explicit() -> None:
    strings = json.loads(
        (INTEGRATION_ROOT / "strings.json").read_text(encoding="utf-8")
    )
    step = strings["config"]["step"]["user"]
    description = step["description"]

    assert "Install and start the HomeWakeWord add-on separately" in description
    assert "built-in Wyoming integration" in description
    assert "host `{wyoming_host}` and port `{wyoming_port}`" in description
    assert "does not install, manage, or proxy the add-on runtime" in description


def test_validate_repo_requires_hacs_surface_paths() -> None:
    from scripts.validate_repo import validate_repo

    errors = validate_repo(REPO_ROOT)

    assert "missing required path: hacs.json" not in errors
    assert "missing required path: custom_components/homewakeword" not in errors
    assert (
        "missing required path: custom_components/homewakeword/manifest.json"
        not in errors
    )
