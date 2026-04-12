# pyright: reportMissingImports=false
from __future__ import annotations

from collections.abc import Mapping

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ADDON_NAME,
    CONF_ADDON_NAME,
    CONF_WYOMING_HOST,
    CONF_WYOMING_PORT,
    NOTIFICATION_ID,
    NOTIFICATION_TITLE,
    WYOMING_HOST,
    WYOMING_PORT,
    build_notification_message,
)


async def async_setup(hass: HomeAssistant, config: Mapping[str, object]) -> bool:
    del hass, config
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    addon_name = str(entry.options.get(CONF_ADDON_NAME, ADDON_NAME))
    wyoming_host = str(entry.options.get(CONF_WYOMING_HOST, WYOMING_HOST))
    wyoming_port = int(entry.options.get(CONF_WYOMING_PORT, WYOMING_PORT))
    persistent_notification.async_create(
        hass,
        build_notification_message(
            addon_name=addon_name,
            wyoming_host=wyoming_host,
            wyoming_port=wyoming_port,
        ),
        title=NOTIFICATION_TITLE,
        notification_id=NOTIFICATION_ID,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    del entry
    persistent_notification.async_dismiss(hass, NOTIFICATION_ID)
    return True
