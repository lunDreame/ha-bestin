import logging

from typing import Callable, Any, Set
from dataclasses import dataclass, field

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    Platform,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
    UnitOfVolumeFlowRate
)

DOMAIN = "bestin"
NAME = "BESTIN"
VERSION = "1.1.5"

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
    "smartlight": Platform.LIGHT.value,
    "livinglight": Platform.LIGHT.value,
    "outlet": Platform.SWITCH.value,
    "outlet:cutoff": Platform.SWITCH.value,
    "outlet:consumption": Platform.SENSOR.value,
    "energy": Platform.SENSOR.value,
    "doorlock": Platform.SWITCH.value,
    "elevator": Platform.SWITCH.value,
    "elevator:direction": Platform.SENSOR.value,
    "elevator:floor": Platform.SENSOR.value,
    "electric": Platform.SWITCH.value,
    "electric:cutoff": Platform.SWITCH.value,
    "gas": Platform.SWITCH.value,
}

ELEMENT_BYTE_RANGE: dict[str, tuple[slice]] = {
    "electric": (slice(8, 12), slice(8, 12)),
    "gas": (slice(32, 36), slice(25, 29)),
    "heat": (slice(40, 44), slice(40, 44)),
    "hotwater": (slice(24, 28), slice(24, 28)),
    "water": (slice(17, 20), slice(17, 20)),
}

ELEMENT_DEVICE_CLASS: dict[str, Any] = {
    "outlet:consumption": UnitOfPower.WATT,
    "electric:realtime": SensorDeviceClass.POWER,
    "electric:total": SensorDeviceClass.ENERGY,
    "gas:total": SensorDeviceClass.GAS,
    "water:total": SensorDeviceClass.WATER,
}

ELEMENT_UNIT: dict[str, Any] = {
    "outlet:consumption": UnitOfPower.WATT,
    "electric:realtime": UnitOfPower.WATT,
    "electric:total": UnitOfEnergy.KILO_WATT_HOUR,
    "gas:realtime": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "gas:total": UnitOfVolume.CUBIC_METERS,
    "heat:realtime": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "heat:total": UnitOfVolume.CUBIC_METERS,
    "hotwater:realtime": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "hotwater:total": UnitOfVolume.CUBIC_METERS,
    "water:realtime": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "water:total": UnitOfVolume.CUBIC_METERS,
}

ELEMENT_VALUE_CONVERSION: dict[str, Any] = {
    "outlet:consumption": lambda value: value,
    "elevator:floor": lambda value: value,
    "elevator:direction": lambda value: value,
    "electric:total": lambda value: round(value / 100, 2),
    "electric:realtime": lambda value: value,
    "gas:total": lambda value: round(value / 1000, 2),
    "gas:realtime": lambda value: value / 10,
    "heat:total": lambda value: round(value / 1000, 2),
    "heat:realtime": [
        lambda value: value,
        lambda value: value / 1000
    ],
    "hotwater:total": lambda value: round(value / 1000, 2),
    "hotwater:realtime": [
        lambda value: value,
        lambda value: value / 1000
    ],
    "water:total": lambda value: round(value / 1000, 2),
    "water:realtime": [
        lambda value: value,
        lambda value: value / 1000,
    ],
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
