"""Base class for BESTIN devices."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.core import callback

from .const import DOMAIN, MAIN_DEVICES


def split_dt(dt: str) -> str:
    """
    Split the first part by a colon,
    if there is no colon, return the entire string.
    """
    return dt.split(":")[0].title() if ":" in dt else dt.title()


class BestinBase:
    """Base class for BESTIN devices."""

    def __init__(self, device, hub):
        """Set up device and update callbacks."""
        self._device = device
        self.hub = hub

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device.info.id

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        base_info = {
            "connections": {(self.hub.hub_id, self.unique_id)},
            "identifiers": {(DOMAIN, f"{self.hub.wp_version}_{split_dt(self._device.info.type)}")},
            "manufacturer": "HDC Labs Co., Ltd.",
            "model": self.hub.wp_version,
            "name": f"{self.hub.name} {split_dt(self._device.info.type)}",
            "sw_version": self.hub.sw_version,
            "via_device": (DOMAIN, self.hub.hub_id),
        }
        if self._device.info.type in MAIN_DEVICES:
            base_info["identifiers"] = {(DOMAIN, f"{self.hub.wp_version}_{self.hub.model}")}
            base_info["name"] = f"{self.hub.name}"

        return base_info

    async def _on_command(self, data: Any = None, **kwargs):
        """Send commands to the device."""
        await self._device.on_command(self.unique_id, data, **kwargs)


class BestinDevice(BestinBase, RestoreEntity):
    """Define the Bestin Device entity."""

    TYPE = ""

    def __init__(self, device, hub):
        """Set up device and update callbacks."""
        super().__init__(device, hub)
        self.hub.entities[self.TYPE].add(self.unique_id)

    @property
    def entity_registry_enabled_default(self):
        """Return if the entity should be enabled when first added to the entity registry."""
        return True

    async def async_added_to_hass(self):
        """Subscribe to device events."""
        self._device.add_callback(self.async_update_callback)
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect device object when removed."""
        self._device.remove_callback(self.async_update_callback)

    @callback
    def async_restore_last_state(self, last_state) -> None:
        """Restore previous state."""
        pass

    @callback
    def async_update_callback(self):
        """Update the device's state."""
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        """Return True if device is available."""
        return self.hub.available

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self._device.info.name

    @property
    def should_poll(self) -> bool:
        """Determine if the device should be polled."""
        return self.hub.is_polling

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes of the sensor."""
        attributes = {
            "unique_id": self.unique_id,
            "device_room": self._device.info.room,
            "device_type": self._device.info.type,
        }
        if self.should_poll:
            attributes["last_update_time"] = self.hub.api.last_update_time
        return attributes
