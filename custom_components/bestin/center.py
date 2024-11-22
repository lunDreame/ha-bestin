import hashlib
import base64
import asyncio
import xmltodict
import xml.etree.ElementTree as ET
import aiohttp
import json

from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.components.climate.const import (
    SERVICE_SET_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_CURRENT_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.light import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
)
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UUID,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    ATTR_STATE,
    WIND_SPEED,
)

from .const import (
    LOGGER,
    BRAND_PREFIX,
    SMART_HOME_1,
    CONF_SESSION,
    DEFAULT_SCAN_INTERVAL,
    SPEED_STR_LOW,
    SPEED_STR_MEDIUM,
    SPEED_STR_HIGH,
    MAIN_DEVICES,
    DEVICE_PLATFORM_MAP,
    PLATFORM_SIGNAL_MAP,
    DeviceProfile,
    DeviceInfo,
)


class CenterAPIv2:
    """Initialize CenterAPIv2 for Smart Home 2.0 API."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Initialize the CenterAPIv2."""
        self.elevator_arrived = False
        self.register_elevator: str | None = entry.data.get(CONF_IP_ADDRESS)
        self.elevator_number: int = entry.data.get("elevator_number", 1)

        self.features_list: list[dict] = []
        self.elevator_data: dict[str,  dict] = {}

    async def _v2_device_status(self, args=None):
        """Update device status for v2 API."""
        if isinstance(args, datetime):
            self.last_update_time = datetime.now()
        
        if self.features_list:
            await self.process_features(self.features_list)
        else:
            await self.fetch_feature_list()
        
        if self.register_elevator:
            for i in range(1, self.elevator_number + 1):
                self._elevator_registration(str(i))
    
    async def _v2_refresh_session(self, args=None):
        """Refresh session for v2 API."""
        url = "https://center.hdc-smart.com/v3/auth/login"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.entry.data[CONF_UUID],
            "User-Agent": "Mozilla/5.0"
        }

        try:
            async with self.session.post(url=url, headers=headers, timeout=5) as response:
                resp = await response.json()

                if response.status != 200:
                    LOGGER.error(f"Login failed: {response.status} {resp}")
                    return
                if "err" in resp:
                    LOGGER.error(f"Session refresh failed: {resp['err']}")
                    return

                LOGGER.debug(f"Session refreshed: {resp}")
                if isinstance(args, datetime):
                    self.last_sess_refresh = datetime.now()
                self.hass.config_entries.async_update_entry(
                    entry=self.entry,
                    data={**self.entry.data, CONF_SESSION: resp},
                )
                await asyncio.sleep(1)
        except Exception as ex:
            LOGGER.error(f"Exception during session refresh: {type(ex).__name__}: {ex}")

    async def elevator_call_request(self):
        """Send elevator call request."""
        url = f"{self.entry.data[CONF_SESSION][CONF_URL]}/v2/admin/elevators/home/apply"
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.entry.data[CONF_UUID],
            "User-Agent": "Mozilla/5.0"
        }
        data = {
            "address": self.entry.data[CONF_IP_ADDRESS],
            "direction": "down"
        }

        try:
            async with self.session.post(url=url, headers=headers, json=data) as response:
                response.raise_for_status()
                resp = await response.json(content_type="text/plain")
                result_status = self.result_after_request(resp)

                if response.status == 200 and result_status == "ok":
                    LOGGER.info(f"Just a central server elevator request successful")
                    self.hass.create_task(self.fetch_elevator_status())
                else:
                    LOGGER.error(f"Only central server elevator request failed: {resp}")
        except Exception as ex:
            LOGGER.error(f"Error requesting elevator command: {ex}")

    async def fetch_elevator_status(self):
        """Fetch and process elevator status updates."""
        url = f"{self.entry.data[CONF_SESSION][CONF_URL]}/v2/admin/elevators/sse"
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    LOGGER.error(f"Failed to fetch elevator status: {response.status}")
                    return
                
                async for line in response.content:
                    if line.startswith(b"data:"):
                        message = line.decode('utf-8').strip("data:").strip()
                        if json.loads(message).get("address") == self.register_elevator:
                            LOGGER.debug(f"Received message - elevator: {message}")
                            await self.handle_message_info(message)
                    if self.elevator_arrived:
                        self.elevator_arrived = False
                        break
        except Exception as ex:
            LOGGER.error(f"Fetch elevator status error occurred: {ex}")

    async def handle_message_info(self, message: str):
        """Process elevator message information."""
        data = json.loads(message)

        if "move_info" in data:
            move_info = data["move_info"]
            serial = move_info["Serial"]
        
            self.elevator_data = {serial: move_info}
            self.elevator_data = dict(sorted(self.elevator_data.items()))
            LOGGER.debug("Elevator data: %s", self.elevator_data)

            if len(self.elevator_data) >= 2:
                for idx, (serial, info) in enumerate(self.elevator_data.items(), start=1):
                    floor = info["Floor"]
                    move_dir = info["MoveDir"].capitalize()
                    self.elevator_data[f"floor{str(idx)}"] = floor

                    self.set_device("elevator", 1, f"floor_{str(idx)}", floor)
                    self.set_device("elevator", 1, f"direction_{str(idx)}", move_dir)
            else:
                floor = move_info["Floor"]
                move_dir = move_info["MoveDir"].capitalize()
                self.elevator_data[f"floor1"] = floor
                
                self.set_device("elevator", 1, "floor_1", floor)
                self.set_device("elevator", 1, "direction_1", move_dir)
        else:
            for idx in range(1, self.elevator_number + 1):
                floor = self.elevator_data.get(f"floor{str(idx)}", "Unknown")
            
                self.set_device("elevator", 1, f"floor_{str(idx)}", floor)
                self.set_device("elevator", 1, f"direction_{str(idx)}", "Arrival")
                await asyncio.sleep(2)  # Wait for a while

                self.set_device("elevator", 1, f"floor_{str(idx)}", "-")
                self.set_device("elevator", 1, f"direction_{str(idx)}", "Idle")

            self.elevator_arrived = True
    
    async def request_feature_command(
        self, device_type: str, room_id: int, unit: str, value: dict | str
    ):
        """Send feature command request."""
        url = f"{self.entry.data[CONF_SESSION][CONF_URL]}/v2/api/features/{device_type}/{room_id}/apply"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "access-token": self.entry.data[CONF_SESSION]["access-token"],
        }
        data = {"unit": unit, "state": value}
        
        if device_type == "ventil":
            data.update({"unit": unit[:-1], "mode": "", "unit_mode": ""})
        if device_type == "smartlight":
            data.update({"unit": unit[-1], **value})

        try:
            async with self.session.put(url=url, headers=headers, json=data) as response:
                response.raise_for_status()
                resp = await response.json()
                result_status = self.result_after_request(resp)

                if response.status == 200 and result_status == "ok":
                    LOGGER.info(f"{device_type} in room {room_id} set to {unit}={value}.")
                    await self.fetch_feature_status(device_type, room_id)
                else:
                    LOGGER.warning(f"Failed to set {device_type} in room {room_id}. Response: {resp}")
        except Exception as ex:
            LOGGER.error(f"Error setting {device_type} in room {room_id}: {ex}")

    async def fetch_feature_status(self, feature_name: str, room_id: int):
        """Fetch status of a specific feature."""
        url = f"{self.entry.data[CONF_SESSION][CONF_URL]}/v2/api/features/{feature_name}/{room_id}/apply"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "access-token": self.entry.data[CONF_SESSION]["access-token"],
        }
        
        try:
            async with self.session.get(url=url, headers=headers) as response:
                response.raise_for_status()
                resp = await response.json()
                result_status = self.result_after_request(resp)

                if response.status == 200 and result_status == "ok":
                    LOGGER.debug(f"Fetched feature status: {resp}")
                    if feature_name == "smartlight":
                        units = [
                            unit for map in resp["map"]
                            if map["units"] is not None
                            for unit in map["units"]
                        ]
                    else:
                        units = resp["units"]
                    
                    for unit in units:
                        if feature_name == "smartlight":
                            unit_last = unit["unit"]
                            unit_state = {
                                ATTR_STATE: unit["state"] == "on",
                                COLOR_MODE_BRIGHTNESS: int(unit["dimming"]) if unit["dimming"] != "null" else None,
                                COLOR_MODE_COLOR_TEMP: int(unit["color"]) if unit["color"] != "null" else None,
                            }
                        else:
                            unit_last = unit["unit"][-1]
                            unit_state = unit["state"]

                        if feature_name in ["light", "smartlight", "livinglight", "gas", "doorlock"]:
                            self._parse_common_status(feature_name, room_id, unit_last, unit_state)
                        if hasattr(self, name := f"_parse_{feature_name}_status"):
                            getattr(self, name)(room_id, unit_last, unit_state)
                else:
                    LOGGER.error(f"Failed to get {feature_name} status: {resp}")
        except Exception as ex:
            LOGGER.error(f"Error getting {feature_name} status: {ex}")
    
    async def process_features(self, features: list[dict]):
        """Process a list of features."""
        for feature in features:
            if feature["name"] in ["sensor", "mode"]:
                continue
            if feature["quantity"] == 0:
                LOGGER.debug(f"Skipping feature '{feature['name']}' with quantity 0")
                continue
            
            if any(name in feature["name"] for name in ("livinglight", "thermostat")):
                quantity = 2
            else:
                quantity = feature["quantity"] + 1
            await asyncio.gather(
                *[
                    self.fetch_feature_status(feature["name"], i)
                    for i in range(1, quantity)
                ]
            )

    async def fetch_feature_list(self):
        """Fetch the list of available features."""
        url = f"{self.entry.data[CONF_SESSION][CONF_URL]}/v2/api/features/apply"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "access-token": self.entry.data[CONF_SESSION]["access-token"],
        }
        
        try:
            async with self.session.get(url=url, headers=headers) as response:
                response.raise_for_status()
                resp = await response.json()
                result_status = self.result_after_request(resp)

                if response.status == 200 and result_status == "ok":
                    LOGGER.debug(f"Fetched feature list: {resp}")
                    self.features_list.extend(resp["features"])
                    await self.process_features(resp["features"])
                else:
                    LOGGER.error(f"Failed to fetch feature list: {resp}")
        except Exception as ex:
            LOGGER.error(f"Error fetching feature list: {ex}")


