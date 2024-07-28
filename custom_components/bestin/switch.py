"""Switch platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.switch import DOMAIN, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LOGGER, NEW_SWITCH
from .device import BestinDevice
from .gateway import load_gateway_from_entry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup switch platform."""
    gateway = load_gateway_from_entry(hass, config_entry)
    gateway.entities[DOMAIN] = set()

    @callback
    def async_add_switch(devices=None):
        if devices is None:
            devices = gateway.api.switchs

        entities = [
            BestinSwitch(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entities[DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_SWITCH), async_add_switch
        )
    )
    async_add_switch()


class BestinSwitch(BestinDevice, SwitchEntity):
    """Defined the Switch."""
    TYPE = DOMAIN

    def __init__(self, device, gateway):
        """Initialize the switch."""
        super().__init__(device, gateway)
        self._version_exists = hasattr(self.gateway.api, "version")
        
        if self._version_exists:
            self._version_exists = self.gateway.api.version

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._device.state

    async def async_turn_on(self, **kwargs):
        """Turn on switch."""
        await self._on_command(
            "on" if self._version_exists else True
        )

    async def async_turn_off(self, **kwargs):
        """Turn off switch."""
        await self._on_command(
            "off" if self._version_exists else False
        )
