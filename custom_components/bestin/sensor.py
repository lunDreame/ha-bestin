"""Sensor platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.sensor import DOMAIN as DOMAIN_SENSOR
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    NEW_SENSOR,
    ELEMENT_VALUE_CONVERSION,
    ELEMENT_DEVICE_CLASS,
    ELEMENT_UNIT,
)
from .device import BestinDevice
from .hub import BestinHub


def extract_and_transform(identifier: str) -> str:
    if "energy_" in identifier:
        extracted_segment = identifier.split("energy_")[1]
    else:
        extracted_segment = ':'.join([identifier.split("_")[1], identifier.split("_")[3]])

    transformed_segment = extracted_segment.replace("_", ":")
    return transformed_segment


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup sensor platform."""
    hub: BestinHub = BestinHub.get_hub(hass, entry)
    hub.entity_groups[DOMAIN_SENSOR] = set()

    @callback
    def async_add_sensor(devices=None):
        if devices is None:
            devices = hub.api.get_devices_from_domain(DOMAIN_SENSOR)

        entities = [
            BestinSensor(device, hub) 
            for device in devices 
            if device.unique_id not in hub.entity_groups[DOMAIN_SENSOR]
        ]

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, hub.async_signal_new_device(NEW_SENSOR), async_add_sensor
        )
    )
    async_add_sensor()


class BestinSensor(BestinDevice):
    """Defined the Sensor."""
    TYPE = DOMAIN_SENSOR

    def __init__(self, device, hub) -> None:
        """Initialize the sensor."""
        super().__init__(device, hub)
        self._attr_id = extract_and_transform(self._device_info.device_id)
        self._is_general = hub.wp_version == "General"
    
    @property
    def state(self):
        """Return the state of the sensor."""
        if self._attr_id not in ELEMENT_VALUE_CONVERSION:
            raise ValueError(f"Invalid attribute ID: {self._attr_id}")

        factor = ELEMENT_VALUE_CONVERSION[self._attr_id]
        if isinstance(factor, list) and len(factor) == 2:
            factor = factor[0] if self._is_general else factor[1]
        
        return factor(self._device_info.state)
    
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
