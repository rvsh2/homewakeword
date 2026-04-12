from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml


class AddonConfigValidationError(ValueError):
    """Raised when add-on packaging metadata or options are invalid."""


_REQUIRED_TOP_LEVEL_KEYS = (
    "name",
    "version",
    "slug",
    "description",
    "arch",
    "init",
    "startup",
    "boot",
    "ports",
    "options",
    "schema",
)

_ALLOWED_LOG_LEVELS = {"trace", "debug", "info", "notice", "warning", "error", "fatal"}
_SUPPORTED_BACKENDS = {"bcresnet"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.validate_addon_config")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--options", type=Path, required=True)
    return parser


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AddonConfigValidationError(f"malformed add-on config YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise AddonConfigValidationError("add-on config root must be a mapping")
    return raw


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AddonConfigValidationError(f"malformed add-on options JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AddonConfigValidationError("add-on options must decode to an object")
    return raw


def _require_keys(config: dict[str, Any]) -> None:
    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in config:
            raise AddonConfigValidationError(f"add-on config missing required key: {key}")


def _validate_schema_shape(config: dict[str, Any]) -> None:
    schema = config.get("schema")
    options = config.get("options")
    ports = config.get("ports")
    if not isinstance(schema, dict):
        raise AddonConfigValidationError("config.schema must be a mapping")
    if not isinstance(options, dict):
        raise AddonConfigValidationError("config.options must be a mapping")
    if not isinstance(ports, dict):
        raise AddonConfigValidationError("config.ports must be a mapping")
    if set(schema) != set(options):
        raise AddonConfigValidationError("config.options and config.schema must define the same option keys")
    if "10700/tcp" not in ports:
        raise AddonConfigValidationError("config.ports must expose '10700/tcp'")


def _validate_metadata(config: dict[str, Any]) -> None:
    if config.get("slug") != "homewakeword-bcresnet":
        raise AddonConfigValidationError("config.slug must be 'homewakeword-bcresnet'")
    if config.get("startup") != "services":
        raise AddonConfigValidationError("config.startup must be 'services'")
    if config.get("boot") != "auto":
        raise AddonConfigValidationError("config.boot must be 'auto'")
    if config.get("init") is not False:
        raise AddonConfigValidationError("config.init must be false so run.sh owns lifecycle")
    arch = config.get("arch")
    if not isinstance(arch, list) or not arch:
        raise AddonConfigValidationError("config.arch must be a non-empty list")


def _require_absolute_path(value: object, *, option_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AddonConfigValidationError(f"option '{option_name}' must be a non-empty string")
    if not value.startswith("/"):
        raise AddonConfigValidationError(f"option '{option_name}' must be an absolute path")
    return value


def _require_bool(value: object, *, option_name: str) -> bool:
    if not isinstance(value, bool):
        raise AddonConfigValidationError(f"option '{option_name}' must be a boolean")
    return value


def _validate_against_schema(config: dict[str, Any], options: dict[str, Any]) -> None:
    schema = config["schema"]
    expected_keys = set(schema)
    actual_keys = set(options)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if extra:
            details.append(f"extra keys: {', '.join(extra)}")
        raise AddonConfigValidationError("add-on options do not match schema: " + "; ".join(details))

    host = options["host"]
    if not isinstance(host, str) or not host.strip():
        raise AddonConfigValidationError("option 'host' must be a non-empty string")

    port = options["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
        raise AddonConfigValidationError("option 'port' must be an integer between 1 and 65535")

    detector_backend = options["detector_backend"]
    if detector_backend not in _SUPPORTED_BACKENDS:
        raise AddonConfigValidationError(
            "option 'detector_backend' must be one of: " + ", ".join(sorted(_SUPPORTED_BACKENDS))
        )

    _ = _require_absolute_path(options["manifest"], option_name="manifest")
    _ = _require_bool(options["custom_models"], option_name="custom_models")
    _ = _require_absolute_path(options["custom_model_dir"], option_name="custom_model_dir")
    _ = _require_bool(options["openwakeword_compat"], option_name="openwakeword_compat")
    _ = _require_absolute_path(
        options["openwakeword_model_dir"],
        option_name="openwakeword_model_dir",
    )

    log_level = options["log_level"]
    if log_level not in _ALLOWED_LOG_LEVELS:
        raise AddonConfigValidationError(
            "option 'log_level' must be one of: " + ", ".join(sorted(_ALLOWED_LOG_LEVELS))
        )


def validate_addon_config(config_path: Path, options_path: Path) -> str:
    config = _load_yaml(config_path)
    options = _load_json(options_path)
    _require_keys(config)
    _validate_schema_shape(config)
    _validate_metadata(config)
    _validate_against_schema(config, options)
    return (
        "add-on config validation passed: "
        f"slug={config['slug']} host={options['host']} port={options['port']} backend={options['detector_backend']} custom_models={options['custom_models']}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(validate_addon_config(args.config, args.options))
    except (AddonConfigValidationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
