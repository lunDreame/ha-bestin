import re
import hashlib
import base64
import asyncio
import xmltodict  # type: ignore
import xml.etree.ElementTree as ET
import ssl
import aiohttp
import json
import requests
import sseclient # type: ignore

from datetime import timedelta
from typing import Any, Callable, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate import HVACMode
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import (
    Platform,
    CONF_IP_ADDRESS,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UUID,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant, callback

from .controller import DeviceProfile
from .const import (
    DOMAIN,
    LOGGER,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_TYPE_MAP,
    DEVICE_PLATFORM_MAP,
    SPEED_STR_LOW,
    SPEED_STR_MEDIUM,
    SPEED_STR_HIGH,
)

class BestinAPI:
    """Bestin HDC Smart home API Class."""

    def __init__(
        self, 
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        entities: dict,
        gatewayid: str,
        version: str,
        version_identifier: str,
        async_add_device: Callable
    ) -> None:
        """API initialization."""
        self.hass = hass
        self.config_entry = config_entry
        self.entities = entities
        self.gatewayid = gatewayid
        self.version = version
        self.version_identifier = version_identifier
        self.async_add_device = async_add_device

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self.session = aiohttp.ClientSession(connector=connector)

        self.tasks: list = []
        self.remove_callbacks: list = []
        self.stop_event = asyncio.Event()

        # version 2
        self.sse_client: sseclient.SSEClient = None
        self.features_list: list = []  
        self.elev_moveinfo: dict = {}

        self.devices: dict[str, dict] = {}
        self.interval: int = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    def get_short_hash(self, id: str) -> str:
        """Generate a short hash for a given id."""
        hash_object = hashlib.sha256(id.encode()).digest()
        return base64.urlsafe_b64encode(hash_object)[:8].decode("utf-8")

    async def start(self) -> None:
        """Start main loop with asyncio."""
        self.stop_event.clear()
        self.tasks.append(asyncio.create_task(self.schedule_session_refresh()))
        await asyncio.sleep(1)
        asyncio.create_task(self.get_device_status())
        self.remove_callbacks.append(
            async_track_time_interval(self.hass, self._device_status_wrapper, timedelta(minutes=self.interval))
        )

    async def stop(self) -> None:
        """Stop main loop and cancel all tasks."""
        self.stop_event.set()
        if len(self.tasks) > 0:
            for task in self.tasks:
                task.cancel()
        if len(self.remove_callbacks) > 0:
            for callback in self.remove_callbacks:
                callback()

    async def _device_status_wrapper(self, *_) -> None:
        """Wrapper for update to handle interval tracking."""
        LOGGER.debug("Scheduled task execution started at: %s", _)
        asyncio.create_task(self.get_device_status())

    async def _refresh_session(
        self, url: str, headers: dict = None, params: dict = None, response_key: str = None
    ) -> None:
        """Refresh session."""
        try:
            if response_key == "ret":
                async with self.session.get(url=url, headers=headers, params=params) as response:
                    response_data = await response.json(content_type="text/html")
            else:
                async with self.session.post(url=url, headers=headers, params=params) as response:
                    response_data = await response.json()

                if response.status != 200:
                    LOGGER.error(f"Login failed: {response.status} {response_data}")
                    return
                if any(key in response_data.get(response_key, response_data) for key in ("_fair", "err")):
                    LOGGER.error(f"Session refresh failed: {response_data.get('msg', 'err')}")
                    return
            
                new_cookie = None
                if response_key == "ret":
                    cookies = response.cookies
                    new_cookie = {
                        "PHPSESSID": cookies.get("PHPSESSID").value if cookies.get("PHPSESSID") else None,
                        "user_id": cookies.get("user_id").value if cookies.get("user_id") else None,
                        "user_name": cookies.get("user_name").value if cookies.get("user_name") else None,
                    }
                LOGGER.debug(f"Session refreshed: {response_data}, Cookie: {new_cookie}")
                self.hass.config_entries.async_update_entry(
                    entry=self.config_entry,
                    title=self.config_entry.data[self.version_identifier],
                    data={**self.config_entry.data, self.version: new_cookie if new_cookie else response_data},
                )
                await asyncio.sleep(1)
        except Exception as ex:
            LOGGER.error(f"Exception during session refresh: {type(ex).__name__}: {ex}")

    async def _v1_refresh_session(self):
        """Refresh session for version 1."""
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/webapp/data/getLoginWebApp.php"
        params = {
            "login_ide": self.config_entry.data[CONF_USERNAME],
            "login_pwd": self.config_entry.data[CONF_PASSWORD],
        }
        await self._refresh_session(url, params=params, response_key="ret")

    async def _v2_refresh_session(self):
        """Refresh session for version 2."""
        url = "https://center.hdc-smart.com/v3/auth/login"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.config_entry.data[CONF_UUID],
            "User-Agent": "mozilla/5.0 (windows nt 10.0; win64; x64) applewebkit/537.36 (khtml, like gecko) chrome/78.0.3904.70 safari/537.36"
        }
        await self._refresh_session(url, headers=headers)

    @callback
    async def on_command(
        self, unique_id: str, value: Any, **kwargs: dict | None
    ) -> None:
        """Handle commands to the devices."""
        parts = unique_id.split("-")[0].split("_")
        device_type = parts[1]
        room_id = int(parts[2])
        pos_id = 0
        sub_type = ""

        if len(parts) > 3:
            if parts[3].isdigit():
                pos_id = int(parts[3])
            else:
                sub_type = parts[3]
        if len(parts) > 4:
            pos_id = int(parts[4])
            sub_type = parts[3]
        if kwargs:
            sub_type, value = next(iter(kwargs.items()))
            
        LOGGER.debug(
            "parsed values - device_type: %s, room_id: %s, pos_id: %s, sub_type: %s",
            device_type, room_id, pos_id, sub_type
        )
        if device_type[0] == "elevator":
            await self.request_elevator()
        else:
            if self.version == "version1.0":
                pass
            else:
                if device_type == "light":
                    device_type = "livinglight" if room_id == 0 else "light"
                    room_id = 1
                elif device_type == "outlet" and sub_type == "cutoff":
                    sub_type = "switch"
                    value = "set" if value == "on" else "unset"
                elif device_type == "thermostat":
                    pos_id = room_id
                    room_id = 1
                elif device_type == "fan":
                    device_type = "ventil"
                elif device_type == "gas":
                    sub_type = "gas"
                    value = "open" if value == "on" else "close"

                unit_id = f"{sub_type or 'switch'}{pos_id}"
                LOGGER.debug(
                    "device_map values - device_type: %s, room_id: %s, unit_id: %s, value: %s",
                    device_type, room_id, unit_id, value
                )
                await self.request_feature(device_type, room_id, unit_id, value)

    def convert_unique_id(self, unique_id: str) -> tuple[str] | None:
        """Convert unique ID to device and unit ID."""
        parts = unique_id.split("-")[0].split("_")
        if len(parts) > 3:
            unit_id = "_".join(parts[3:])
            device_id = "_".join(parts[1:3])
        else:
            unit_id = None
            device_id = "_".join(parts[1:3])
        return device_id, unit_id

    def get_devices_from_domain(self, domain: str) -> list[dict]:
        """Get devices from a specific domain."""
        entity_list = self.entities.get(domain, set())
        return [self.initialize_device(*self.convert_unique_id(uid), None) for uid in entity_list]

    @property
    def lights(self) -> list:
        """Get light devices."""
        return self.get_devices_from_domain(Platform.LIGHT)

    @property
    def switchs(self) -> list:
        """Get switch devices."""
        return self.get_devices_from_domain(Platform.SWITCH)

    @property
    def sensors(self) -> list:
        """Get sensor devices."""
        return self.get_devices_from_domain(Platform.SENSOR)

    @property
    def climates(self) -> list:
        """Get climate devices."""
        return self.get_devices_from_domain(Platform.CLIMATE)

    @property
    def fans(self) -> list:
        """Get fan devices."""
        return self.get_devices_from_domain(Platform.FAN)

    def on_register(self, unique_id: str, update: Callable) -> None:
        """Register a callback for a device."""
        self.devices[unique_id].on_update = update
        LOGGER.debug(f"Callback registered for device: {unique_id}")

    def on_remove(self, unique_id: str) -> None:
        """Remove a callback for a device."""
        self.devices[unique_id].on_update = None
        LOGGER.debug(f"Callback removed for device: {unique_id}")

    def initialize_device(
        self, device_id: str, unit_id: str | None, status: bool | dict
    ) -> dict[str, dict]:
        """Initialize a device."""
        device_type, device_room = device_id.split("_")
        base_unique_id = f"bestin_{device_id}"
        unique_id = f"{base_unique_id}_{unit_id}" if unit_id else base_unique_id
        full_unique_id = f"{unique_id}-{self.get_short_hash(self.gatewayid)}"

        if device_type != "energy" and (unit_id and not unit_id.isdigit()):
            letter_sub_id = "".join(re.findall(r'[a-zA-Z]', unit_id))
            device_type = f"{device_type}:{letter_sub_id}"

        platform = DEVICE_PLATFORM_MAP.get(device_type)
        if not platform:
            raise ValueError(f"Unsupported platform: {device_type}")

        if full_unique_id not in self.devices:
            device = DeviceProfile(
                unique_id=full_unique_id,
                name=unique_id,
                type=device_type,
                room=device_room,
                state=status,
                platform=platform,
                on_register=self.on_register,
                on_remove=self.on_remove,
                on_command=self.on_command,
            )
            self.devices[full_unique_id] = device

        return self.devices[full_unique_id]

    def setup_device(
        self, device_type: str, device_number: int, unit_id: str | None, status: bool | dict
    ) -> None:
        """Set up a device."""
        LOGGER.debug(
            f"Setting up {device_type} device number {device_number}, unit {unit_id}, status {status}"
        )

        if device_type not in DEVICE_TYPE_MAP:
            raise ValueError(f"Unsupported device type: {device_type}")

        device_id = f"{device_type}_{device_number}"
        device = self.initialize_device(device_id, unit_id, status)
        unique_id = device.unique_id

        if device_type != "energy" and unit_id and not unit_id.isdigit():
            letter_sub_id = "".join(re.findall(r'[a-zA-Z]', unit_id))
            device_key = f"{device_type}:{letter_sub_id}"
            new_device_type = DEVICE_TYPE_MAP[device_key]
        else:
            new_device_type = DEVICE_TYPE_MAP[device_type]

        self.async_add_device(new_device_type, device)

        if device.state != status:
            device.state = status
            if device.on_update and callable(device.on_update):
                device.on_update()

    async def _setup_elevator_entities(self) -> None:
        """Set the elevator entity."""
        self.setup_device("elevator", 0, "0", False)
        self.setup_device("elevator", 0, "floor_0", None)
        self.setup_device("elevator", 0, "direction_0", None)
        LOGGER.info("Elevator entities successfully registered.")

    def parse_xml_response(self, response: str) -> str:
        """Parse XML response."""
        try:
            result = xmltodict.parse(response)
            return result["imap"]["service"][0]["@result"]
        except Exception as ex:
            LOGGER.error(f"XML parsing error: {ex}")
            return None

    def result_after_request(self, response: str | dict) -> str:
        """Get result after request."""
        if self.version == "version1.0":
            result_data = self.parse_xml_response(response)
        else:
            result_data = response.get("result", None)
        return result_data

    async def _get_status(
        self, url: str, params: dict, device_type: str, device_number: int
    ) -> None:
        """Get device status."""
        cookies = self.config_entry.data[self.version]
        try:
            async with self.session.get(url=url, cookies=cookies, params=params) as response:
                response.raise_for_status()
                response_text = await response.text()
                if not response_text.strip():
                    LOGGER.warning(f"Empty response for {device_type}")
                    return

                try:
                    root = ET.fromstring(response_text)
                except ET.ParseError as e:
                    LOGGER.error(f"XML parsing error for {device_type}: {e}")
                    return

                status_infos = root.findall(".//status_info")
                if not status_infos:
                    LOGGER.warning(f"No status info found for {device_type}")
                    return

                unit_statuses = [
                    (info.attrib["unit_num"], info.attrib["unit_status"])
                    for info in status_infos
                ]
                for unit_num, unit_status in unit_statuses:
                    convert_unit_num = unit_num[-1]
                    if device_type in ["light", "gas", "doorlock"]:
                        self._parse_common_status(device_type, device_number, convert_unit_num, unit_status)
                    if hasattr(self, name := f"_parse_{device_type}_status"):
                        getattr(self, name)(device_number, convert_unit_num, unit_status)
        except Exception as ex:
            LOGGER.error(f"Error getting status for {device_type}: {ex}")

    def _parse_common_status(
        self, device_type: str, device_number: int, unit_num: str, unit_status: str
    ) -> None:
        """Parse common status for devices with on/off state."""
        status_value = unit_status in ["on", "open"]
        self.setup_device(device_type, device_number, unit_num, status_value)

    def _parse_electric_status(
        self, device_number: int, unit_num: str, unit_status: str
    ) -> None:
        """Parse the unit status for the electric/outlet."""
        status_parts = unit_status.split("/")
        for status_key in status_parts:
            is_cutoff = status_key in ["set", "unset"]
            convert_unit_num = f"cutoff_{unit_num}" if is_cutoff else unit_num
            status_value = status_key in ["set", "on"]
            self.setup_device("outlet", device_number, convert_unit_num, status_value)

    def _parse_thermostat_status(
        self, device_number: int, unit_num: str, unit_status: str
    ) -> None:
        """Parse the unit status for the thermostat."""
        status_parts = unit_status.split("/")
        status_value = {
            "mode": HVACMode.HEAT if status_parts[0] == "on" else HVACMode.OFF,
            "target_temperature": float(status_parts[1]),
            "current_temperature": float(status_parts[2])
        }
        self.setup_device("thermostat", unit_num, None, status_value)

    def _parse_fan_status(
        self, device_number: int, unit_num: str, unit_status: str
    ) -> None:
        """Parse the unit status for the fan."""
        is_off = unit_status == "off"
        speed_list = [SPEED_STR_LOW, SPEED_STR_MEDIUM, SPEED_STR_HIGH]
        status_value = {
            "state": not is_off,
            "speed": unit_status if not is_off else "off",
            "speed_list": speed_list,
            "preset": None,
        }
        self.setup_device("fan", device_number, None, status_value)

    async def get_light_status(self, device_number: int) -> None:
        """Get light status."""
        params = {
            "req_name": "remote_access_light" if device_number != 0 else "remote_access_livinglight",
            "req_action": "status"
        }
        if device_number != 0:
            params["req_dev_num"] = device_number
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._get_status(url, params, "light", device_number)

    async def get_outlet_status(self, device_number: int) -> None:
        """Get outlet status."""
        params = {
            "req_name": "remote_access_electric",
            "req_action": "status",
            "req_dev_num": device_number
        }
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._get_status(url, params, "electric", device_number)

    async def get_thermostat_status(self, device_number: int) -> None:
        """Get thermostat status."""
        params = {
            "req_name": "remote_access_temper",
            "req_action": "status",
            "req_unit_num": f"room{device_number}"
        }
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._get_status(url, params, "thermostat", device_number)

    async def get_gas_status(self, device_number: int = 0) -> None:
        """Get gas status."""
        params = {
            "req_name": "remote_access_gas",
            "req_action": "status",
            "req_unit_num": f"room{device_number}"
        }
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._get_status(url, params, "gas", device_number)

    async def get_fan_status(self, device_number: int = 0) -> None:
        """Get fan status."""
        params = {
            "req_name": "remote_access_ventil",
            "req_action": "status",
        }
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._get_status(url, params, "fan", device_number)

    async def get_doorlock_status(self, device_number: int = 0) -> None:
        """Get doorlock status."""
        params = {
            "req_name": "remote_access_doorlock",
            "req_action": "status",
            "req_unit_num": f"room{device_number}"
        }
        url = f"http://{self.config_entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._get_status(url, params, "doorlock", device_number)

    async def request_elevator(self) -> None:
        """Request elevator."""
        url = f"{self.config_entry.data[self.version]['url']}/v2/admin/elevators/home/apply"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.config_entry.data[CONF_UUID],
            "User-Agent": "mozilla/5.0 (windows nt 10.0; win64; x64) applewebkit/537.36 (khtml, like gecko) chrome/78.0.3904.70 safari/537.36"
        }
        params = {"address": self.config_entry.data[CONF_IP_ADDRESS], "direction": "down"}

        try:
            async with self.session.post(url=url, headers=headers, params=params) as response:
                response.raise_for_status()
                response_data = await response.json()
                result_status = self.result_after_request(response_data)

                if response.status == 200 and result_status == "ok":
                    LOGGER.info(f"Just a central server elevator request successful")
                    await self.get_elevator_status()
                else:
                    LOGGER.error(f"Only central server elevator request failed: {response_data}")
        except Exception as ex:
            LOGGER.error(f"Error requesting elevator command: {ex}")

    async def request_feature(
        self, device_type: str, room_id: int, unit_id: str, value: str
    ) -> None:
        """Request feature."""
        url = f"{self.config_entry.data[self.version]['url']}//v2/api/features/{device_type}/{room_id}/apply"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.config_entry.data[CONF_UUID],
            "User-Agent": "mozilla/5.0 (windows nt 10.0; win64; x64) applewebkit/537.36 (khtml, like gecko) chrome/78.0.3904.70 safari/537.36"
        }
        params = {"unit": unit_id, "state": value}
        if device_type[1] == "ventil":
            params.update({"mode": "", "unit_mode": ""})

        try:
            async with self.session.put(url=url, headers=headers, params=params) as response:
                response.raise_for_status()
                response_data = await response.json()
                result_status = self.result_after_request(response_data)

                if response.status == 200 and result_status == "ok":
                    LOGGER.info(f"{device_type}/{room_id}/{unit_id}, {value} request successful")
                    await self.get_feature_status(device_type, room_id)
                else:
                    LOGGER.info(f"{device_type}/{room_id}/{unit_id}, {value} request failed: {response_data}")
        except Exception as ex:
            LOGGER.error(f"Error requesting {device_type}, {room_id}/{unit_id}, {value} command: {ex}")

    async def get_feature_status(self, feature_name: str, room_id: str) -> None:
        """Get feature status."""
        url = f"{self.config_entry.data[self.version]['url']}/v2/api/features/{feature_name}/{room_id}/apply"
        headers = {
            "User-Agent": "mozilla/5.0 (windows nt 10.0; win64; x64) applewebkit/537.36 (khtml, like gecko) chrome/78.0.3904.70 safari/537.36",
            "access-token": self.config_entry.data[self.version]["access-token"]
        }

        try:
            async with self.session.get(url=url, headers=headers) as response:
                response.raise_for_status()
                response_data = await response.json()
                result_status = self.result_after_request(response_data)

                if response.status == 200 and result_status == "ok":
                    for unit in response_data["units"]:
                        convert_unit = unit["unit"][-1]
                        unit_state = unit["state"]
                        if feature_name in ["light", "livinglight", "gas", "doorlock"]:
                            if feature_name == "livinglight":
                                feature_name, room_id = "light", 0
                            self._parse_common_status(feature_name, room_id, convert_unit, unit_state)
                        if hasattr(self, name := f"_parse_{feature_name}_status"):
                            getattr(self, name)(room_id, convert_unit, unit_state)
                else:
                    LOGGER.error(f"Failed to get {feature_name} status: {response_data}")
        except Exception as ex:
            LOGGER.error(f"Error getting {feature_name} status: {ex}")

    async def process_features(self, features: list) -> None:
        """Process features."""
        for feature in features:
            if feature["quantity"] == 0:
                LOGGER.debug(f"Skipping feature '{feature['name']}' with quantity 0")
                continue
            
            if any(name in feature["name"] for name in ("livinglight", "thermostat")):
                quantity = 2
            else:
                quantity = feature["quantity"] + 1
            await asyncio.gather(
                *[
                    self.get_feature_status(feature["name"], i)
                    for i in range(1, quantity)
                ]
            )

    async def get_controllable_list(self):
        """Get controllable list."""
        url = f"{self.config_entry.data[self.version]['url']}/v2/api/features/apply"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "access-token": self.config_entry.data[self.version]["access-token"]
        }
        
        try:
            async with self.session.get(url=url, headers=headers) as response:
                response.raise_for_status()
                response_data = await response.json()
                result_status = self.result_after_request(response_data)

                if response.status == 200 and result_status == "ok":
                    LOGGER.debug(f"Fetched controllable list: {response_data}")
                    self.features_list.extend(response_data["features"])
                    await self.process_features(response_data["features"])
                else:
                    LOGGER.error(f"Failed to fetch controllable list: {response_data}")
        except Exception as ex:
            LOGGER.error(f"Error fetching controllable list: {ex}")

    async def get_device_status(self):
        """Get device status asynchronously."""
        if self.version == "version1.0":
            tasks = []

            tasks.extend(self.get_light_status(i) for i in range(6))
            tasks.extend(self.get_outlet_status(i) for i in range(1, 6))
            tasks.extend(self.get_thermostat_status(i) for i in range(1, 6))
            tasks.extend([
                self.get_gas_status(),
                self.get_fan_status(),
                self.get_doorlock_status()
            ])
            await asyncio.gather(*tasks)
        else:
            if self.features_list:
                LOGGER.debug(f"List of cached controllable: {self.features_list}")
                await self.process_features(self.features_list)
            else:
                await self.get_controllable_list()

    def handle_event_info(self, event) -> None:
        data = json.loads(event.data)

        if "move_info" in data:
            self.elev_moveinfo.update(data["move_info"])

            serial = self.elev_moveinfo.get("Serial", 0),
            floor = self.elev_moveinfo.get("Floor", "대기 층")
            movedir = self.elev_moveinfo.get("MoveDir", "대기"),

            self.setup_device("elevator", 0, f"floor_{serial}", floor)
            self.setup_device("elevator", 0, f"direction_{serial}", movedir)
        else:
            serial = self.elev_moveinfo.get("Serial", 0)

            self.setup_device("elevator", 0, serial, False)
            self.setup_device("elevator", 0, f"floor_{serial}", "arrived")
            self.setup_device("elevator", 0, f"direction_{serial}", "도착")

            if self.sse_client:
                self.sse_client.close()
                self.sse_client = None

    def get_elevator_status(self) -> None:
        url = f"{self.config_entry.data[self.version]['url']}/v2/admin/elevators/sse"
        with requests.get(url, stream=True) as r:
            self.sse_client = sseclient.SSEClient(r)
            try:
                for event in self.sse_client.events():
                    if event.event in ["moveinfo", "arrived"]:
                        self.handle_event_info(event)
            except Exception as e:
                print(f"EventSource elevator error occurred: {e}")

    async def schedule_session_refresh(self) -> None:
        """Schedule for periodic session refresh.""" 
        while not self.stop_event.is_set():
            if self.version == "version1.0":
                await self._v1_refresh_session()
            else:
                await self._v2_refresh_session()
            await asyncio.sleep(60 * 60)
