from dataclasses import dataclass
import importlib.util
from pathlib import Path

try:
    from .const import (
        ADDON_NAME,
        DETECTOR_BACKEND,
        SPEEX_ENABLED,
        VAD_ENABLED,
        VAD_THRESHOLD,
        WYOMING_HOST,
        WYOMING_PORT,
    )

    _default_addon_name = ADDON_NAME
    _default_detector_backend = DETECTOR_BACKEND
    _default_speex_enabled = SPEEX_ENABLED
    _default_vad_enabled = VAD_ENABLED
    _default_vad_threshold = VAD_THRESHOLD
    _default_wyoming_host = WYOMING_HOST
    _default_wyoming_port = WYOMING_PORT
except ImportError:  # pragma: no cover - test loader fallback
    const_path = Path(__file__).with_name("const.py")
    spec = importlib.util.spec_from_file_location(
        "homewakeword_const_fallback", const_path
    )
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _default_addon_name = module.ADDON_NAME
        _default_detector_backend = module.DETECTOR_BACKEND
        _default_speex_enabled = module.SPEEX_ENABLED
        _default_vad_enabled = module.VAD_ENABLED
        _default_vad_threshold = module.VAD_THRESHOLD
        _default_wyoming_host = module.WYOMING_HOST
        _default_wyoming_port = module.WYOMING_PORT
    else:  # pragma: no cover - extreme fallback
        _default_addon_name = "HomeWakeWord add-on"
        _default_detector_backend = "bcresnet"
        _default_speex_enabled = False
        _default_vad_enabled = False
        _default_vad_threshold = 0.5
        _default_wyoming_host = "homewakeword"
        _default_wyoming_port = 10700


@dataclass(frozen=True, slots=True)
class HelperSettings:
    addon_name: str = _default_addon_name
    wyoming_host: str = _default_wyoming_host
    wyoming_port: int = _default_wyoming_port
    detector_backend: str = _default_detector_backend
    vad_enabled: bool = _default_vad_enabled
    vad_threshold: float = _default_vad_threshold
    speex_enabled: bool = _default_speex_enabled


@dataclass(frozen=True, slots=True)
class ApplyResult:
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ConnectivityResult:
    status: str
    detail: str
    active_wake_words: tuple[str, ...] = ()


def build_addon_options_payload(settings: HelperSettings) -> dict[str, object]:
    return {
        "options": {
            "host": "0.0.0.0",
            "port": settings.wyoming_port,
            "detector_backend": settings.detector_backend,
            "manifest": "/app/models/bcresnet-real/manifest.yaml",
            "custom_models": True,
            "custom_model_dir": "/share/homewakeword/models",
            "openwakeword_compat": False,
            "openwakeword_model_dir": "/share/openwakeword",
            "enable_speex_noise_suppression": settings.speex_enabled,
            "vad_enabled": settings.vad_enabled,
            "vad_threshold": settings.vad_threshold,
            "log_level": "info",
        }
    }


def build_notification_message(
    settings: HelperSettings,
    apply_result: ApplyResult | None,
    connectivity_result: ConnectivityResult | None = None,
) -> str:
    status_line = "Add-on apply status: `not attempted`"
    if apply_result is not None:
        status_line = (
            f"Add-on apply status: `{apply_result.status}` ({apply_result.detail})"
        )

    connectivity_line = "Wyoming connectivity: `not checked`"
    wake_words_line = "Active wake words: `unknown`"
    if connectivity_result is not None:
        connectivity_line = f"Wyoming connectivity: `{connectivity_result.status}` ({connectivity_result.detail})"
        if connectivity_result.active_wake_words:
            wake_words_line = (
                "Active wake words: `"
                + ", ".join(connectivity_result.active_wake_words)
                + "`"
            )
        else:
            wake_words_line = "Active wake words: `none reported`"

    return (
        "HomeWakeWord installed from HACS is a helper integration. "
        f"It can try to push supported settings to the {settings.addon_name} and request a restart when Supervisor API access is available. "
        "It does not install, manage, or proxy the add-on runtime by itself.\n\n"
        f"Use Home Assistant's built-in Wyoming integration with host `{settings.wyoming_host}` and port `{settings.wyoming_port}`.\n\n"
        "Current helper settings:\n"
        f"- Detector backend: `{settings.detector_backend}`\n"
        f"- VAD enabled: `{str(settings.vad_enabled).lower()}`\n"
        f"- VAD threshold: `{settings.vad_threshold}`\n"
        f"- Speex noise suppression: `{str(settings.speex_enabled).lower()}`\n"
        f"- {status_line}\n"
        f"- {connectivity_line}\n"
        f"- {wake_words_line}"
    )
