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
        INTEGRATION_ROOT / "brand" / "icon.png",
        INTEGRATION_ROOT / "brand" / "logo.png",
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
    assert payload["requirements"] == ["wyoming==1.8.0"]
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


def test_helper_integration_strings_expose_options_labels() -> None:
    strings = json.loads(
        (INTEGRATION_ROOT / "strings.json").read_text(encoding="utf-8")
    )
    options = strings["options"]["step"]["init"]

    assert options["data"]["addon_name"] == "Add-on name"
    assert options["data"]["wyoming_host"] == "Wyoming host"
    assert options["data"]["wyoming_port"] == "Wyoming port"
    assert options["data"]["detector_backend"] == "Detector backend"
    assert options["data"]["vad_enabled"] == "Enable VAD"
    assert options["data"]["vad_threshold"] == "VAD threshold"
    assert (
        options["data"]["enable_speex_noise_suppression"]
        == "Enable Speex noise suppression"
    )


def test_helper_notification_copy_mentions_runtime_settings() -> None:
    import importlib.util

    const_path = INTEGRATION_ROOT / "const.py"
    spec = importlib.util.spec_from_file_location("homewakeword_const", const_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper_path = INTEGRATION_ROOT / "helper.py"
    helper_spec = importlib.util.spec_from_file_location(
        "homewakeword_helper", helper_path
    )
    assert helper_spec is not None and helper_spec.loader is not None
    helper_module = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper_module)
    HelperSettings = helper_module.HelperSettings
    ApplyResult = helper_module.ApplyResult
    ConnectivityResult = helper_module.ConnectivityResult
    build_notification_message = helper_module.build_notification_message

    message = build_notification_message(
        HelperSettings(
            addon_name="HomeWakeWord add-on",
            wyoming_host="homewakeword",
            wyoming_port=10700,
            detector_backend="openwakeword",
            vad_enabled=True,
            vad_threshold=0.42,
            speex_enabled=True,
        ),
        ApplyResult(status="applied", detail="options updated and restart requested"),
        ConnectivityResult(
            status="connected",
            detail="received Wyoming info response",
            active_wake_words=("okay_nabu", "hey_jarvis"),
        ),
    )

    assert "Detector backend: `openwakeword`" in message
    assert "VAD enabled: `true`" in message
    assert "VAD threshold: `0.42`" in message
    assert "Speex noise suppression: `true`" in message
    assert "Add-on apply status: `applied`" in message
    assert "Wyoming connectivity: `connected`" in message
    assert "Active wake words: `okay_nabu, hey_jarvis`" in message


def test_helper_payload_maps_options_to_addon_runtime_shape() -> None:
    import importlib.util

    helper_path = INTEGRATION_ROOT / "helper.py"
    helper_spec = importlib.util.spec_from_file_location(
        "homewakeword_helper", helper_path
    )
    assert helper_spec is not None and helper_spec.loader is not None
    helper_module = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper_module)

    payload = helper_module.build_addon_options_payload(
        helper_module.HelperSettings(
            addon_name="HomeWakeWord add-on",
            wyoming_host="homewakeword",
            wyoming_port=10700,
            detector_backend="openwakeword",
            vad_enabled=True,
            vad_threshold=0.33,
            speex_enabled=True,
        )
    )

    assert payload["options"]["host"] == "0.0.0.0"
    assert payload["options"]["port"] == 10700
    assert payload["options"]["detector_backend"] == "openwakeword"
    assert payload["options"]["vad_enabled"] is True
    assert payload["options"]["vad_threshold"] == 0.33
    assert payload["options"]["enable_speex_noise_suppression"] is True


def test_validate_repo_requires_hacs_surface_paths() -> None:
    from scripts.validate_repo import validate_repo

    errors = validate_repo(REPO_ROOT)

    assert "missing required path: hacs.json" not in errors
    assert "missing required path: custom_components/homewakeword" not in errors
    assert (
        "missing required path: custom_components/homewakeword/manifest.json"
        not in errors
    )
