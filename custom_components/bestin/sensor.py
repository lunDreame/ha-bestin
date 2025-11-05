"""Sensor platform for Bestin."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType
from .entity_descriptions import SENSOR_DESCRIPTIONS
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin sensor platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def _add_device(ds: DeviceState):
        device_id = gateway.api.make_device_id(
            ds.device_type, ds.room_id, ds.device_index, ds.sub_type
        )
        if device_id not in gateway.entity_groups.setdefault("sensors", set()):
            gateway.entity_groups["sensors"].add(device_id)
            async_add_entities([BestinSensor(gateway, ds)])
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_sensors_{gateway.host}", _add_device)
    )


class BestinSensor(BestinDevice, SensorEntity):
    """Bestin sensor entity."""

    def __init__(self, gateway: BestinGateway, device_state: DeviceState):
        """Initialize sensor entity."""
        self.entity_description = self._find_description(device_state)
        super().__init__(gateway, device_state)
    
    def _find_description(self, device_state: DeviceState):
        """Find matching entity description."""
        if device_state.device_type == DeviceType.ENERGY and device_state.attributes:
            energy_type = device_state.attributes.get("energy_type", "")
            sensor_type = device_state.attributes.get("sensor_type", "")
            search_key = f"energy_{energy_type}_{sensor_type}"
            
            if desc := next((d for d in SENSOR_DESCRIPTIONS if d.key == search_key), None):
                return desc
        
        return next(
            (d for d in SENSOR_DESCRIPTIONS 
            if d.device_type == device_state.device_type and d.sub_type == device_state.sub_type),
            SENSOR_DESCRIPTIONS[0]
        )
    
    @property
    def native_value(self) -> float | int | str | None:
        """Return sensor value."""
        state = self.gateway.api.get_device_state(self.device_id)
        if not state:
            return None
        
        value = state.get("state")
        return self.entity_description.value_fn(value) \
            if value is not None and self.entity_description.value_fn else value
