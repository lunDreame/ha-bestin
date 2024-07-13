"""Fan platform for BESTIN"""

from __future__ import annotations
from typing import Any, Optional

from homeassistant.components.fan import (
    DOMAIN,
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import (
    LOGGER,
    NEW_FAN,
    PRESET_NATURAL,
    PRESET_NONE,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MEDIUM,
)
from .device import BestinDevice
from .gateway import load_gateway_from_entry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup fan platform."""
    gateway = load_gateway_from_entry(hass, config_entry)
    gateway.entities[DOMAIN] = set()

    @callback
    def async_add_fan(devices=None):
        if devices is None:
            devices = gateway.api.fans

        entities = [
            BestinFan(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entities[DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_FAN), async_add_fan
        )
    )
    async_add_fan()


class BestinFan(BestinDevice, FanEntity):
    """Defined the Fan."""
    TYPE = DOMAIN

    def __init__(self, device, gateway) -> None:
        """Initialize the fan."""
        super().__init__(device, gateway)
        self._supported_features = FanEntityFeature.SET_SPEED
        self._supported_features |= FanEntityFeature.PRESET_MODE
        self._speed_list = [SPEED_LOW, SPEED_MEDIUM, SPEED_HIGH]
        self._preset_modes = [PRESET_NATURAL, PRESET_NONE]

    @property
    def is_on(self) -> bool:
        """Return true if fan is on."""
        return self._device.state["state"]

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._supported_features

    @property
    def percentage(self) -> Optional[int]:
        """Return the current speed percentage."""
        return ordered_list_item_to_percentage(
            self._speed_list, self._device.state["speed"]
        )

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return len(self._speed_list)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        speed = (
            percentage_to_ordered_list_item(self._speed_list, percentage)
            if percentage > 0 else 0
        )
        self._on_command(speed=speed)

    @property
    def preset_mode(self):
        """Return the preset mode."""
        return self._device.state["preset"]

    @property
    def preset_modes(self) -> list:
        """Return the list of available preset modes."""
        return self._preset_modes

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        self._on_command(
            preset=False if preset_mode == PRESET_NONE else preset_mode
        )

    async def async_turn_on(
        self,
        speed: Optional[str] = None,
        percentage: Optional[int] = None,
        preset_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Turn on fan."""
        self._on_command(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off fan."""
        self._on_command(False)
