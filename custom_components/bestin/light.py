"""Light platform for BESTIN"""

from __future__ import annotations

from typing import Optional

from homeassistant.components.light import (
    ColorMode,
    DOMAIN as LIGHT_DOMAIN,
    LightEntity,
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_OFF, ATTR_STATE
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_VERSION, NEW_LIGHT
from .device import BestinDevice
from .hub import BestinHub


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
        
        self._max_color_temp_kelvin = 5700  # 5700K
        self._min_color_temp_kelvin = 3000  # 3000K
        
        # [3000, 3300, 3600, 3900, 4200, 4500, 4800, 5100, 5400, 5700]
        self._color_temp_levels = list(range(3000, 5701, 300))

        self._version_exists = getattr(hub.api, CONF_VERSION, False)

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
        brightness = state[COLOR_MODE_BRIGHTNESS]
        color_temp = state[COLOR_MODE_COLOR_TEMP]

        if brightness:
            self._color_mode = ColorMode.BRIGHTNESS
            self._supported_color_modes = {ColorMode.BRIGHTNESS}
        if brightness and color_temp:
            self._color_mode = ColorMode.COLOR_TEMP
            self._supported_color_modes = {ColorMode.COLOR_TEMP}
        
        return state[ATTR_STATE]
    
    def convert_brightness(
        self,
        brightness: int,
        reverse: bool = False
    ) -> int:
        """Convert the brightness value."""
        brightness_step = (
            10 if self._device_info.device_type == "smartlight"
            else 1
        )
        if reverse:
            # Converts the ones place of a given two-digit number to 0.
            value = round(brightness / 2.55)
            return ((value // 10) * 10) // brightness_step
        else:
            return round((brightness * brightness_step) * 2.55)
    
    def convert_color_temp(
        self,
        color_temp: int,
        reverse: bool = False
    ) -> int:
        """Convert the color temperature value."""
        color_temp_step = (
            1 if self._device_info.device_type == "smartlight"
            else 10
        )
        if reverse:
            for i, temp in enumerate(self._color_temp_levels):
                if color_temp < temp:
                    return color_temp_step * i
            return color_temp_step * 10
        else:
            index = max((color_temp // color_temp_step) - 1, 0)
            return self._color_temp_levels[index]

    def set_light_command(
        self,
        state: str,
        brightness: int | None,
        color_temp: int | None
    ) -> dict:
        light_command = {
            ATTR_STATE: state,
            "dimming": str(brightness) if brightness is not None else "null",
            "color": str(color_temp) if color_temp is not None else "null",
        }
        return light_command

    @property
    def brightness(self) -> Optional[int]:
        """Return the current brightness."""
        brightness_value = self._device_info.state[COLOR_MODE_BRIGHTNESS]
        return self.convert_brightness(brightness_value)
    
    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """The current color temperature in Kelvin."""
        color_temp_value = self._device_info.state[COLOR_MODE_COLOR_TEMP]
        return self.convert_color_temp(color_temp_value)

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
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        color_temp = kwargs.get(ATTR_COLOR_TEMP_KELVIN)

        command_kwargs = {}
        if brightness:
            brightness = self.convert_brightness(brightness, reverse=True)
            command_kwargs[COLOR_MODE_BRIGHTNESS] = brightness
        if color_temp:
            color_temp = self.convert_color_temp(color_temp, reverse=True)
            command_kwargs[COLOR_MODE_COLOR_TEMP] = color_temp

        if self._version_exists:
            light_command = self.set_light_command(STATE_ON, brightness, color_temp)

            switch = light_command if self._has_smartlight else STATE_ON
            await self.enqueue_command(switch=switch)
        elif command_kwargs:
            await self.enqueue_command(**command_kwargs)
        else:
            await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        color_temp = kwargs.get(ATTR_COLOR_TEMP_KELVIN)

        if self._version_exists:
            light_command = self.set_light_command(STATE_OFF, brightness, color_temp)

            switch = light_command if self._has_smartlight else STATE_OFF
            await self.enqueue_command(switch=switch)
        else:
            await self.enqueue_command(False)
