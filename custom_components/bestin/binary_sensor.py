"""Binary sensor platform for Bestin."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType, DeviceSubType
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin binary sensor platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def _add_device(ds: DeviceState):
        device_id = gateway.api.make_device_id(
            ds.device_type, ds.room_id, ds.device_index, ds.sub_type
        )
        if device_id not in gateway.entity_groups.setdefault("binary_sensors", set()):
            gateway.entity_groups["binary_sensors"].add(device_id)
            async_add_entities([BestinBinarySensor(gateway, ds)])
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_binary_sensors_{gateway.host}", _add_device)
    )


class BestinBinarySensor(BestinDevice, BinarySensorEntity):
    """Bestin binary sensor entity."""

    def __init__(self, gateway: BestinGateway, device_state: DeviceState):
        """Initialize binary sensor entity."""
        super().__init__(gateway, device_state)
        
        if self.device_type == DeviceType.INTERCOM:
            self._attr_device_class = BinarySensorDeviceClass.SOUND
            
            if self.sub_type == DeviceSubType.HOME_ENTRANCE:
                self._attr_name = "세대현관 벨"
                self._attr_translation_key = "intercom_home_doorbell"
            elif self.sub_type == DeviceSubType.COMMON_ENTRANCE:
                self._attr_name = "공동현관 벨"
                self._attr_translation_key = "intercom_common_doorbell"
    
    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        state = self.gateway.api.get_device_state(self.device_id)
        if state:
            return bool(state.get("state", False))
        return False
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return True
