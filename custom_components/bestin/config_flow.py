"""Config flow to configure BESTIN."""

from __future__ import annotations
from typing import Any

import voluptuous as vol

from homeassistant.core import callback
from homeassistant.config_entries import (
    ConfigFlow, 
    ConfigEntry,
    FlowResult,
    OptionsFlow,
    SOURCE_IMPORT,
)
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UUID,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
import homeassistant.helpers.config_validation as cv

from homeassistant.helpers.selector import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import (
    DOMAIN,
    LOGGER,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_MAX_TRANSMISSION,
    DEFAULT_PACKET_VIEWER,
)


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BESTIN."""

    VERSION = 1
    data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(entry)
    
    @staticmethod
    def int_between(min_int, max_int):
        """Return an integer between "min_int" and "max_int"."""
        return vol.All(vol.Coerce(int), vol.Range(min=min_int, max=max_int))

    async def async_step_user(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return self.async_show_menu(step_id="user", menu_options=["local", "center"])

    async def async_step_local(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the local communication."""
        errors = {}

        if user_input is not None:
            self.data.update(user_input)
            self.config_identifier = CONF_HOST

            await self.async_set_unique_id(user_input[CONF_HOST])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_HOST], data=self.data)
        
        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }),
            errors=errors
        )

    async def _v1_server_login(self, session) -> Any:
        """Login to HDC v1 server."""
        url = f"http://{self.data[CONF_IP_ADDRESS]}/webapp/data/getLoginWebApp.php"
        params = {
            "login_ide": self.data[CONF_USERNAME],
            "login_pwd": self.data[CONF_PASSWORD],
        }

        try:
            async with session.get(url=url, params=params, timeout=5) as response:
                response_data = await response.json(content_type="text/html")

                if response.status == 200 and "_fair" not in response_data["ret"]:
                    cookies = response.cookies
                    new_cookie = {
                        "PHPSESSID": cookies.get("PHPSESSID").value if cookies.get("PHPSESSID") else None,
                        "user_id": cookies.get("user_id").value if cookies.get("user_id") else None,
                        "user_name": cookies.get("user_name").value if cookies.get("user_name") else None,
                    }
                    LOGGER.info(f"V1 Login successful. Response data: {response_data}. Cookies: {new_cookie}")
                    return new_cookie, None
                elif "_fair" in response_data["ret"]:
                    LOGGER.error(f"V1 Login failed (status 200): Invalid credentials. Message: {response_data['msg']}")
                    return None, ("error_login", response_data["msg"])
                else:
                    LOGGER.error(f"V1 Login failed. Status: {response.status}. Response data: {response_data}")
                    return None, ("error_network", None)

        except Exception as ex:
            LOGGER.error(f"V1 Login exception: {type(ex).__name__}. Details: {ex}")
            return None, ("error_network", None)

    async def _v2_server_login(self, session) -> Any:
        """Login to HDC v2 server."""
        url = "https://center.hdc-smart.com/v3/auth/login"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.data[CONF_UUID],
            "User-Agent": "mozilla/5.0 (windows nt 10.0; win64; x64) applewebkit/537.36 (khtml, like gecko) chrome/78.0.3904.70 safari/537.36"
        }

        try:
            async with session.post(url=url, headers=headers, timeout=5) as response:
                response_data = await response.json()
        
                if response.status == 200:
                    LOGGER.info(f"V2 Login successful. Response data: {response_data}")
                    return response_data, None
                elif response.status == 500:
                    LOGGER.error(f"V2 Login failed (status 500): Server error. Error message: {response_data['err']}")
                    return None, ("error_login", response_data["err"])
                else:
                    LOGGER.error(f"V2 Login failed. Status: {response.status}. Response data: {response_data}")
                    return None, ("error_network", None)
                
        except Exception as ex:
            LOGGER.error(f"V2 Login exception: {type(ex).__name__}. Details: {ex}")
            return None, ("error_network", None)

    async def async_step_center(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the center version selection."""
        errors = {}

        if user_input is not None:
            self.data.update(user_input)
            self.center_version = user_input["version"]
            if self.center_version == "version1.0":
                self.config_identifier = CONF_USERNAME
                return await self.async_step_center_v1()
            else:
                self.config_identifier = CONF_UUID
                return await self.async_step_center_v2()

        data_schema = vol.Schema({
            "version": selector({
                "select": {
                    "options": ["version1.0", "version2.0"],
                    "mode": "dropdown",
                }
            })
        })

        return self.async_show_form(
            step_id="center",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_center_v1(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the center v1."""
        errors = {}
        description_placeholders = None  

        if user_input is not None:
            self.data.update({**user_input, "identifier": self.config_identifier})
            session = async_create_clientsession(self.hass)

            response, error_message = await self._v1_server_login(session)

            if error_message:
                errors["base"] = error_message[0]
                description_placeholders = {"err": error_message[1]}
            else:
                self.data[self.center_version] = response
                await self.async_set_unique_id(user_input[self.config_identifier])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[self.config_identifier], data=self.data)

        data_schema = vol.Schema({
            vol.Required(CONF_IP_ADDRESS): cv.string,
            vol.Required(CONF_USERNAME): cv.string,
            vol.Required(CONF_PASSWORD): cv.string,
        })

        return self.async_show_form(
            step_id="center_v1",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders
        )

    async def async_step_center_v2(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the center v2."""
        errors = {}
        description_placeholders = None  

        if user_input is not None:
            self.data.update({**user_input, "identifier": self.config_identifier})
            session = async_create_clientsession(self.hass)

            response, error_message = await self._v2_server_login(session)

            if error_message:
                errors["base"] = error_message[0]
                description_placeholders = {"err": error_message[1]["msg"]}
            else:
                self.data[self.center_version] = response
                await self.async_set_unique_id(user_input[self.config_identifier])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[self.config_identifier], data=self.data)

        data_schema = vol.Schema({
            vol.Required("elevator_number", default=1): ConfigFlow.int_between(1, 3),
            vol.Optional(CONF_IP_ADDRESS): cv.string,
            vol.Required(CONF_UUID): cv.string,
        })

        return self.async_show_form(
            step_id="center_v2",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders
        )
    
    async def async_step_import(
        self,
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle configuration by yaml file."""
        await self.async_set_unique_id(user_input[self.config_identifier]) 
        for entry in self._async_current_entries():
            if entry.unique_id == self.unique_id:
                self.hass.config_entries.async_update_entry(entry, data=user_input) 
                self._abort_if_unique_id_configured()
        return self.async_create_entry(title=user_input[self.config_identifier], data=user_input)


class OptionsFlowHandler(OptionsFlow):
    """Handle an option flow for BESTIN."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.entry = entry

    async def async_step_init(
        self, 
        user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options flow."""
        errors = {}

        if self.entry.source == SOURCE_IMPORT:
            return self.async_show_form(step_id="init", data_schema=None)
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "max_transmission", 
                    default=self.entry.options.get("max_transmission", DEFAULT_MAX_TRANSMISSION)
                ): ConfigFlow.int_between(1, 50),
                vol.Required(
                    "packet_viewer",
                    default=self.entry.options.get("packet_viewer", DEFAULT_PACKET_VIEWER)
                ): cv.boolean,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): cv.positive_int,
            }),
            errors=errors
        )
