import logging

from enum import IntEnum
from typing import Callable, Optional, Set, Any
from dataclasses import dataclass, field

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

class DeviceType(IntEnum):
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

class DeviceSubType(IntEnum):
    NONE = 0
    POWER_USAGE = 1
    CUTOFF_VALUE = 2
    STANDBY_CUTOFF = 3
    DIRECTION = 4
    FLOOR = 5

MAIN_DEVICES = [
    DeviceType.VENTILATION,
    {DeviceType.ELEVATOR, DeviceSubType.DIRECTION},
    {DeviceType.ELEVATOR, DeviceSubType.FLOOR},
    DeviceType.GASVALVE,
    DeviceType.DOORLOCK,
    DeviceType.ELEVATOR,
]

PLATFORM_SIGNAL_MAP = {
    Platform.CLIMATE.value: NEW_CLIMATE,
    Platform.FAN.value: NEW_FAN,
    Platform.LIGHT.value: NEW_LIGHT,
    Platform.SENSOR.value: NEW_SENSOR,
    Platform.SWITCH.value: NEW_SWITCH,
}

DEVICE_PLATFORM_MAP = {
    DeviceType.THERMOSTAT: Platform.CLIMATE.value,
    DeviceType.VENTILATION: Platform.FAN.value,
    DeviceType.LIGHT: Platform.LIGHT.value,
    {DeviceType.LIGHT, DeviceSubType.POWER_USAGE}: Platform.SENSOR.value,      # power usage
    DeviceType.OUTLET: Platform.SWITCH.value,
    {DeviceType.OUTLET, DeviceSubType.CUTOFF_VALUE}: Platform.SENSOR.value,    # cutoff value
    {DeviceType.OUTLET, DeviceSubType.STANDBY_CUTOFF}: Platform.SWITCH.value,  # standby cutoff
    {DeviceType.OUTLET, DeviceSubType.POWER_USAGE}: Platform.SENSOR.value,     # power usage
    DeviceType.ENERGY: Platform.SENSOR.value,
    DeviceType.DOORLOCK: Platform.SWITCH.value,
    DeviceType.ELEVATOR: Platform.SWITCH.value,
    {DeviceType.ELEVATOR, DeviceSubType.DIRECTION}: Platform.SENSOR.value,
    {DeviceType.ELEVATOR, DeviceSubType.FLOOR}: Platform.SENSOR.value,
    DeviceType.GASVALVE: Platform.SWITCH.value,    
}

@dataclass(frozen=True)
class DeviceKey:
    device_type: DeviceType
    room_index: Optional[int | str]
    device_index: Optional[int | str]
    sub_type: Optional[DeviceSubType] = field(default_factory=lambda: DeviceSubType.NONE)

    @property
    def unique_id(self) -> str:
        return f"{self.device_type.value}_{self.room_index}_{self.device_index}_{self.sub_type.value}"

@dataclass(frozen=True)
class Device:
    platform: str
    key: DeviceKey
    state: Any
    attributes: dict[str, Any]
    callbacks: Set[Callable[..., None]] = field(default_factory=set)

    def add_callback(self, callback: Callable[..., None]) -> None:
        self.callbacks.add(callback)

    def remove_callback(self, callback: Callable[..., None]) -> None:
        self.callbacks.discard(callback)

    def update_callbacks(self) -> None:
        for callback in self.callbacks:
            assert callable(callback), "Callback should be callable"
            callback()
