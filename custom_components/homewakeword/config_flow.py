# pyright: reportMissingImports=false, reportGeneralTypeIssues=false, reportCallIssue=false
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    ADDON_NAME,
    CONF_ADDON_NAME,
    CONF_DETECTOR_BACKEND,
    CONF_ENABLE_SPEEX_NOISE_SUPPRESSION,
    CONF_VAD_ENABLED,
    CONF_VAD_THRESHOLD,
    CONF_WYOMING_HOST,
    CONF_WYOMING_PORT,
    DETECTOR_BACKEND,
    DOMAIN,
    SPEEX_ENABLED,
    TITLE,
    VAD_ENABLED,
    VAD_THRESHOLD,
    WYOMING_HOST,
    WYOMING_PORT,
)


def _options_schema(
    *,
    addon_name: str = ADDON_NAME,
    wyoming_host: str = WYOMING_HOST,
    wyoming_port: int = WYOMING_PORT,
    detector_backend: str = DETECTOR_BACKEND,
    vad_enabled: bool = VAD_ENABLED,
    vad_threshold: float = VAD_THRESHOLD,
    enable_speex_noise_suppression: bool = SPEEX_ENABLED,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ADDON_NAME, default=addon_name): str,
            vol.Required(CONF_WYOMING_HOST, default=wyoming_host): str,
            vol.Required(CONF_WYOMING_PORT, default=wyoming_port): int,
            vol.Required(CONF_DETECTOR_BACKEND, default=detector_backend): vol.In(
                ["bcresnet", "openwakeword"]
            ),
            vol.Required(CONF_VAD_ENABLED, default=vad_enabled): bool,
            vol.Required(CONF_VAD_THRESHOLD, default=vad_threshold): vol.All(
                vol.Coerce(float), vol.Range(min=0.0, max=1.0)
            ),
            vol.Required(
                CONF_ENABLE_SPEEX_NOISE_SUPPRESSION,
                default=enable_speex_noise_suppression,
            ): bool,
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
                    CONF_DETECTOR_BACKEND: DETECTOR_BACKEND,
                    CONF_VAD_ENABLED: VAD_ENABLED,
                    CONF_VAD_THRESHOLD: VAD_THRESHOLD,
                    CONF_ENABLE_SPEEX_NOISE_SUPPRESSION: SPEEX_ENABLED,
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
        super().__init__()
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
                detector_backend=str(
                    self._config_entry.options.get(
                        CONF_DETECTOR_BACKEND, DETECTOR_BACKEND
                    )
                ),
                vad_enabled=bool(
                    self._config_entry.options.get(CONF_VAD_ENABLED, VAD_ENABLED)
                ),
                vad_threshold=float(
                    self._config_entry.options.get(CONF_VAD_THRESHOLD, VAD_THRESHOLD)
                ),
                enable_speex_noise_suppression=bool(
                    self._config_entry.options.get(
                        CONF_ENABLE_SPEEX_NOISE_SUPPRESSION, SPEEX_ENABLED
                    )
                ),
            ),
        )
