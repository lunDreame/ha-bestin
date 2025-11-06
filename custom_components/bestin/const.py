"""Constants for Bestin integration."""

import logging

from enum import IntEnum

from homeassistant.const import Platform

DOMAIN = "bestin"

VERSION = "2.0.0"

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

LOGGER = logging.getLogger(__package__)

DEFAULT_PORT = 8899

NEW_BINARY_SENSOR = "binary_sensors"
NEW_CLIMATE = "climates"
NEW_FAN = "fans"
NEW_LIGHT = "lights"
NEW_SENSOR = "sensors"
NEW_SWITCH = "switchs"


class DeviceType(IntEnum):
    """Device types supported by Bestin wallpad."""
    THERMOSTAT = 1
    VENTILATION = 2
    DIMMINGLIGHT = 3
    LIGHT = 4
    OUTLET = 5
    ENERGY = 6
    DOORLOCK = 7
    ELEVATOR = 8
    GASVALVE = 9
    BATCHSWITCH = 10
    INTERCOM = 11


class DeviceSubType(IntEnum):
    """Sub-types for devices (for sensors and special features)."""
    NONE = 0
    POWER_USAGE = 1
    CUTOFF_VALUE = 2
    STANDBY_CUTOFF = 3
    DIRECTION = 4
    FLOOR = 5
    COMMON_ENTRANCE = 6
    HOME_ENTRANCE = 7
    COMMON_ENTRANCE_SCHEDULE = 8
    HOME_ENTRANCE_SCHEDULE = 9


class ThermostatMode(IntEnum):
    """Thermostat system modes."""
    OFF = 0
    HEAT = 1


class FanMode(IntEnum):
    """Fan speed modes for ventilation."""
    OFF = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class ElevatorState(IntEnum):
    """Elevator states."""
    IDLE = 0
    CALLED = 1
    MOVING_DOWN = 2
    MOVING_UP = 3
    ARRIVED = 4


class EnergyType(IntEnum):
    """Energy meter types (HEMS)."""
    ELECTRIC = 0x01
    WATER = 0x02
    HOTWATER = 0x03
    GAS = 0x04
    HEAT = 0x05


class IntercomType(IntEnum):
    """Intercom entrance types."""
    HOME = 1
    COMMON = 2
