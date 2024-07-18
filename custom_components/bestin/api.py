import re
import asyncio
import xmltodict 
import xml.etree.ElementTree as ET

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UUID,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .controller import DeviceProfile
from .const import (
    DOMAIN,
    LOGGER,
    DEVICE_TYPE_MAP,
    DEVICE_PLATFORM_MAP,
)


class BestinAPI:
    """Bestin HDC Smart home API Class."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, version: str
    ) -> None:
        """API initialization."""
        self.hass = hass
        self.config_entry = config_entry
        self.version = version
        self.version_identifier = CONF_USERNAME if self.version == "version1.0" else CONF_UUID
        self.session = async_create_clientsession(self.hass)

    async def _v1_refresh_session(self):
        url = "http://59.7.82.99/webapp/data/getLoginWebApp.php"
        params = {
            "login_ide": self.config_entry.data[CONF_USERNAME],
            "login_pwd": self.config_entry.data[CONF_PASSWORD],
        }
       
        try:
            async with self.session.get(url=url, params=params) as response:
                data = await response.json(content_type="text/html")

                if response.status == 200 and "_fair" not in data["ret"]:
                    cookies = response.cookies
                    new_cookie = {
                        "PHPSESSID": cookies.get("PHPSESSID").value,
                        "user_id": cookies.get("user_id").value,
                        "user_name": cookies.get("user_name").value, 
                    }
                    LOGGER.debug(f"Refresh session successful: {data}, {new_cookie}")
                    self.hass.config_entries.async_update_entry(
                        entry=self.config_entry,
                        title=self.version_identifier,
                        data={**self.config_entry.data, self.version: new_cookie},
                    )
                elif "_fair" in data["ret"]:
                    LOGGER.error(f"Refresh session failed with status 200: Invalid value: {data['msg']}")
                else:
                    LOGGER.error(f"Refresh session failed with status {response.status}: {data}")

        except Exception as ex:
            LOGGER.error(f"Exception during login: {type(ex).__name__}: {ex}")

    async def _v2_refresh_session(self):
        url = "https://center.hdc-smart.com/v3/auth/login"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.config_entry.data[CONF_UUID],
            "User-Agent": "mozilla/5.0 (windows nt 10.0; win64; x64) applewebkit/537.36 (khtml, like gecko) chrome/78.0.3904.70 safari/537.36"
        }

        try:
            async with self.session.post(url=url, headers=headers) as response:
                data = await response.json()

                if response.status == 200:
                    LOGGER.debug(f"Refresh session successful: {data}")
                    self.hass.config_entries.async_update_entry(
                        entry=self.config_entry,
                        title=self.version_identifier,
                        data={**self.config_entry.data, self.version: data},
                    )
                elif response.status == 500:
                    LOGGER.error(f"Login failed with status 500: Server error: {data['err']}")
                else:
                    LOGGER.error(f"Login failed with status {response.status}: {data}")

        except Exception as ex:
            LOGGER.error(f"Exception during login: {type(ex).__name__}: {ex}")
    
    def setup_device(
        self, 
        req_name: str, dev_num: int, unit_num: str, unit_status: str
    ) -> None:
        LOGGER.debug(f"setup_device: {req_name}, {dev_num}, {unit_num}, {unit_status}")
    
    def result_after_request(self, response):
        if self.version == "version1.0":
            try:
                result = xmltodict.parse(response)
                result_data = result["imap"]["service"][0]["@result"]
            except Exception as ex:
                LOGGER.error(f"An error occurred while parsing the response result after the request: {ex}")
        else:
            result_data = response.get("result", None)

        return result_data
    
    async def get_light_status(self, dev_num: int) -> None:
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        cookies = self.config_entry.data[self.version]

        params = {
            "req_name": "remote_access_light",
            "req_action": "status",
            "req_dev_num": dev_num
        }
        if dev_num == 0:
            params["req_name"] = params["req_name"].replace("_light", "_livinglight")
            del params["req_dev_num"]

        try:
            async with self.session.get(url=url, cookies=cookies, params=params) as response:
                response.raise_for_status()  
                try:
                    root = ET.fromstring(await response.text())
                except ET.ParseError as e:
                    LOGGER.error(f"XML parsing error: {e}")
                    return
                
                status_infos = root.findall('.//status_info')
                unit_statuses = [
                    (info.attrib['unit_num'], info.attrib['unit_status'])
                    for info in status_infos
                ]
                for unit_num, unit_status in unit_statuses:
                    self.setup_device("light", dev_num, unit_num, unit_status)
        except Exception as ex:
            LOGGER.error(f"Unexpected error: {type(ex).__name__}: {ex}")

    async def get_outlet_status(self, dev_num: int) -> None:
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        cookies = self.config_entry.data[self.version]

        params = {
            "req_name": "remote_access_electric",
            "req_action": "status",
            "req_dev_num": dev_num
        }
        try:
            async with self.session.get(url=url, cookies=cookies, params=params) as response:
                response.raise_for_status()  
                try:
                    root = ET.fromstring(await response.text())
                except ET.ParseError as e:
                    LOGGER.error(f"XML parsing error: {e}")
                    return
                
                status_infos = root.findall('.//status_info')
                unit_statuses = [
                    (info.attrib['unit_num'], info.attrib['unit_status'])
                    for info in status_infos
                ]
                for unit_num, unit_status in unit_statuses:
                    self.setup_device("outlet", dev_num, unit_num, unit_status)
        except Exception as ex:
            LOGGER.error(f"Unexpected error: {type(ex).__name__}: {ex}")

    async def get_thermostat_status(self, dev_num: int) -> None:
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        cookies = self.config_entry.data[self.version]

        params = {
            "req_name": "remote_access_temper",
            "req_action": 'status',
            "req_unit_num": f"room{dev_num}"
        }
        try:
            async with self.session.get(url=url, cookies=cookies, params=params) as response:
                response.raise_for_status()  
                try:
                    root = ET.fromstring(await response.text())
                except ET.ParseError as e:
                    LOGGER.error(f"XML parsing error: {e}")
                    return
                
                status_infos = root.findall('.//status_info')
                unit_statuses = [
                    (info.attrib['unit_num'], info.attrib['unit_status'])
                    for info in status_infos
                ]
                for unit_num, unit_status in unit_statuses:
                    self.setup_device("thermostat", dev_num, unit_num, unit_status)
        except Exception as ex:
            LOGGER.error(f"Unexpected error: {type(ex).__name__}: {ex}")

    async def setup_initial_control_list(self):
        tasks = []
    
        if self.version == "version1.0":
            tasks = [self.get_light_status(dev_num) for dev_num in range(6)]
            tasks += [self.get_outlet_status(dev_num) for dev_num in range(1, 6)]
            tasks += [self.get_thermostat_status(dev_num) for dev_num in range(1, 6)]
        
            await asyncio.gather(*tasks)
        else:
            LOGGER.warning("Version 2.0 is not yet supported.")
