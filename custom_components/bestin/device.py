"""Base class for BESTIN devices."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.core import callback

from .const import DOMAIN, MAIN_DEVICES


class BestinBase:
    """Base class for BESTIN devices."""

    def __init__(self, device, gateway):
        """Initialize device and gateway."""
        self._device = device
        self._device_info = device.info
        self.gateway = gateway
    
    async def enqueue_command(self, data: Any = None, **kwargs):
        """Send commands to the device."""
        await self._device.enqueue_command(self._device_info.device_id, data, **kwargs)
    
    @property
    def unique_id(self) -> str:
        """Get unique device ID."""
        return self._device.unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Get device registry information."""
        if self._device_info.device_type in MAIN_DEVICES:
            device_name = "BESTIN"
        else:
            if ":" in self._device_info.device_type:
                device_name = f"BESTIN {self._device_info.device_type.split(':')[0].upper()}"
            else:
                device_name = f"BESTIN {self._device_info.device_type.upper()}"
        return DeviceInfo(
            connections={(self.gateway.host, self.unique_id)},
            identifiers={(DOMAIN, device_name)},
            manufacturer="HDC Labs Co., Ltd.",
            model="BESTIN WALLPAD",
            name=device_name,
            sw_version=self.gateway.sw_version,
            via_device=(DOMAIN, self.gateway.host),
        )


class BestinDevice(BestinBase, Entity):
    """Define the Bestin Device entity."""

    TYPE = ""

    def __init__(self, device, gateway):
        """Initialize device and update callbacks."""
        super().__init__(device, gateway)
        self.gateway.entity_groups[self.TYPE].add(self.unique_id)
        self._attr_has_entity_name = True
        self._attr_name = self._device_info.name

    @property
    def entity_registry_enabled_default(self):
        """Check if the entity is enabled by default."""
        return True

    async def async_added_to_hass(self):
        """Subscribe to device events upon addition to HASS."""
        self._device.add_callback(self.async_update_callback)
        self.gateway.entity_to_id[self.entity_id] = self._device_info.device_id
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when the entity is removed from HASS."""
        self._device.remove_callback(self.async_update_callback)
        del self.gateway.entity_to_id[self.entity_id]
        self.gateway.entity_groups[self.TYPE].remove(self.unique_id)

    @callback
    def async_restore_last_state(self, last_state) -> None:
        """Restore the last known state (not implemented)."""
        pass

    @callback
    def async_update_callback(self):
        """Trigger an update of the device state."""
        self.async_schedule_update_ha_state()

    @property
    def available(self) -> bool:
        """Check if the device is available."""
        return self.gateway.available

    @property
    def should_poll(self) -> bool:
        """Determine if the device requires polling."""
        return False

    @property
    def extra_state_attributes(self) -> dict:
        """Get additional state attributes."""
        attributes = {
            "unique_id": self.unique_id,
            "device_room": self._device_info.room,
            "device_type": self._device_info.device_type,
        }
        return attributes
