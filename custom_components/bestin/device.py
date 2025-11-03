"""Base device class for Bestin integration."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.core import callback

from .const import DOMAIN, DeviceType
from .protocol import DeviceState


class BestinDevice(Entity):
    """Base class for Bestin devices."""
    
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, gateway, device_state: DeviceState):
        """Initialize Bestin device."""
        self.gateway = gateway
        self.device_type = device_state.device_type
        self.room_id = device_state.room_id
        self.device_index = device_state.device_index
        self.sub_type = device_state.sub_type
        
        self.device_id = self.gateway.api.make_device_id(
            self.device_type, self.room_id, self.device_index, self.sub_type
        )
        self._attr_unique_id = f"{self.device_id}_{self.gateway.host}"
        
        if hasattr(self, "entity_description") and self.entity_description:
            self._attr_translation_placeholders = {
                "room_id": str(self.room_id),
                "device_num": str(self.device_index + 1),
            }
    
    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        is_main = self.device_type in [
            DeviceType.VENTILATION,
            DeviceType.GASVALVE,
            DeviceType.DOORLOCK,
            DeviceType.ELEVATOR,
            DeviceType.BATCHSWITCH
        ]
        
        return DeviceInfo(
            identifiers={(
                DOMAIN, 
                f"bestin_{self.gateway.host}" 
                if is_main else f"bestin_{self.gateway.host}_{self.device_type.name.lower()}"
            )},
            name="BESTIN" if is_main else f"BESTIN {self.device_type.name}",
            manufacturer="HDC Labs Co., Ltd.",
            model="BESTIN Wallpad",
            sw_version=self.gateway.sw_version,
        )
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.gateway.available
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes."""
        return {
            "device_type": self.device_type.name.lower(),
            "room_id": self.room_id,
            "device_index": self.device_index,
        }
    
    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self.gateway.api.register_callback(self.device_id, self._handle_update)
    
    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self.gateway.api.remove_callback(self.device_id, self._handle_update)
    
    @callback
    def _handle_update(self) -> None:
        """Handle device state update."""
        self.async_write_ha_state()
