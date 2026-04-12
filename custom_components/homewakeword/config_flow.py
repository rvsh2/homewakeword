# pyright: reportMissingImports=false, reportGeneralTypeIssues=false, reportCallIssue=false
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, TITLE, WYOMING_HOST, WYOMING_PORT


class HomeWakeWordConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "wyoming_host": WYOMING_HOST,
                "wyoming_port": str(WYOMING_PORT),
            },
        )
