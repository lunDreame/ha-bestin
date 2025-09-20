"""Config flow to configure BESTIN."""

from __future__ import annotations
from typing import Any

import asyncio
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from homeassistant.const import CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv

from .gateway import BestinGateway
from .const import DOMAIN, LOGGER, DEFAULT_PORT


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BESTIN."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            
            try:
                gateway = BestinGateway(self.hass, entry=None)
                await asyncio.wait_for(gateway.connect(host, port), timeout=5)
            except asyncio.TimeoutError as ex:
                LOGGER.error(f"Connection to {host}:{port} failed due to timeout: {ex}")
                errors["base"] = "connect_failed"
            else:            
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=host, data=user_input)
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }),
            errors=errors
        )
