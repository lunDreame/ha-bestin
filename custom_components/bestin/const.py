"""Constants for Bestin integration."""

import logging

from enum import IntEnum

from homeassistant.const import Platform

DOMAIN = "bestin"

VERSION = "2.0.0"

PLATFORMS = [
    Platform.CLIMATE,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

LOGGER = logging.getLogger(__package__)

DEFAULT_PORT = 8899

NEW_CLIMATE = "climates"
NEW_FAN = "fans"
NEW_LIGHT = "lights"
NEW_SENSOR = "sensors"
NEW_SWITCH = "switchs"


class PacketHeader(IntEnum):
    """Packet header types for Bestin protocol."""
    BATCH_SWITCH_1 = 0x15
    BATCH_SWITCH_2 = 0x17
    DIMMING_LIGHT = 0x21
    THERMOSTAT = 0x28
    LIGHT_OUTLET_GAS = 0x31
    LIGHT_OUTLET_2 = 0x32
    LIGHT_OUTLET_3 = 0x33
    LIGHT_OUTLET_4 = 0x34
    LIGHT_OUTLET_F = 0x3F
    DOORLOCK = 0x41
    SYNC = 0x42
    AIO_LIGHT_1 = 0x51
    AIO_LIGHT_2 = 0x52
    AIO_LIGHT_3 = 0x53
    AIO_LIGHT_4 = 0x54
    AIO_LIGHT_5 = 0x55
    VENTILATOR = 0x61
    SMART_SWITCH = 0xA2
    SMART_SWITCH_C = 0xC1
    ENERGY = 0xD1


class PacketType(IntEnum):
    """Packet type codes."""
    CONTROL = 0x01
    QUERY = 0x11
    CONTROL_ACK = 0x12
    STATE = 0x21
    STATE_QUERY_ACK = 0x91
    STATE_CONTROL_ACK = 0x92
    STATE_A1 = 0xA1
    STATE_A2 = 0xA2


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
    COOKTOP = 11


class DeviceSubType(IntEnum):
    """Sub-types for devices (for sensors and special features)."""
    NONE = 0
    POWER_USAGE = 1
    CUTOFF_VALUE = 2
    STANDBY_CUTOFF = 3
    DIRECTION = 4
    FLOOR = 5


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
