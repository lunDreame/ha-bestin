"""The BESTIN component."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, PLATFORMS
from .hub import BestinHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the BESTIN integration."""
    hub = BestinHub(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    LOGGER.debug(f"entry_data: {entry.data}, unique_id: {entry.unique_id}")

    if "version" not in entry.data:
        if not await hub.connect():
            LOGGER.warning(f"Hub connection failed: {hub.hub_id}")
            await hub.async_close()
            
            hass.data[DOMAIN].pop(entry.entry_id)
            return False

        LOGGER.debug(f"Hub connected: {hub.hub_id}")
        await hub.async_initialize_serial()
    else:
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
