"""Base class for BESTIN devices."""
from typing import Any
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.core import callback

from .const import DOMAIN, LOGGER, MAIN_DEVICES

def split_dt(dt: str) -> str:
    """
    Split the first part by a colon,
    if there is no colon, it returns the entire string.
    """
    if ":" in dt:
        return dt.split(":")[0].title()
    else:
        return dt.title()


class BestinBase:
    """Bestin Base Class."""

    def __init__(self, device, gateway):
        """Setting up device and update callbacks."""
        self._device = device
        self.gateway = gateway

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device.unique_id

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        if self._device.type in MAIN_DEVICES:
            return {
                "connections": {(self.gateway.host, self.unique_id)},
                "identifiers": {(DOMAIN, f"{self.gateway.wp_ver}_{self.gateway.model}")},
                "manufacturer": "HDC Labs Co., Ltd.",
                "model": f"{self.gateway.wp_ver}-generation",
                "name": self.gateway.name,
                "sw_version": self.gateway.version,
                "via_device": (DOMAIN, self.gateway.host),
            }
        else:
            return {
                "connections": {(self.gateway.host, self.unique_id)},
                "identifiers": {
                    (DOMAIN, f"{self.gateway.wp_ver}_{split_dt(self._device.type)}")
                },
                "manufacturer": "HDC Labs Co., Ltd.",
                "model": f"{self.gateway.wp_ver}-generation",
                "name": f"{self.gateway.name} {split_dt(self._device.type)}",
                "sw_version": self.gateway.version,
                "via_device": (DOMAIN, self.gateway.host),
            }

    def _on_command(self, data: Any = None, **kwargs):
        """Set commands for the device."""
        self._device.on_command(self.unique_id, data, **kwargs)


class BestinDevice(BestinBase, RestoreEntity):
    """Define the Bestin Device entity."""
    TYPE = ""

    def __init__(self, device, gateway):
        """Setting up device and update callbacks."""
        super().__init__(device, gateway)
        self.gateway.entities[self.TYPE].add(self.unique_id)

    @property
    def entity_registry_enabled_default(self):
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

    async def async_added_to_hass(self):
        """Subscribe to device events."""
        self._device.on_register(self.unique_id, self.async_update_callback)
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect device object when removed."""
        self.gateway.entities[self.TYPE].remove(self.unique_id)
        self._device.on_remove(self.unique_id)

    @callback
    def async_restore_last_state(self, last_state) -> None:
        """Restore previous state."""

    @callback
    def async_update_callback(self):
        """Update the device's state."""
        self.schedule_update_ha_state()

    @property
    def available(self):
        """Return True if device is available."""
        return self.gateway.available

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._device.name

    @property
    def should_poll(self) -> bool:
        """No polling needed for this device."""
        return False

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        attributes = {
            "unique_id": self.unique_id,
            "device_room": self._device.room,
            "device_type": self._device.type,
        }
        return attributes
