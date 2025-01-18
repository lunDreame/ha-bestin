import logging

from typing import Callable, Any, Set
from dataclasses import dataclass, field

from homeassistant.const import Platform

DOMAIN = "bestin"
NAME = "BESTIN"
VERSION = "1.1.9"

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

LOGGER = logging.getLogger(__package__)

CONF_VERSION = "version"
CONF_VERSION_1 = "version1.0"
CONF_VERSION_2 = "version2.0"
CONF_SESSION = "session"

DEFAULT_PORT = 8899
DEFAULT_MAX_SEND_RETRY = 10
DEFAULT_PACKET_VIEWER = False

DEFAULT_SCAN_INTERVAL = 30

SMART_HOME_1 = "Smart Home 1.0"
SMART_HOME_2 = "Smart Home 2.0"

SPEED_INT_LOW = 1
SPEED_INT_MEDIUM = 2
SPEED_INT_HIGH = 3

SPEED_STR_LOW = "low"
SPEED_STR_MEDIUM = "mid"
SPEED_STR_HIGH = "high"

PRESET_NONE = "none"
PRESET_NV = "natural_ventilation"

BRAND_PREFIX = "bestin"

NEW_CLIMATE = "climates"
NEW_FAN = "fans"
NEW_LIGHT = "lights"
NEW_SENSOR = "sensors"
NEW_SWITCH = "switchs"

MAIN_DEVICES: list[str] = [
    "fan",
    "ventil",
    "elevator:direction",
    "elevator:floor",
    "gas",
    "doorlock",
    "elevator",
]

PLATFORM_SIGNAL_MAP = {
    Platform.CLIMATE.value: NEW_CLIMATE,
    Platform.FAN.value: NEW_FAN,
    Platform.LIGHT.value: NEW_LIGHT,
    Platform.SENSOR.value: NEW_SENSOR,
    Platform.SWITCH.value: NEW_SWITCH,
}

DEVICE_PLATFORM_MAP = {
    "temper": Platform.CLIMATE.value,
    "thermostat": Platform.CLIMATE.value,
    "fan": Platform.FAN.value,
    "ventil": Platform.FAN.value,
    "light": Platform.LIGHT.value,
    "light:dcvalue": Platform.SENSOR.value,
    "smartlight": Platform.LIGHT.value,
    "livinglight": Platform.LIGHT.value,
    "outlet": Platform.SWITCH.value,
    "outlet:cutvalue": Platform.SENSOR.value,
    "outlet:standbycut": Platform.SWITCH.value,
    "outlet:powercons": Platform.SENSOR.value,
    "energy": Platform.SENSOR.value,
    "doorlock": Platform.SWITCH.value,
    "elevator": Platform.SWITCH.value,
    "elevator:direction": Platform.SENSOR.value,
    "elevator:floor": Platform.SENSOR.value,
    "electric": Platform.SWITCH.value,
    "electric:standbycut": Platform.SWITCH.value,
    "gas": Platform.SWITCH.value,    
}

@dataclass
class DeviceInfo:
    """Represents information about a device."""
    device_type: str
    name: str
    room: str
    state: Any
    device_id: str

@dataclass
class DeviceProfile:
    """Manages device profiles, including callbacks and command handling."""
    enqueue_command: Callable[..., None]
    domain: str
    unique_id: str
    info: DeviceInfo
    callbacks: Set[Callable[..., None]] = field(default_factory=set)

    def add_callback(self, callback: Callable[..., None]) -> None:
        """Adds a callback to the set of callbacks."""
        self.callbacks.add(callback)

    def remove_callback(self, callback: Callable[..., None]) -> None:
        """Removes a callback from the set of callbacks."""
        self.callbacks.discard(callback)
    
    def update_callbacks(self) -> None:
        """Calls all registered callbacks."""
        for callback in self.callbacks:
            assert callable(callback), "Callback should be callable"
            callback()
