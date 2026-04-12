from __future__ import annotations

DOMAIN = "homewakeword"
TITLE = "HomeWakeWord"
ADDON_NAME = "HomeWakeWord add-on"
BUILT_IN_WYOMING_NAME = "Wyoming"
WYOMING_HOST = "homewakeword"
WYOMING_PORT = 10700
CONF_ADDON_NAME = "addon_name"
CONF_WYOMING_HOST = "wyoming_host"
CONF_WYOMING_PORT = "wyoming_port"
NOTIFICATION_ID = f"{DOMAIN}_onboarding"
NOTIFICATION_TITLE = "HomeWakeWord setup"


def build_notification_message(
    *, addon_name: str, wyoming_host: str, wyoming_port: int
) -> str:
    return (
        "HomeWakeWord installed from HACS is only a helper integration. "
        f"Install and start the {addon_name} separately, then add Home Assistant's "
        f"built-in Wyoming integration and point it to host `{wyoming_host}` on port `{wyoming_port}`. "
        "This helper does not install, manage, or proxy the runtime."
    )
