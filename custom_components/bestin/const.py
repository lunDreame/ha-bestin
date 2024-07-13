import logging
from datetime import timedelta

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
VERSION = "1.0.1"

LOGGER = logging.getLogger(__package__)
SCAN_INTERVAL = timedelta(seconds=60)
DEFAULT_PORT = 8899

DEVICE_CONSUMPTION = "outlet:consumption"
DEVICE_CUTOFF = "outlet:cutoff"
DEVICE_DOORLOCK = "doorlock"
DEVICE_ENERGY = "energy"
DEVICE_FAN = "fan"
DEVICE_GAS = "gas"
DEVICE_LIGHT = "light"
DEVICE_OUTLET = "outlet"
DEVICE_THERMOSTAT = "thermostat"

MAIN_DEVICES = [
    DEVICE_DOORLOCK,
    DEVICE_FAN,
    DEVICE_GAS,
]

ELECTRIC_REALTIME = "electric:realtime"
ELECTRIC_TOTAL = "electric:total"
GAS_REALTIME = "gas:realtime"
GAS_TOTAL = "gas:total"
HEAT_REALTIME = "heat:realtime"
HEAT_TOTAL = "heat:total"
HOTWATER_REALTIME = "hotwater:realtime"
HOTWATER_TOTAL = "hotwater:total"
WATER_REALTIME = "water:realtime"
WATER_TOTAL = "water:total"

ATTR_ELECTRIC = "electric"
ATTR_GAS = "gas"
ATTR_HEAT = "heat"
ATTR_HOTWATER = "hotwater"
ATTR_WATER = "water"

ELEMENT_BYTE_RANGE = {
    ATTR_ELECTRIC: (slice(8, 12), slice(8, 12)),
    ATTR_GAS: (slice(32, 36), slice(25, 29)),
    ATTR_HEAT: (slice(40, 44), slice(40, 44)),
    ATTR_HOTWATER: (slice(24, 28), slice(24, 28)),
    ATTR_WATER: (slice(17, 20), slice(17, 20)),
}

ELEMENT_DEVICE_CLASS = {
    DEVICE_CONSUMPTION: UnitOfPower.WATT,
    ELECTRIC_REALTIME: SensorDeviceClass.POWER,
    ELECTRIC_TOTAL: SensorDeviceClass.ENERGY,
    GAS_TOTAL: SensorDeviceClass.GAS,
    WATER_TOTAL: SensorDeviceClass.WATER,
}

ELEMENT_UNIT = {
    DEVICE_CONSUMPTION: UnitOfPower.WATT,
    ELECTRIC_REALTIME: UnitOfPower.WATT,
    ELECTRIC_TOTAL: UnitOfEnergy.KILO_WATT_HOUR,
    GAS_REALTIME: UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    GAS_TOTAL: UnitOfVolume.CUBIC_METERS,
    HEAT_REALTIME: UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    HEAT_TOTAL: UnitOfVolume.CUBIC_METERS,
    HOTWATER_REALTIME: UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    HOTWATER_TOTAL: UnitOfVolume.CUBIC_METERS,
    WATER_REALTIME: UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    WATER_TOTAL: UnitOfVolume.CUBIC_METERS,
}

ELEMENT_VALUE_CONVERSION = {
    DEVICE_CONSUMPTION: lambda value: value,
    ELECTRIC_TOTAL: lambda value: round(value / 100, 2),
    ELECTRIC_REALTIME: lambda value: value,
    GAS_TOTAL: lambda value: round(value / 1000, 2),
    GAS_REALTIME: lambda value: value / 10,
    HEAT_TOTAL: lambda value: round(value / 1000, 2),
    HEAT_REALTIME: [
        lambda value: value,
        lambda value: value / 1000
    ],
    HOTWATER_TOTAL: lambda value: round(value / 1000, 2),
    HOTWATER_REALTIME: [
        lambda value: value,
        lambda value: value / 1000
    ],
    WATER_TOTAL: lambda value: round(value / 1000, 2),
    WATER_REALTIME: [
        lambda value: value,
        lambda value: value / 1000,
    ],
}

NEW_CLIMATE = "climates"
NEW_FAN = "fans"
NEW_LIGHT = "lights"
NEW_SENSOR = "sensors"
NEW_SWITCH = "switchs"

DEVICE_TYPE_MAP = {
    DEVICE_CONSUMPTION: NEW_SENSOR,
    DEVICE_CUTOFF: NEW_SWITCH,
    DEVICE_DOORLOCK: NEW_SWITCH,
    DEVICE_ENERGY: NEW_SENSOR,
    DEVICE_FAN: NEW_FAN,
    DEVICE_GAS: NEW_SWITCH,
    DEVICE_LIGHT: NEW_LIGHT,
    DEVICE_OUTLET: NEW_SWITCH,
    DEVICE_THERMOSTAT: NEW_CLIMATE,
}

DEVICE_PLATFORM_MAP = {
    DEVICE_CONSUMPTION: Platform.SENSOR,
    DEVICE_CUTOFF: Platform.SWITCH,
    DEVICE_DOORLOCK: Platform.SWITCH,
    DEVICE_ENERGY: Platform.SENSOR,
    DEVICE_FAN: Platform.FAN,
    DEVICE_GAS: Platform.SWITCH,
    DEVICE_LIGHT: Platform.LIGHT,
    DEVICE_OUTLET: Platform.SWITCH,
    DEVICE_THERMOSTAT: Platform.CLIMATE,
}

PLATFORMS = [
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

PRESET_NATURAL = "natural"
PRESET_NONE = "none"

SPEED_HIGH = 3
SPEED_LOW = 1
SPEED_MEDIUM = 2
