"""The BESTIN component."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, LOGGER, PLATFORMS
from .gateway import BestinGateway


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the BESTIN integration."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up the BESTIN integration."""
    gateway: BestinGateway = BestinGateway(hass, config_entry)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = gateway

    if connected := gateway.connect():
        LOGGER.debug(f"Gateway connected: {connected} (Host: {gateway.host})")
        
        await gateway.async_load_entity_registry()
        await gateway.async_initialize_gateway()
        
        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
        config_entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.shutdown)
        )
    else:
        LOGGER.debug("Gateway connection failed")
        
        hass.data[DOMAIN][config_entry.entry_id].shutdown()
        hass.data[DOMAIN].pop(config_entry.entry_id)
        return False

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload the BESTIN integration."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        hass.data[DOMAIN][config_entry.entry_id].shutdown()
        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok
