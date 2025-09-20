"""Switch platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SwitchEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NEW_SWITCH
from .device import BestinDevice
from .gateway import BestinGateway

DEVICE_ICON = {
    "outlet": "mdi:power-socket",
    "outlet:sc": "mdi:power-sleep",
    "doorlock": "mdi:door-closed",
    "elevator": "mdi:elevator-down",
    "gasvalve": "mdi:valve",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup switch platform."""
    gateway: BestinGateway = BestinGateway.get_gateway(hass, entry)
    gateway.entity_groups[SWITCH_DOMAIN] = set()

    @callback
    def async_add_switch(devices=None):
        if devices is None:
            devices = gateway.api.get_devices_from_domain(SWITCH_DOMAIN)

        entities = [
            BestinSwitch(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entity_groups[SWITCH_DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_SWITCH), async_add_switch
        )
    )
    async_add_switch()


class BestinSwitch(BestinDevice, SwitchEntity):
    """Defined the Switch."""
    TYPE = SWITCH_DOMAIN
    
    def __init__(self, device, gateway: BestinGateway):
        """Initialize the switch."""
        super().__init__(device, gateway)
        self._attr_icon = DEVICE_ICON.get(self._device_info.device_type)

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._device_info.state
    
    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        await self.enqueue_command(True)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        await self.enqueue_command(False)
