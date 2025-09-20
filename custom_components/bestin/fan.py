"""Fan platform for BESTIN"""

from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.fan import (
    DOMAIN as FAN_DOMAIN,
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

from .const import NEW_FAN
from .device import BestinDevice
from .gateway import BestinGateway


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup fan platform."""
    gateway: BestinGateway = BestinGateway.get_gateway(hass, entry)
    gateway.entity_groups[FAN_DOMAIN] = set()

    @callback
    def async_add_fan(devices=None):
        if devices is None:
            devices = gateway.api.get_devices_from_domain(FAN_DOMAIN)

        entities = [
            BestinFan(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entity_groups[FAN_DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_FAN), async_add_fan
        )
    )
    async_add_fan()


class BestinFan(BestinDevice, FanEntity):
    """Defined the Fan."""
    TYPE = FAN_DOMAIN

    def __init__(self, device, gateway) -> None:
        """Initialize the fan."""
        super().__init__(device, gateway)
        self._supported_features = FanEntityFeature.SET_SPEED
        self._supported_features |= FanEntityFeature.TURN_ON
        self._supported_features |= FanEntityFeature.TURN_OFF
        self._speed_list = self._device_info.state.get("speed_list")
        self._preset_modes = self._device_info.state.get("preset_modes")

        if self._preset_modes:
            self._supported_features |= FanEntityFeature.PRESET_MODE

    @property
    def is_on(self) -> bool:
        """Return true if fan is on."""
        return self._device_info.state["state"]

    @property
    def supported_features(self) -> FanEntityFeature:
        """Flag supported features."""
        return self._supported_features

    @property
    def percentage(self) -> Optional[int]:
        """Return the current speed percentage."""
        speed = self._device_info.state["speed"]
        if speed == 0:
            return 0
        return ordered_list_item_to_percentage(self._speed_list, speed)
    
    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return len(self._speed_list)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self.enqueue_command(False)
        else:
            percentage = percentage_to_ordered_list_item(self._speed_list, percentage)
            if percentage == 1 and self.is_on == False:
                await self.enqueue_command(True)
            else:
                await self.enqueue_command(set_percentage=percentage)

    @property
    def preset_mode(self) -> str:
        """Return the preset mode."""
        return self._device_info.state["preset_mode"]

    @property
    def preset_modes(self) -> list:
        """Return the list of available preset modes."""
        return self._preset_modes

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        await self.enqueue_command(preset_mode=preset_mode == "natural")

    async def async_turn_on(
        self,
        speed: Optional[str] = None,
        percentage: Optional[int] = None,
        preset_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Turn on fan."""
        await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off fan."""
        await self.enqueue_command(False)
