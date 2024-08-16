"""Switch platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.switch import DOMAIN, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NEW_SWITCH
from .device import BestinDevice
from .hub import load_hub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup switch platform."""
    hub = load_hub(hass, entry)
    hub.entities[DOMAIN] = set()

    @callback
    def async_add_switch(devices=None):
        if devices is None:
            devices = hub.api.get_devices_from_domain(DOMAIN)

        entities = [
            BestinSwitch(device, hub) 
            for device in devices 
            if device.info.unique_id not in hub.entities[DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    hub.listeners.append(
        async_dispatcher_connect(
            hass, hub.async_signal_new_device(NEW_SWITCH), async_add_switch
        )
    )
    async_add_switch()


class BestinSwitch(BestinDevice, SwitchEntity):
    """Defined the Switch."""
    TYPE = DOMAIN

    def __init__(self, device, hub):
        """Initialize the switch."""
        super().__init__(device, hub)
        self._is_gas = device.info.device_type == "gas"
        self._version_exists = getattr(hub.api, "version", False)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._device.info.state

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        if self._version_exists:
            if self._is_gas:
                await self._on_command("open")
            else:
                await self._on_command(switch="on")
        else:
            await self._on_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        if self._version_exists:
            if self._is_gas:
                await self._on_command("close")
            else:
                await self._on_command(switch="off")
        else:
            await self._on_command(False)
