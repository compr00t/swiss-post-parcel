"""The Swiss Post integration for Home Assistant."""

from __future__ import annotations

import functools
import logging
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .client import SwissPostClient
from .const import (
    CONF_ACCOUNT_NAME,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEVICE_ID,
    CONF_ID_TOKEN,
    CONF_PROFILE_ID,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_COOKIES,
    CONF_TOKEN_ENDPOINT,
    DEFAULT_ACCOUNT_NAME,
    DEFAULT_CLIENT_ID,
    DEFAULT_TOKEN_ENDPOINT,
    DOMAIN,
)
from .coordinator import SwissPostAccountCoordinator, SwissPostConsolidatedData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Swiss Post from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("coordinators", {})

    # Shared consolidator across all accounts
    if "consolidator" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["consolidator"] = SwissPostConsolidatedData(hass)
        hass.data[DOMAIN]["consolidated_entities_added"] = False

    account_name = entry.data.get(CONF_ACCOUNT_NAME, DEFAULT_ACCOUNT_NAME)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    session_cookies = entry.data.get(CONF_SESSION_COOKIES)
    client_id = entry.data.get(CONF_CLIENT_ID, DEFAULT_CLIENT_ID)
    client_secret = entry.data.get(CONF_CLIENT_SECRET)
    token_endpoint = entry.data.get(CONF_TOKEN_ENDPOINT, DEFAULT_TOKEN_ENDPOINT)
    device_id = entry.data.get(CONF_DEVICE_ID)
    profile_id = entry.data.get(CONF_PROFILE_ID)
    id_token = entry.data.get(CONF_ID_TOKEN)

    current_entry_data = dict(entry.data)

    def on_token_refreshed(new_tokens: Dict[str, Any]) -> None:
        """Persist rotated refresh token back to the config entry thread-safely."""
        try:
            _LOGGER.debug("[%s] Saving rotated token to config entry", account_name)
            if "refresh_token" in new_tokens and new_tokens["refresh_token"]:
                current_entry_data[CONF_REFRESH_TOKEN] = new_tokens["refresh_token"]
            if "id_token" in new_tokens and new_tokens["id_token"]:
                current_entry_data[CONF_ID_TOKEN] = new_tokens["id_token"]
            if "profile_id" in new_tokens and new_tokens["profile_id"]:
                current_entry_data[CONF_PROFILE_ID] = new_tokens["profile_id"]

            data_copy = dict(current_entry_data)
            hass.loop.call_soon_threadsafe(
                functools.partial(hass.config_entries.async_update_entry, entry, data=data_copy)
            )
        except Exception as err:
            _LOGGER.error("[%s] Failed to schedule config entry update: %s", account_name, err)

    client = SwissPostClient(
        account_name=account_name,
        refresh_token=refresh_token,
        session_cookies=session_cookies,
        client_id=client_id,
        client_secret=client_secret,
        token_endpoint=token_endpoint,
        device_id=device_id,
        profile_id=profile_id,
        id_token=id_token,
        on_token_refreshed=on_token_refreshed,
    )

    coordinator = SwissPostAccountCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator

    consolidator: SwissPostConsolidatedData = hass.data[DOMAIN]["consolidator"]
    consolidator.register_coordinator(entry.entry_id, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        consolidator: SwissPostConsolidatedData = hass.data[DOMAIN].get("consolidator")
        if consolidator:
            consolidator.unregister_coordinator(entry.entry_id)

        hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)

        # If all entries are removed, reset consolidated entities flag
        if not hass.data[DOMAIN]["coordinators"]:
            hass.data[DOMAIN]["consolidated_entities_added"] = False

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