class BestinCenterAPI(CenterAPIv2):
    """BestinCenterAPI for Smart Home 1.0/2.0 API."""

    def __init__(
        self, 
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_groups: dict[str, set[str]],
        hub_id: str,
        version: str,
        add_device_callback: Callable
    ) -> None:
        """Initialize API and create session."""
        super().__init__(hass, entry)
        self.hass = hass
        self.entry = entry
        self.entity_groups = entity_groups
        self.hub_id = hub_id
        self.version = version
        self.add_device_callback = add_device_callback

        connector = aiohttp.TCPConnector()
        self.session = aiohttp.ClientSession(connector=connector)
        
        self.tasks: list[asyncio.Task] = []
        self.devices: dict[str, DeviceProfile] = {}
        self.last_update_time: datetime = datetime.now()
        self.last_sess_refresh: datetime = datetime.now()

    def get_short_hash(self, id: str) -> str:
        """Generate a short hash from the given ID."""
        hash_object = hashlib.sha256(id.encode()).digest()
        return base64.urlsafe_b64encode(hash_object)[:8].decode("utf-8").upper()

    async def start(self):
        """Start the API operations."""
        version_suffix = self.version[11:12]  # Smart Home 1.0
    
        refresh_session_interval = timedelta(
            minutes=15 if version_suffix == "1" else 60
        )
        device_status_interval = timedelta(
            minutes=self.entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
    
        refresh_session = getattr(self, f"_v{version_suffix}_refresh_session")
        device_status = getattr(self, f"_v{version_suffix}_device_status")
    
        await refresh_session()
        self.hass.create_task(device_status())

        self.tasks = [
            async_track_time_interval(self.hass, refresh_session, refresh_session_interval),
            async_track_time_interval(self.hass, device_status, device_status_interval)
        ]

    async def stop(self):
        """Stop all running tasks and reset timers."""
        if self.tasks:
            for task in self.tasks:
                task()
            self.tasks = []

    @callback
    async def enqueue_command(self, device_id: str, value: Any, **kwargs: dict | None):
        """Enqueue a command for a device."""
        parts = device_id.split("_")
        device_type = parts[1]
        room_id = int(parts[2])
        pos_id = 0
        sub_type = None

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

        if self.version == SMART_HOME_1:
            if device_type == "doorlock":
                LOGGER.warning("For doorlock, command is not supported.")
            else:
                unit_id = f"{sub_type}{pos_id or room_id}" \
                    if kwargs else f"{device_type}{pos_id or ''}"
                await self.request_home_device(device_type, room_id, unit_id, value)
        else:
            if device_type == "elevator":
                await self.elevator_call_request()
            else:
                unit_id = f"{sub_type}{pos_id or room_id}" if kwargs else f"{device_type}1"
                await self.request_feature_command(device_type, room_id, unit_id, value)

    def get_devices_from_domain(self, domain: str) -> list:
        """Get devices for a specific domain."""
        entity_list = self.entity_groups.get(domain, set())
        return [self.devices.get(uid, {}) for uid in entity_list]

    def initial_device(self, device_id: str, sub_id: str | None, state: Any) -> dict:
        """Initialize a device with given parameters."""
        device_type, device_room = device_id.split("_")
    
        did_suffix = f"_{sub_id}" if sub_id else ""
        device_id = f"{BRAND_PREFIX}_{device_id}{did_suffix}"
        if sub_id:
            sub_id_parts = sub_id.split("_")
            device_name = f"{device_type} {device_room} {' '.join(sub_id_parts)}".title()
        else:
            device_name = f"{device_type} {device_room}".title()

        if sub_id and not sub_id.isdigit():
            device_type = f"{device_type}:{''.join(filter(str.isalpha, sub_id))}"
        
        if device_type not in MAIN_DEVICES:
            uid_suffix = f"-{self.get_short_hash(self.hub_id)}"
        else:
            uid_suffix = ""
        unique_id = f"{device_id}{uid_suffix}"

        if device_id not in self.devices:
            device_info = DeviceInfo(
                device_type=device_type,
                name=device_name,
                room=device_room,
                state=state,
                device_id=device_id,
            )
            self.devices[device_id] = DeviceProfile(
                enqueue_command=self.enqueue_command,
                domain=DEVICE_PLATFORM_MAP[device_type],
                unique_id=unique_id,
                info=device_info,
            )
        return self.devices[device_id]

    def set_device(
        self, device_type: str, device_number: int, unit_id: str | None, status: Any
    ):
        """Set device status and add it if not exists."""
        if device_type not in DEVICE_PLATFORM_MAP:
            LOGGER.error(f"Unsupported device type: {device_type}")
            return
        
        device_id = f"{device_type}_{device_number}"
        device = self.initial_device(device_id, unit_id, status)

        if unit_id and not unit_id.isdigit():
            format_device = f"{device_type}:{''.join(filter(str.isalpha, unit_id))}"
            device_platform = DEVICE_PLATFORM_MAP[format_device]
        else:
            device_platform = DEVICE_PLATFORM_MAP[device_type]
        
        device_uid = device.unique_id
        device_info = device.info
        if device_uid not in self.entity_groups.get(device_platform, []):
            signal = PLATFORM_SIGNAL_MAP[device_platform]
            self.add_device_callback(signal, device)

        if device_info.state != status:
            device_info.state = status
            device.update_callbacks()

    def parse_xml_response(self, response: str) -> str:
        """Parse XML response and return result."""
        try:
            result = xmltodict.parse(response)
            return result["imap"]["service"]["@result"]
        except Exception as ex:
            LOGGER.error(f"XML parsing error: {ex}")
            return None

    def result_after_request(self, response: dict | str) -> str:
        """Process response after request based on API version."""
        if self.version == SMART_HOME_1:
            result_data = self.parse_xml_response(response)
        else:
            result_data = response.get("result", None)
        return result_data

    def _elevator_registration(self, id: str):
        """Register elevator device."""
        self.set_device("elevator", 1, id, False)
        self.set_device("elevator", 1, f"floor_{id}", "-")
        self.set_device("elevator", 1, f"direction_{id}", "Idle")
    
    def _parse_common_status(
        self, device_type: str, device_number: int, unit_num: str, unit_status: dict | str
    ):
        """Parse common status for devices."""
        if isinstance(unit_status, dict):
            status_value = unit_status
        else:
            status_value = unit_status in ["on", "open"]
        self.set_device(device_type, device_number, unit_num, status_value)

    def _parse_electric_status(
        self, device_number: int, unit_num: str, unit_status: str
    ):
        """Parse electric device status."""
        status_parts = unit_status.split("/")
        for status_key in status_parts:
            is_set = status_key in ["set", "unset"]
            conv_unit_num = f"standbycut_{unit_num}" if is_set else unit_num
            status_value = status_key in ["set", "on"]
            if (
                # Version 1 has one standby power cut-off per room
                self.version == SMART_HOME_1 
                and conv_unit_num.startswith("standbycut_")
                and int(unit_num) > 1
            ):
                continue
            self.set_device("electric", device_number, conv_unit_num, status_value)

    def _parse_thermostat_status(
        self, device_number: int, unit_num: str, unit_status: str
    ):
        """Parse thermostat status."""
        status_parts = unit_status.split("/")
        status_value = {
            ATTR_HVAC_MODE: HVACMode.HEAT if status_parts[0] == "on" else HVACMode.OFF,
            SERVICE_SET_TEMPERATURE: float(status_parts[1]),
            ATTR_CURRENT_TEMPERATURE: float(status_parts[2])
        }
        self.set_device("thermostat", unit_num, None, status_value)

    def _parse_temper_status(
        self, device_number: int, unit_num: str, unit_status: str
    ):
        """Parse temper(thermostat) status."""
        status_parts = unit_status.split("/")
        status_value = {
            ATTR_HVAC_MODE: HVACMode.HEAT if status_parts[0] == "on" else HVACMode.OFF,
            SERVICE_SET_TEMPERATURE: float(status_parts[1]),
            ATTR_CURRENT_TEMPERATURE: float(status_parts[2])
        }
        self.set_device("temper", unit_num, None, status_value)
    
    def _parse_ventil_status(
        self, device_number: int, unit_num: str, unit_status: str
    ):
        """Parse ventilation status."""
        is_off = unit_status == "off"
        speed_list = [SPEED_STR_LOW, SPEED_STR_MEDIUM, SPEED_STR_HIGH]
        status_value = {
            ATTR_STATE: not is_off,
            WIND_SPEED: unit_status if not is_off else "off",
            "speed_list": speed_list,
            ATTR_PRESET_MODE: None,
        }
        self.set_device("ventil", device_number, None, status_value)

    async def _v1_device_status(self, args=None):
        """Update device status for v1 API."""
        if isinstance(args, datetime):
            self.last_update_time = args
        
        await asyncio.gather(
            *[self.fetch_device_status("light", i) for i in range(6)],
            *[self.fetch_device_status("electric", i) for i in range(1, 6)],
            *[self.fetch_device_status("temper", i) for i in range(1, 6)],
            self.fetch_device_status("gas"),
            self.fetch_device_status("ventil"),
            self.fetch_device_status("doorlock")
        )

    async def _v1_refresh_session(self, args=None):
        """Refresh session for v1 API."""
        url = f"http://{self.entry.data[CONF_IP_ADDRESS]}/webapp/data/getLoginWebApp.php"
        params = {
            "login_ide": self.entry.data[CONF_USERNAME],
            "login_pwd": self.entry.data[CONF_PASSWORD]
        }
        try:
            async with self.session.get(url=url, params=params, timeout=5) as response:
                resp = await response.json(content_type="text/html")
                if response.status != 200 or "_fair" in resp:
                    LOGGER.error(f"Session refresh failed: {resp.get('msg', 'Unknown error')}")
                    return

                cookies = response.cookies
                new_cookie = {
                    "PHPSESSID": cookies.get("PHPSESSID").value if cookies.get("PHPSESSID") else None,
                    "user_id": cookies.get("user_id").value if cookies.get("user_id") else None,
                    "user_name": cookies.get("user_name").value if cookies.get("user_name") else None,
                }
                LOGGER.debug(f"Session refreshed: {resp}, Cookie: {new_cookie}")
                if isinstance(args, datetime):
                    self.last_sess_refresh = args
                self.hass.config_entries.async_update_entry(
                    entry=self.entry,
                    data={**self.entry.data, CONF_SESSION: new_cookie},
                )
                await asyncio.sleep(1)
        except Exception as ex:
            LOGGER.error(f"Exception during session refresh: {type(ex).__name__}: {ex}")

    async def _v1_fetch_status(
        self, url: str, params: dict, device_type: str, device_number: int
    ):
        """Fetch status for v1 API devices."""
        cookies = self.entry.data[CONF_SESSION]
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
                    if device_type in ["light", "livinglight", "gas", "doorlock"]:
                        self._parse_common_status(device_type, device_number, unit_num[-1], unit_status)
                    if hasattr(self, name := f"_parse_{device_type}_status"):
                        getattr(self, name)(device_number, unit_num[-1], unit_status)
        except Exception as ex:
            LOGGER.error(f"Error getting status for {device_type}: {ex}")
    
    async def fetch_device_status(self, device_type: str, device_number: int = 1):
        """Fetch status for a specific device type."""
        params = {
            "req_action": "status"
        }
        
        if device_type == "light":
            params["req_name"] = "remote_access_light" if device_number != 0 else "remote_access_livinglight"
            if device_number != 0:
                params["req_dev_num"] = device_number
        elif device_type == "electric":
            params["req_name"] = "remote_access_electric"
            params["req_dev_num"] = device_number
        elif device_type == "temper":
            params["req_name"] = "remote_access_temper"
            params["req_unit_num"] = f"room{device_number}"
        elif device_type == "gas":
            params["req_name"] = "remote_access_gas"
        elif device_type == "ventil":
            params["req_name"] = "remote_access_ventil"
        elif device_type == "doorlock":
            params["req_name"] = "remote_access_doorlock"
        
        url = f"http://{self.entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        await self._v1_fetch_status(url, params, device_type, device_number)
    
    async def request_home_device(
        self, device_type: str, room_id: int, unit: str, value: str
    ):
        """Request a home device."""
        params = {
            "req_name": "remote_access_livinglight"
                if device_type == "light" and room_id == 0 else f"remote_access_{device_type}",
            "req_action": "control",
            "req_unit_num": unit,
            "req_ctrl_action": value,
        }
        if device_type not in ["gas", "ventil"]:
            params["req_dev_num"] = room_id

        url = f"http://{self.entry.data[CONF_IP_ADDRESS]}/mobilehome/data/getHomeDevice.php"
        cookies = self.entry.data[CONF_SESSION]
        try:
            async with self.session.get(url=url, cookies=cookies, params=params) as response:
                response.raise_for_status()
                resp = await response.text()
                result_status = self.result_after_request(resp)

                if response.status == 200 and result_status == "ok":
                    LOGGER.info(f"{device_type} in room {room_id} set to {unit}={value}.")
                    await self.fetch_device_status(device_type, room_id)
                else:
                    LOGGER.warning(f"Failed to set {device_type} in room {room_id}. Response: {resp}")
        except Exception as ex:
            LOGGER.error(f"Error setting {device_type} in room {room_id}: {ex}")
