"""Light platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.light import (
    ColorMode,
    DOMAIN,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LOGGER, NEW_LIGHT
from .device import BestinDevice
from .gateway import load_gateway_from_entry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup light platform."""
    gateway = load_gateway_from_entry(hass, config_entry)
    gateway.entities[DOMAIN] = set()

    @callback
    def async_add_light(devices=None):
        if devices is None:
            devices = gateway.api.lights

        entities = [
            BestinLight(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entities[DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_LIGHT), async_add_light
        )
    )
    async_add_light()


class BestinLight(BestinDevice, LightEntity):
    """Defined the Light."""
    TYPE = DOMAIN

    def __init__(self, device, gateway):
        """Initialize the light."""
        super().__init__(device, gateway)
        self._color_mode = ColorMode.ONOFF
        self._supported_color_modes = {ColorMode.ONOFF}
    
    @property
    def color_mode(self):
        """Return the color mode of the light."""
        return self._color_mode
        
    @property
    def supported_color_modes(self):
        """Return the list of supported color modes."""
        return self._supported_color_modes
    
    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._device.state

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        await self._on_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        await self._on_command(False)
