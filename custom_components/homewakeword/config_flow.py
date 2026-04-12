# pyright: reportMissingImports=false, reportGeneralTypeIssues=false, reportCallIssue=false
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    ADDON_NAME,
    CONF_ADDON_NAME,
    CONF_WYOMING_HOST,
    CONF_WYOMING_PORT,
    DOMAIN,
    TITLE,
    WYOMING_HOST,
    WYOMING_PORT,
)


def _options_schema(
    *,
    addon_name: str = ADDON_NAME,
    wyoming_host: str = WYOMING_HOST,
    wyoming_port: int = WYOMING_PORT,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ADDON_NAME, default=addon_name): str,
            vol.Required(CONF_WYOMING_HOST, default=wyoming_host): str,
            vol.Required(CONF_WYOMING_PORT, default=wyoming_port): int,
        }
    )


class HomeWakeWordConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title=TITLE,
                data={},
                options={
                    CONF_ADDON_NAME: ADDON_NAME,
                    CONF_WYOMING_HOST: WYOMING_HOST,
                    CONF_WYOMING_PORT: WYOMING_PORT,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "wyoming_host": WYOMING_HOST,
                "wyoming_port": str(WYOMING_PORT),
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "HomeWakeWordOptionsFlow":
        return HomeWakeWordOptionsFlow(config_entry)


class HomeWakeWordOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                addon_name=str(
                    self._config_entry.options.get(CONF_ADDON_NAME, ADDON_NAME)
                ),
                wyoming_host=str(
                    self._config_entry.options.get(CONF_WYOMING_HOST, WYOMING_HOST)
                ),
                wyoming_port=int(
                    self._config_entry.options.get(CONF_WYOMING_PORT, WYOMING_PORT)
                ),
            ),
        )
