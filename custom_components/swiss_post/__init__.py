"""The Swiss Post integration for Home Assistant."""

from __future__ import annotations

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

    def on_token_refreshed(new_tokens: Dict[str, Any]) -> None:
        """Persist rotated refresh token back to the config entry."""
        _LOGGER.debug("[%s] Saving rotated token to config entry", account_name)
        new_data = dict(entry.data)
        if "refresh_token" in new_tokens and new_tokens["refresh_token"]:
            new_data[CONF_REFRESH_TOKEN] = new_tokens["refresh_token"]
        hass.config_entries.async_update_entry(entry, data=new_data)

    client = SwissPostClient(
        account_name=account_name,
        refresh_token=refresh_token,
        session_cookies=session_cookies,
        client_id=client_id,
        client_secret=client_secret,
        token_endpoint=token_endpoint,
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
