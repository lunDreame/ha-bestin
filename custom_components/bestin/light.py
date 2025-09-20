"""Light platform for BESTIN"""

from __future__ import annotations

from typing import Optional

from homeassistant.components.light import (
    ColorMode,
    DOMAIN as LIGHT_DOMAIN,
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NEW_LIGHT
from .device import BestinDevice
from .gateway import BestinGateway


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup light platform."""
    gateway: BestinGateway = BestinGateway.get_gateway(hass, entry)
    gateway.entity_groups[LIGHT_DOMAIN] = set()

    @callback
    def async_add_light(devices=None):
        if devices is None:
            devices = gateway.api.get_devices_from_domain(LIGHT_DOMAIN)

        entities = [
            BestinLight(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entity_groups[LIGHT_DOMAIN]
        ]
        
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_LIGHT), async_add_light
        )
    )
    async_add_light()


class BestinLight(BestinDevice, LightEntity):
    """Define the Light."""
    TYPE = LIGHT_DOMAIN

    def __init__(self, device, gateway):
        """Initialize the light."""
        super().__init__(device, gateway)
        self._is_dimmable = False
        self._color_mode = ColorMode.ONOFF
        self._supported_color_modes = {ColorMode.ONOFF}
        
        self._max_color_temp_kelvin = 5700  # 5700K
        self._min_color_temp_kelvin = 3000  # 3000K
        
        # [3000, 3300, 3600, 3900, 4200, 4500, 4800, 5100, 5400, 5700]
        self._color_temp_levels = list(range(3000, 5701, 300))

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
            self._is_dimmable = True
            state = self.state_parse(state)
        return state
    
    def state_parse(self, state: dict) -> bool:
        """State parse for dimmable light."""
        brightness = state["brightness"]
        color_temp = state["color_temp"]

        if brightness:
            self._color_mode = ColorMode.BRIGHTNESS
            self._supported_color_modes = {ColorMode.BRIGHTNESS}
        if brightness and color_temp:
            self._color_mode = ColorMode.COLOR_TEMP
            self._supported_color_modes = {ColorMode.COLOR_TEMP}
        return state["state"]
    
    def convert_brightness(self, brightness: int, reverse: bool = False) -> int:
        """Convert the brightness value."""
        if reverse:
            # Converts the ones place of a given two-digit number to 0.
            value = round(brightness / 2.55)
            return ((value // 10) * 10) // 1
        else:
            return round((brightness * 1) * 2.55)
    
    def convert_color_temp(self, color_temp: int, reverse: bool = False) -> int:
        """Convert the color temperature value."""
        if reverse:
            for i, temp in enumerate(self._color_temp_levels):
                if color_temp < temp:
                    return 10 * i
            return 100
        else:
            index = max((color_temp // 10) - 1, 0)
            return self._color_temp_levels[index]
    
    @property
    def brightness(self) -> Optional[int]:
        """Return the current brightness."""
        brightness_value = self._device_info.state["brightness"]
        return self.convert_brightness(brightness_value)
    
    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """The current color temperature in Kelvin."""
        color_temp_value = self._device_info.state["color_temp"]
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
            command_kwargs["brightness"] = brightness
        if color_temp:
            color_temp = self.convert_color_temp(color_temp, reverse=True)
            command_kwargs["color_temp"] = color_temp

        if command_kwargs:
            await self.enqueue_command(**command_kwargs)
        else:
            await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        color_temp = kwargs.get(ATTR_COLOR_TEMP_KELVIN)

        await self.enqueue_command(False)
