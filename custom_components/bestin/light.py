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

from .const import NEW_LIGHT
from .device import BestinDevice
from .hub import load_hub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup light platform."""
    hub = load_hub(hass, entry)
    hub.entities[DOMAIN] = set()

    @callback
    def async_add_light(devices=None):
        if devices is None:
            devices = hub.api.get_devices_from_domain(DOMAIN)

        entities = [
            BestinLight(device, hub) 
            for device in devices 
            if device.info.id not in hub.entities[DOMAIN]
        ]
        
        if entities:
            async_add_entities(entities)

    hub.listeners.append(
        async_dispatcher_connect(
            hass, hub.async_signal_new_device(NEW_LIGHT), async_add_light
        )
    )
    async_add_light()


class BestinLight(BestinDevice, LightEntity):
    """Defined the Light."""
    TYPE = DOMAIN

    def __init__(self, device, hub):
        """Initialize the light."""
        super().__init__(device, hub)
        self._color_mode = ColorMode.ONOFF
        self._supported_color_modes = {ColorMode.ONOFF}
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
        return self._device.info.state

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        if self._version_exists:
            await self._on_command(switch="on")
        else:
            await self._on_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        if self._version_exists:
            await self._on_command(switch="off")
        else:
            await self._on_command(False)
