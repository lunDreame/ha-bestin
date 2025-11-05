"""The BESTIN integration."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS, LOGGER
from .gateway import BestinGateway


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the BESTIN integration."""
    gateway = BestinGateway(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway

    if await gateway.connect(None, None):
        await gateway.async_start()
    else:
        await gateway.async_close()
        hass.data[DOMAIN].pop(entry.entry_id)
        return False
    
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.shutdown))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the BESTIN integration."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        gateway: BestinGateway = hass.data[DOMAIN].pop(entry.entry_id)
        await gateway.async_close()
    
    return unload_ok
