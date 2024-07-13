"""Sensor platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.sensor import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ELEMENT_DEVICE_CLASS,
    ELEMENT_UNIT,
    ELEMENT_VALUE_CONVERSION,
    LOGGER,
    NEW_SENSOR,
)
from .device import BestinDevice
from .gateway import load_gateway_from_entry

def extract_and_transform(identifier: str) -> str:
    if "energy_" in identifier:
        extracted_segment = identifier.split("energy_")[1].split("-")[0]
    else:
        extracted_segment = ':'.join(
            [identifier.split("_")[1], identifier.split("_")[3]]
        )
    transformed_segment = extracted_segment.replace("_", ":")
    return transformed_segment


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup sensor platform."""
    gateway = load_gateway_from_entry(hass, config_entry)
    gateway.entities[DOMAIN] = set()

    @callback
    def async_add_sensor(devices=None):
        if devices is None:
            devices = gateway.api.sensors
            
        entities = [
            BestinSensor(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entities[DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_SENSOR), async_add_sensor
        )
    )
    async_add_sensor()


class BestinSensor(BestinDevice):
    """Defined the Sensor."""
    TYPE = DOMAIN

    def __init__(self, device, gateway) -> None:
        """Initialize the sensor."""
        super().__init__(device, gateway)
        self._attr_id = extract_and_transform(self.unique_id)
    
    @property
    def state(self):
        """Return the state of the sensor."""
        factor = ELEMENT_VALUE_CONVERSION[self._attr_id]
        if isinstance(factor, list) and len(factor) == 2:
            if self.gateway.wp_ver == "General":
                factor = factor[0] 
            else:
                factor = factor[1]
        return factor(self._device.state)
    
    @property
    def device_class(self):
        """Return the class of the sensor."""
        return ELEMENT_DEVICE_CLASS.get(self._attr_id, None)

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this sensor."""
        return ELEMENT_UNIT.get(self._attr_id, None)

    @property
    def state_class(self):
        """Type of this sensor state."""
        return (
            # measurement: consumption, realtime
            "total_increasing" if "total" in self._attr_id else "measurement"
        )
