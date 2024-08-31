"""Switch platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NEW_SWITCH
from .device import BestinDevice
from .hub import BestinHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup switch platform."""
    hub: BestinHub = BestinHub.load_hub(hass, entry)
    hub.entities[SWITCH_DOMAIN] = set()

    @callback
    def async_add_switch(devices=None):
        if devices is None:
            devices = hub.api.get_devices_from_domain(SWITCH_DOMAIN)

        entities = [
            BestinSwitch(device, hub) 
            for device in devices 
            if device.info.unique_id not in hub.entities[SWITCH_DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, hub.async_signal_new_device(NEW_SWITCH), async_add_switch
        )
    )
    async_add_switch()


class BestinSwitch(BestinDevice, SwitchEntity):
    """Defined the Switch."""
    TYPE = SWITCH_DOMAIN

    def __init__(self, device, hub: BestinHub):
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
                await self.enqueue_command("open")
            else:
                await self.enqueue_command(switch="on")
        else:
            await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        if self._version_exists:
            if self._is_gas:
                await self.enqueue_command("close")
            else:
                await self.enqueue_command(switch="off")
        else:
            await self.enqueue_command(False)
