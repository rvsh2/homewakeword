from __future__ import annotations

DOMAIN = "homewakeword"
TITLE = "HomeWakeWord"
ADDON_NAME = "HomeWakeWord add-on"
BUILT_IN_WYOMING_NAME = "Wyoming"
WYOMING_HOST = "homewakeword"
WYOMING_PORT = 10700
NOTIFICATION_ID = f"{DOMAIN}_onboarding"
NOTIFICATION_TITLE = "HomeWakeWord setup"
NOTIFICATION_MESSAGE = (
    "HomeWakeWord installed from HACS is only a helper integration. "
    "Install and start the HomeWakeWord add-on separately, then add Home Assistant's "
    "built-in Wyoming integration and point it to host `homewakeword` on port `10700`. "
    "This helper does not install, manage, or proxy the runtime."
)
