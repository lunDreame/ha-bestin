"""Fan platform for Bestin."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import ordered_list_item_to_percentage, percentage_to_ordered_list_item

from .const import DOMAIN, DeviceType, FanMode
from .entity_descriptions import FAN_DESCRIPTIONS
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin fan platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_fans_{gateway.host}",
                                 lambda ds: async_add_entities([BestinFan(gateway, ds)]))
    )


class BestinFan(BestinDevice, FanEntity):
    """Bestin fan entity."""
    
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED |
        FanEntityFeature.PRESET_MODE |
        FanEntityFeature.TURN_ON |
        FanEntityFeature.TURN_OFF
    )
    _attr_preset_modes = ["natural", "none"]
    _speed_list = [1, 2, 3]

    def __init__(self, gateway: BestinGateway, device_state: DeviceState):
        """Initialize fan entity."""
        self.entity_description = FAN_DESCRIPTIONS[0]
        super().__init__(gateway, device_state)
    
    def _get_state(self, key: str, default: Any = None) -> Any:
        """Get state value."""
        state = self.gateway.api.get_device_state(self.device_id)
        return state.get(key, default) if state else default
    
    @property
    def is_on(self) -> bool:
        """Return true if fan is on."""
        return self._get_state("is_on", False)
    
    @property
    def percentage(self) -> int | None:
        """Return current speed percentage."""
        fan_mode = self._get_state("fan_mode", FanMode.OFF)
        return (
            0 if fan_mode == FanMode.OFF 
            else ordered_list_item_to_percentage(self._speed_list, int(fan_mode))
        )
    
    @property
    def speed_count(self) -> int:
        """Return number of speeds."""
        return len(self._speed_list)
    
    @property
    def preset_mode(self) -> str | None:
        """Return preset mode."""
        return self._get_state("preset_mode", "none")
    
    async def async_set_percentage(self, percentage: int) -> None:
        """Set speed percentage."""
        if percentage == 0:
            await self.async_turn_off()
        else:
            speed = percentage_to_ordered_list_item(self._speed_list, percentage)
            await self.gateway.api.send_command(
                DeviceType.VENTILATION, self.room_id, self.device_index, fan_mode=FanMode(speed)
            )
    
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        pass
    
    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        """Turn on."""
        if percentage:
            await self.async_set_percentage(percentage)
        else:
            await self.gateway.api.send_command(
                DeviceType.VENTILATION, self.room_id, self.device_index, fan_mode=FanMode.LOW
            )
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.gateway.api.send_command(
            DeviceType.VENTILATION, self.room_id, self.device_index, fan_mode=FanMode.OFF
        )
