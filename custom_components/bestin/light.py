"""Light platform for BESTIN"""

from __future__ import annotations

import math
from typing import Optional

from homeassistant.components.light import (
    ColorMode,
    DOMAIN as LIGHT_DOMAIN,
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import value_to_brightness
from homeassistant.util.percentage import percentage_to_ranged_value

from .const import NEW_LIGHT
from .device import BestinDevice
from .hub import BestinHub

BRIGHTNESS_SCALE = (1, 100)

COLOR_TEMP_SCALE = (3000, 5700)  # Kelvin values for the 10 steps
COLOR_TEMP_LEVELS = list(range(COLOR_TEMP_SCALE[0], COLOR_TEMP_SCALE[1]+1, 300))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup light platform."""
    hub: BestinHub = BestinHub.get_hub(hass, entry)
    hub.entity_groups[LIGHT_DOMAIN] = set()

    @callback
    def async_add_light(devices=None):
        if devices is None:
            devices = hub.api.get_devices_from_domain(LIGHT_DOMAIN)

        entities = [
            BestinLight(device, hub) 
            for device in devices 
            if device.unique_id not in hub.entity_groups[LIGHT_DOMAIN]
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
        self._has_smartlight = False
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
        state = self._device_info.state
        if isinstance(state, dict):
            self._has_smartlight = True
            state = self.state_parse(state)

        return state
    
    def state_parse(self, state: dict) -> bool:
        """State parse for smartlight."""
        brightness = state["brightness"]
        color_temp = state["color_temp"]

        if brightness:
            self._color_mode = ColorMode.BRIGHTNESS
            self._supported_color_modes = {ColorMode.BRIGHTNESS}
        if brightness and color_temp:
            self._color_mode = ColorMode.COLOR_TEMP
            self._supported_color_modes = {ColorMode.COLOR_TEMP}
        
        return state["is_on"]
    
    def convert_brightness(
        self,
        brightness: int,
        reverse: bool = False
    ) -> int:
        """Convert the brightness value."""
        if reverse:
            result = (brightness - 1) * (100 - 1) / (255 - 1) + 1
            return round(result / 10) * 10
        else:
            return int((brightness - 1) * (255 - 1) / (100 - 1) + 1)
    
    def convert_color_temp(
        self,
        color_temp: int,
        reverse: bool = False
    ) -> int:
        """Convert the color temperature value."""
        if reverse:
            for i, temp in enumerate(COLOR_TEMP_LEVELS):
                if color_temp < temp:
                    return i * 10
            return 100
        else:
            return COLOR_TEMP_LEVELS[(color_temp // 10) - 1]

    def set_light_command(
        self,
        state: str,
        brightness: int | None,
        kelvin: int | None
    ) -> dict:
        brightness_value = kelvin_value = "null"
        if brightness is not None:
            brightness_value = str(self.convert_brightness(brightness, reverse=True))
        if kelvin is not None:
            kelvin_value = str(self.convert_color_temp(kelvin, reverse=True))
        
        light_command = {
            "state": state,
            "dimming": brightness_value,
            "color": kelvin_value,
        }
        return light_command

    @property
    def brightness(self) -> Optional[int]:
        """Return the current brightness."""
        brightness_value = self._device_info.state["brightness"]
        return self.convert_brightness(brightness_value)
    
    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """The current color temperature in Kelvin."""
        color_temp_step = self._device_info.state["color_temp"]
        return self.convert_color_temp(color_temp_step)

    @property
    def max_color_temp_kelvin(self) -> int:
        """The highest supported color temperature in Kelvin."""
        return self._max_color_temp_kelvin

    @property
    def min_color_temp_kelvin(self) -> int:
        """The lowest supported color temperature in Kelvin."""
        return self._min_color_temp_kelvin

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        if self._version_exists:
            brightness = kwargs.get(ATTR_BRIGHTNESS)
            kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)

            light_command = self.set_light_command("on", brightness, kelvin)

            switch = light_command if self._has_smartlight else "on"
            await self.enqueue_command(switch=switch)
        else:
            await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        if self._version_exists:
            brightness = kwargs.get(ATTR_BRIGHTNESS)
            kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)

            light_command = self.set_light_command("off", brightness, kelvin)

            switch = light_command if self._has_smartlight else "off"
            await self.enqueue_command(switch=switch)
        else:
            await self.enqueue_command(False)
