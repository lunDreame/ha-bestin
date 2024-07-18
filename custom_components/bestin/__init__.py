"""The BESTIN component."""

from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER, PLATFORMS
from .gateway import BestinGateway
from .api import BestinAPI


def check_ip_or_serial(unique_id: str) -> bool:
    ip_pattern = re.compile(r'^((25[0-5]|2[0-4][0-9]|[0-1]?[0-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|[0-1]?[0-9]?[0-9])$')
    serial_pattern = re.compile(r'^/dev/ttyUSB\d+$')

    if ip_pattern.match(unique_id) or serial_pattern.match(unique_id):
        return True
    else:
        return False


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up the BESTIN integration."""
    hass.data.setdefault(DOMAIN, {})

    entry_id = config_entry.entry_id
    entry_data = config_entry.data
    LOGGER.debug(f"Entry data: {entry_data}")

    if "version" in entry_data:
        coordinator = BestinAPI(hass, config_entry, entry_data["version"])
    else:
        coordinator = BestinGateway(hass, config_entry)

    hass.data[DOMAIN][entry_id] = coordinator

    if isinstance(coordinator, BestinGateway):
        if not await coordinator.connect():
            LOGGER.debug("Gateway connection failed")
            await coordinator.shutdown()
            hass.data[DOMAIN].pop(entry_id)
            return False

        LOGGER.debug(f"Gateway connected: {coordinator.host}")
        await coordinator.async_load_entity_registry()
        await coordinator.async_initialize_gateway()
        config_entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, coordinator.shutdown)
        )
    else:
        await coordinator.setup_initial_control_list()

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
        if check_ip_or_serial(config_entry.unique_id):
            await hass.data[DOMAIN][config_entry.entry_id].shutdown()

        hass.data[DOMAIN].pop(config_entry.entry_id)

    return unload_ok
