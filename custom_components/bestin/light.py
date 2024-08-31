"""Light platform for BESTIN"""

from __future__ import annotations

from typing import Optional

from homeassistant.components.light import (
    ColorMode,
    DOMAIN as LIGHT_DOMAIN,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import value_to_brightness

from .const import NEW_LIGHT
from .device import BestinDevice
from .hub import BestinHub

BRIGHTNESS_SCALE = (1, 100)

COLOR_TEMP_SCALE = (3000, 5700)  # Kelvin values for the 9 steps


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup light platform."""
    hub: BestinHub = BestinHub.load_hub(hass, entry)
    hub.entities[LIGHT_DOMAIN] = set()

    @callback
    def async_add_light(devices=None):
        if devices is None:
            devices = hub.api.get_devices_from_domain(LIGHT_DOMAIN)

        entities = [
            BestinLight(device, hub) 
            for device in devices 
            if device.info.unique_id not in hub.entities[LIGHT_DOMAIN]
        ]
        
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, hub.async_signal_new_device(NEW_LIGHT), async_add_light
        )
    )
    async_add_light()


class BestinLight(BestinDevice, LightEntity):
    """Define the Light."""
    TYPE = LIGHT_DOMAIN

    def __init__(self, device, hub):
        """Initialize the light."""
        super().__init__(device, hub)
        self._is_dimming = False
        self._color_mode = ColorMode.ONOFF
        self._supported_color_modes = {ColorMode.ONOFF}
        self._max_color_temp_kelvin = COLOR_TEMP_SCALE[1]  # 5700K
        self._min_color_temp_kelvin = COLOR_TEMP_SCALE[0]  # 3000K
        self._version_exists = getattr(hub.api, "version", False)

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self._color_mode
    
    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return the list of supported color modes."""
        return self._supported_color_modes
    
    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        state = self._device.info.state
        if isinstance(state, dict):
            self._is_dimming = True
            self._color_mode = ColorMode.COLOR_TEMP
            self._supported_color_modes = {ColorMode.COLOR_TEMP}
            return state["is_on"]
        
        return state

    @property
    def brightness(self) -> Optional[int]:
        """Return the current brightness."""
        brightness_value = self._device.info.state["brightness"]
        return value_to_brightness(BRIGHTNESS_SCALE, brightness_value)
    
    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """The current color temperature in Kelvin."""
        color_temp_step = self._device.info.state["color_temp"]
        return self._map_step_to_kelvin(color_temp_step)

    @property
    def max_color_temp_kelvin(self) -> int:
        """The highest supported color temperature in Kelvin."""
        return self._max_color_temp_kelvin

    @property
    def min_color_temp_kelvin(self) -> int:
        """The lowest supported color temperature in Kelvin."""
        return self._min_color_temp_kelvin

    def _map_value_to_step(self, value: int, steps: list[int]) -> int:
        """Map a given value to the closest step in a given list of steps."""
        return min(steps, key=lambda x: abs(x - value))

    def _map_step_to_kelvin(self, step: int) -> int:
        """Map a step (1 to 9) to a Kelvin temperature value within the defined range."""
        step = max(1, min(step, 9))
        return int(self._min_color_temp_kelvin + (self._max_color_temp_kelvin - self._min_color_temp_kelvin) * (step - 1) / 8)

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        if self._version_exists:
            await self.enqueue_command(switch="on")
        else:
            await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        if self._version_exists:
            await self.enqueue_command(switch="off")
        else:
            await self.enqueue_command(False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes of the sensor."""
        attributes = {
            "unique_id": self.unique_id,
            "device_type": self.device_type,
            "device_room": self._device.info.room,
        }
        if self._is_dimming:
            attributes["brightness"] = self.brightness
            attributes["color_temp"] = self.color_temp_kelvin
        
        return attributes
