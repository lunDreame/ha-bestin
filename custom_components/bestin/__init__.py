"""The BESTIN component."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, PLATFORMS
from .gateway import BestinGateway


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up the BESTIN integration."""
    gateway = BestinGateway(hass, config_entry)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = gateway

    LOGGER.debug(f"Entry data: {config_entry.data}, unique ID: {config_entry.unique_id}")

    if "version" not in config_entry.data:
        if not await gateway.connect():
            LOGGER.debug("Gateway connection failed")
            await gateway.shutdown()
            hass.data[DOMAIN].pop(config_entry.entry_id)
            return False

        LOGGER.debug(f"Gateway connected: {gateway.gatewayid}")
        await gateway.async_initialize_gateway()
    else:
        await gateway.initialize_control_statuses()

    await gateway.async_load_entity_registry()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.shutdown)
    )
    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload the BESTIN integration."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        await hass.data[DOMAIN][config_entry.entry_id].shutdown()

        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok
