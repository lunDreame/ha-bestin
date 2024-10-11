"""The BESTIN component."""

from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, PLATFORMS, CONF_SESSION
from .hub import BestinHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the BESTIN integration."""
    hub = BestinHub(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    if CONF_SESSION not in entry.data:
        try:
            await asyncio.wait_for(hub.connect(), timeout=5)
        except asyncio.TimeoutError as ex:
            await hub.async_close()
            hass.data[DOMAIN].pop(entry.entry_id)
            raise ConfigEntryNotReady(f"Connection to {hub.hub_id} timed out.") from ex

        LOGGER.info("Start serial initialization.")
        await hub.async_initialize_serial()
    else:
        LOGGER.info("Start center initialization.")
        await hub.async_initialize_center()
    
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, hub.shutdown)
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the BESTIN integration."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        hub: BestinHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_close()
    
    return unload_ok
