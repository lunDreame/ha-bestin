"""Config flow to configure BESTIN."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    FlowResult,
    OptionsFlow,
    SOURCE_IMPORT,
)
from homeassistant.const import CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv

from .const import (
    DEFAULT_PORT,
    DEFAULT_MAX_TRANSMISSIONS,
    DEFAULT_TRANSMISSIONS_INTERVAL,
    DOMAIN, 
    LOGGER
)


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BESTIN."""

    VERSION = 1
    data: dict[str, Any]

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)
        
    @staticmethod
    def int_between(
        min_int: int, max_int: int
    ) -> vol.All:
        """Return an integer between 'min_int' and 'max_int'."""
        return vol.All(vol.Coerce(int), vol.Range(min=min_int, max=max_int))
    
    async def async_step_user(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }),
            errors=errors
        )

    async def async_step_import(
        self,
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle configuration by yaml file."""
        await self.async_set_unique_id(user_input[CONF_HOST])
        for entry in self._async_current_entries():
            if entry.unique_id == self.unique_id:
                self.hass.config_entries.async_update_entry(entry, data=user_input)
                self._abort_if_unique_id_configured()
        return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)


class OptionsFlowHandler(OptionsFlow):
    """Handle a option flow for BESTIN."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options flow."""
        if self.config_entry.source == SOURCE_IMPORT:
            return self.async_show_form(step_ip="init", data_schema=None)
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("max_transmissions",
                    default=self.config_entry.options.get(
                        "max_transmissions", DEFAULT_MAX_TRANSMISSIONS
                ): ConfigFlow.int_between(1, 50),
                vol.Required("transmission_interval",
                    default=self.config_entry.options.get(
                        "transmission_interval", DEFAULT_TRANSMISSIONS_INTERVAL
                ): ConfigFlow.int_between(100, 250),
            }),
            errors={},
        )
