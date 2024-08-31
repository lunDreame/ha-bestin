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
VERSION = "1.3.0"

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

LOGGER: logging.Logger = logging.getLogger(__package__)

DEFAULT_PORT: int = 8899
DEFAULT_SCAN_INTERVAL: int = 15
DEFAULT_MAX_TRANSMISSION: int = 10

DEFAULT_PACKET_VIEWER: bool = False

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

DOMAIN_SIGNAL_MAP: dict[str, Platform] = {
    Platform.CLIMATE: NEW_CLIMATE,
    Platform.FAN: NEW_FAN,
    Platform.LIGHT: NEW_LIGHT,
    Platform.SENSOR: NEW_SENSOR,
    Platform.SWITCH: NEW_SWITCH,
}

DEVICE_DOMAIN_MAP: dict[str, Platform] = {
    "thermostat": Platform.CLIMATE,
    "fan": Platform.FAN,
    "light": Platform.LIGHT,
    "outlet:consumption": Platform.SENSOR,
    "energy": Platform.SENSOR,
    "outlet": Platform.SWITCH,
    "outlet:cutoff": Platform.SWITCH,
    "gas": Platform.SWITCH,
    "doorlock": Platform.SWITCH,
}

# Center
CTR_DOMAIN_SIGNAL_MAP: dict[Platform, str] = {
    Platform.CLIMATE: NEW_CLIMATE,
    Platform.FAN: NEW_FAN,
    Platform.LIGHT: NEW_LIGHT,
    Platform.SENSOR: NEW_SENSOR,
    Platform.SWITCH: NEW_SWITCH,
}

CTR_DEVICE_DOMAIN_MAP: dict[str, Platform] = {
    "temper": Platform.CLIMATE,
    "thermostat": Platform.CLIMATE,
    "ventil": Platform.FAN,
    "light": Platform.LIGHT,
    "livinglight": Platform.LIGHT,
    "elevator:direction": Platform.SENSOR,
    "elevator:floor": Platform.SENSOR,
    "electric": Platform.SWITCH,
    "electric:cutoff": Platform.SWITCH,
    "gas": Platform.SWITCH,
    "elevator": Platform.SWITCH,
}

# Fan (Ventil)
SPEED_STR_LOW = "low"
SPEED_STR_MEDIUM = "mid"
SPEED_STR_HIGH = "high"

SPEED_INT_LOW = 1
SPEED_INT_MEDIUM = 2
SPEED_INT_HIGH = 3

PRESET_NONE = "None"
PRESET_NATURAL_VENTILATION = "Natural Ventilation"

# Energy (HEMS) Index Map
ELEMENT_BYTE_RANGE: dict[str, tuple[slice]] = {
    "electric": (slice(8, 12), slice(8, 12)),
    "gas": (slice(32, 36), slice(25, 29)),
    "heat": (slice(40, 44), slice(40, 44)),
    "hotwater": (slice(24, 28), slice(24, 28)),
    "water": (slice(17, 20), slice(17, 20)),
}

# Energy (HEMS) Class Map
ELEMENT_DEVICE_CLASS: dict[str, UnitOfPower | SensorDeviceClass] = {
    "outlet:consumption": UnitOfPower.WATT,
    "electric:realtime": SensorDeviceClass.POWER,
    "electric:total": SensorDeviceClass.ENERGY,
    "gas:total": SensorDeviceClass.GAS,
    "water:total": SensorDeviceClass.WATER,
}

# Energy (HEMS) Unit Map
ELEMENT_UNIT: dict[str, UnitOfPower | UnitOfEnergy | UnitOfVolumeFlowRate | UnitOfVolume] = {
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

# Energy (HEMS) Value Convert
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
    """Represents the basic information of a device."""
    device_type: str
    name: str
    room: str
    state: Any
    unique_id: str

@dataclass
class Device:
    """Represents a device with callbacks and update functionalities."""
    info: DeviceInfo
    domain: str
    enqueue_command: Callable
    callbacks: Set[Callable] = field(default_factory=set)
    
    def add_callback(self, callback: Callable):
        """Add a callback to the set of callbacks."""
        self.callbacks.add(callback)

    def remove_callback(self, callback: Callable):
        """Remove a callback from the set of callbacks, if it exists."""
        self.callbacks.discard(callback)
