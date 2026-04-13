from dataclasses import dataclass

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
except ImportError:  # pragma: no cover - test loader fallback
    ADDON_NAME = "HomeWakeWord add-on"
    DETECTOR_BACKEND = "bcresnet"
    SPEEX_ENABLED = False
    VAD_ENABLED = False
    VAD_THRESHOLD = 0.5
    WYOMING_HOST = "homewakeword"
    WYOMING_PORT = 10700


@dataclass(frozen=True, slots=True)
class HelperSettings:
    addon_name: str = ADDON_NAME
    wyoming_host: str = WYOMING_HOST
    wyoming_port: int = WYOMING_PORT
    detector_backend: str = DETECTOR_BACKEND
    vad_enabled: bool = VAD_ENABLED
    vad_threshold: float = VAD_THRESHOLD
    speex_enabled: bool = SPEEX_ENABLED


@dataclass(frozen=True, slots=True)
class ApplyResult:
    status: str
    detail: str


def build_addon_options_payload(settings: HelperSettings) -> dict[str, object]:
    return {
        "options": {
            "host": "0.0.0.0",
            "port": settings.wyoming_port,
            "detector_backend": settings.detector_backend,
            "manifest": "/app/models/manifest.yaml",
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
    settings: HelperSettings, apply_result: ApplyResult | None
) -> str:
    status_line = "Add-on apply status: `not attempted`"
    if apply_result is not None:
        status_line = (
            f"Add-on apply status: `{apply_result.status}` ({apply_result.detail})"
        )

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
        f"- {status_line}"
    )
