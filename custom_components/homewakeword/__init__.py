# pyright: reportMissingImports=false
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import os

from homeassistant.helpers.aiohttp_client import async_get_clientsession
import aiohttp
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    ADDON_NAME,
    ADDON_SLUG,
    CONF_ADDON_NAME,
    CONF_DETECTOR_BACKEND,
    CONF_ENABLE_SPEEX_NOISE_SUPPRESSION,
    CONF_VAD_ENABLED,
    CONF_VAD_THRESHOLD,
    CONF_WYOMING_HOST,
    CONF_WYOMING_PORT,
    DETECTOR_BACKEND,
    NOTIFICATION_ID,
    NOTIFICATION_TITLE,
    SPEEX_ENABLED,
    VAD_ENABLED,
    VAD_THRESHOLD,
    WYOMING_HOST,
    WYOMING_PORT,
)
from .helper import (
    ApplyResult,
    ConnectivityResult,
    HelperSettings,
    build_addon_options_payload,
    build_notification_message,
)


async def async_setup(hass: HomeAssistant, config: Mapping[str, object]) -> bool:
    del hass, config
    return True


async def _apply_addon_options(
    hass: HomeAssistant, settings: HelperSettings
) -> ApplyResult:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return ApplyResult(status="not_available", detail="Supervisor API unavailable")

    session = async_get_clientsession(hass)
    headers = {aiohttp.hdrs.AUTHORIZATION: f"Bearer {token}"}
    payload = build_addon_options_payload(settings)
    try:
        async with session.post(
            f"http://supervisor/addons/{ADDON_SLUG}/options",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                body = await response.text()
                return ApplyResult(
                    status="failed",
                    detail=f"options update failed ({response.status}): {body[:120]}",
                )
        async with session.post(
            f"http://supervisor/addons/{ADDON_SLUG}/restart",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                body = await response.text()
                return ApplyResult(
                    status="failed",
                    detail=f"restart failed ({response.status}): {body[:120]}",
                )
    except Exception as exc:
        return ApplyResult(status="failed", detail=str(exc))
    return ApplyResult(status="applied", detail="options updated and restart requested")


async def _show_notification(hass: HomeAssistant, entry: ConfigEntry) -> None:
    settings = HelperSettings(
        addon_name=str(entry.options.get(CONF_ADDON_NAME, ADDON_NAME)),
        wyoming_host=str(entry.options.get(CONF_WYOMING_HOST, WYOMING_HOST)),
        wyoming_port=int(entry.options.get(CONF_WYOMING_PORT, WYOMING_PORT)),
        detector_backend=str(
            entry.options.get(CONF_DETECTOR_BACKEND, DETECTOR_BACKEND)
        ),
        vad_enabled=bool(entry.options.get(CONF_VAD_ENABLED, VAD_ENABLED)),
        vad_threshold=float(entry.options.get(CONF_VAD_THRESHOLD, VAD_THRESHOLD)),
        speex_enabled=bool(
            entry.options.get(CONF_ENABLE_SPEEX_NOISE_SUPPRESSION, SPEEX_ENABLED)
        ),
    )
    apply_result = await _apply_addon_options(hass, settings)
    connectivity_result = await _check_wyoming_connectivity(settings)
    persistent_notification.async_create(
        hass,
        build_notification_message(settings, apply_result, connectivity_result),
        title=NOTIFICATION_TITLE,
        notification_id=NOTIFICATION_ID,
    )


async def _check_wyoming_connectivity(settings: HelperSettings) -> ConnectivityResult:
    try:
        from wyoming.client import AsyncClient
        from wyoming.info import Describe, Info
    except Exception as exc:  # pragma: no cover - dependency/runtime specific
        return ConnectivityResult(status="unavailable", detail=str(exc))

    try:
        client = AsyncClient.from_uri(
            f"tcp://{settings.wyoming_host}:{settings.wyoming_port}"
        )
        await client.connect()
        try:
            await client.write_event(Describe().event())
            event = await asyncio.wait_for(client.read_event(), timeout=3)
        finally:
            try:
                await client.disconnect()
            except BaseException:
                pass
    except Exception as exc:
        return ConnectivityResult(status="failed", detail=str(exc))

    if event is None:
        return ConnectivityResult(
            status="failed", detail="no response from Wyoming service"
        )
    if event.type != "info":
        return ConnectivityResult(
            status="failed", detail=f"unexpected response type: {event.type}"
        )
    try:
        info = Info.from_event(event)
    except Exception as exc:
        return ConnectivityResult(
            status="failed", detail=f"invalid info response: {exc}"
        )

    wake_words: list[str] = []
    for wake_program in info.wake:
        for model in wake_program.models:
            wake_words.append(model.name)
    return ConnectivityResult(
        status="connected",
        detail="received Wyoming info response",
        active_wake_words=tuple(wake_words),
    )


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await _show_notification(hass, entry)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await _show_notification(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    del entry
    persistent_notification.async_dismiss(hass, NOTIFICATION_ID)
    return True
