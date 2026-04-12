# pyright: reportMissingImports=false
from __future__ import annotations

from collections.abc import Mapping

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import NOTIFICATION_ID, NOTIFICATION_MESSAGE, NOTIFICATION_TITLE


async def async_setup(hass: HomeAssistant, config: Mapping[str, object]) -> bool:
    del hass, config
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    del entry
    persistent_notification.async_create(
        hass,
        NOTIFICATION_MESSAGE,
        title=NOTIFICATION_TITLE,
        notification_id=NOTIFICATION_ID,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    del entry
    persistent_notification.async_dismiss(hass, NOTIFICATION_ID)
    return True
