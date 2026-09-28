"""Config flow for Swiss Post integration."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .client import SwissPostAuthError, SwissPostClient
from .const import (
    AUTH_TYPE_COOKIES,
    AUTH_TYPE_REFRESH_TOKEN,
    CONF_ACCOUNT_NAME,
    CONF_AUTH_TYPE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_COOKIES,
    CONF_TOKEN_ENDPOINT,
    DEFAULT_ACCOUNT_NAME,
    DEFAULT_CLIENT_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOKEN_ENDPOINT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class SwissPostConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Swiss Post."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: Optional[config_entries.ConfigEntry] = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            account_name = user_input.get(CONF_ACCOUNT_NAME, DEFAULT_ACCOUNT_NAME).strip()
            auth_type = user_input.get(CONF_AUTH_TYPE, AUTH_TYPE_REFRESH_TOKEN)
            refresh_token = user_input.get(CONF_REFRESH_TOKEN)
            session_cookies = user_input.get(CONF_SESSION_COOKIES)

            if auth_type == AUTH_TYPE_REFRESH_TOKEN and not refresh_token:
                errors[CONF_REFRESH_TOKEN] = "missing_refresh_token"
            elif auth_type == AUTH_TYPE_COOKIES and not session_cookies:
                errors[CONF_SESSION_COOKIES] = "missing_session_cookies"
            else:
                def _validate_credentials() -> Dict[str, Any]:
                    client = SwissPostClient(
                        account_name=account_name,
                        refresh_token=refresh_token,
                        session_cookies=session_cookies,
                        client_id=user_input.get(CONF_CLIENT_ID, DEFAULT_CLIENT_ID),
                        token_endpoint=user_input.get(CONF_TOKEN_ENDPOINT, DEFAULT_TOKEN_ENDPOINT),
                    )
                    return client.get_user_info()

                try:
                    user_info = await self.hass.async_add_executor_job(_validate_credentials)
                    user_id = user_info.get("userIdentifier") or account_name

                    # Ensure unique ID per account
                    await self.async_set_unique_id(f"{DOMAIN}_{user_id}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Swiss Post ({account_name})",
                        data=user_input,
                    )
                except SwissPostAuthError:
                    errors["base"] = "invalid_auth"
                except Exception as e:
                    _LOGGER.error("Failed to connect to Swiss Post: %s", e)
                    errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCOUNT_NAME, default=DEFAULT_ACCOUNT_NAME): selector.TextSelector(),
                vol.Required(
                    CONF_AUTH_TYPE,
                    default=AUTH_TYPE_REFRESH_TOKEN,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=AUTH_TYPE_REFRESH_TOKEN,
                                label="Refresh Token (Long-lived mobile app token)",
                            ),
                            selector.SelectOptionDict(
                                value=AUTH_TYPE_COOKIES,
                                label="Session Cookies (service.post.ch web cookies)",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_REFRESH_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_SESSION_COOKIES): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=120, step=5, unit_of_measurement="minutes")
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Dict[str, Any]) -> FlowResult:
        """Handle reauthentication."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Dialog that prompts user to re-enter token or cookie."""
        errors: Dict[str, str] = {}
        if user_input is not None and self._reauth_entry:
            new_data = dict(self._reauth_entry.data)
            new_data.update(user_input)

            def _validate_reauth() -> Dict[str, Any]:
                client = SwissPostClient(
                    account_name=new_data.get(CONF_ACCOUNT_NAME, "Personal"),
                    refresh_token=new_data.get(CONF_REFRESH_TOKEN),
                    session_cookies=new_data.get(CONF_SESSION_COOKIES),
                )
                return client.get_user_info()

            try:
                await self.hass.async_add_executor_job(_validate_reauth)
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=new_data)
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except Exception:
                errors["base"] = "invalid_auth"

        schema = vol.Schema(
            {
                vol.Optional(CONF_REFRESH_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_SESSION_COOKIES): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(step_id="reauth_confirm", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return SwissPostOptionsFlow(config_entry)


class SwissPostOptionsFlow(config_entries.OptionsFlow):
    """Handle Swiss Post options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=120, step=5, unit_of_measurement="minutes")
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
