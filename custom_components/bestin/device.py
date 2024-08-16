"""Base class for BESTIN devices."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.core import callback

from .const import DOMAIN, MAIN_DEVICES


class BestinBase:
    """Base class for BESTIN devices."""

    def __init__(self, device, hub):
        """Set up device and update callbacks."""
        self._device = device
        self.hub = hub

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device.info.unique_id

    @property
    def device_type_name(self) -> str:
        """Returns the formatted device type name."""
        device_type = self._device.info.device_type
        return (device_type.split(":")[0].title() 
                if ":" in device_type else device_type.title())

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        if self._device.info.device_type in MAIN_DEVICES:
            return DeviceInfo(
                connections={(self.hub.hub_id, self.unique_id)},
                identifiers={(DOMAIN, f"{self.hub.wp_version}_{self.hub.model}")},
                manufacturer="HDC Labs Co., Ltd.",
                model=self.hub.wp_version,
                name=self.hub.name,
                sw_version=self.hub.sw_version,
                via_device=(DOMAIN, self.hub.hub_id),
            )
        return DeviceInfo(
            connections={(self.hub.hub_id, self.unique_id)},
            identifiers={(DOMAIN, f"{self.hub.wp_version}_{self.device_type_name}")},
            manufacturer="HDC Labs Co., Ltd.",
            model=self.hub.wp_version,
            name=f"{self.hub.name} {self.device_type_name}",
            sw_version=self.hub.sw_version,
            via_device=(DOMAIN, self.hub.hub_id),
        )

    async def _on_command(self, data: Any = None, **kwargs):
        """Send commands to the device."""
        await self._device.on_command(self.unique_id, data, **kwargs)


class BestinDevice(BestinBase, Entity):
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
            "device_type": self._device.info.device_type,
        }
        if self.should_poll:
            attributes["last_update_time"] = self.hub.api.last_update_time
        return attributes
