from __future__ import annotations

from pathlib import Path

from scripts.validate_addon_config import main, validate_addon_config


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "addon"
CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "addon"
    / "homewakeword"
    / "config.yaml"
)


def test_validate_addon_config_accepts_valid_options() -> None:
    message = validate_addon_config(CONFIG_PATH, FIXTURE_ROOT / "options.valid.json")

    assert "add-on config validation passed" in message
    assert "backend=bcresnet" in message


def test_validate_addon_config_rejects_invalid_options(capsys) -> None:
    exit_code = main(
        [
            "--config",
            str(CONFIG_PATH),
            "--options",
            str(FIXTURE_ROOT / "options.invalid.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "option 'host' must be a non-empty string" in captured.err
