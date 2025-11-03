"""Config flow for Bestin integration."""

from __future__ import annotations

from typing import Any
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, DEFAULT_PORT


class BestinConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bestin."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}
        
        if user_input is not None:
            host = user_input[CONF_HOST]
            
            if not (re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host) 
                    or re.match(r"^/dev/tty(USB|AMA)\d+$", host)):
                errors["base"] = "invalid_host"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=host,
                    data=user_input,
                )
        
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            }),
            errors=errors,
        )
