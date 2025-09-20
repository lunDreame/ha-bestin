"""Sensor platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.sensor import (
    DOMAIN as DOMAIN_SENSOR,
    SensorEntity,
    SensorDeviceClass
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
    UnitOfVolumeFlowRate
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NEW_SENSOR
from .device import BestinDevice
from .gateway import BestinGateway

DEVICE_ICON = {
    "light:pu": "mdi:flash",
    "outlet:pu": "mdi:flash",
    "electric:rt": "mdi:flash",
    "electric:tl": "mdi:lightning-bolt",
    "gas:rt": "mdi:gas-cylinder",
    "gas:tl": "mdi:gas-cylinder",
    "heat:rt": "mdi:radiator",
    "heat:tl": "mdi:thermometer-lines",
    "hotwater:rt": "mdi:water-boiler",
    "hotwater:tl": "mdi:water-boiler",
    "water:rt": "mdi:water-pump",
    "water:tl": "mdi:water-pump"
}

DEVICE_CLASS = {
    "light:pu": SensorDeviceClass.POWER,
    "outlet:cv": SensorDeviceClass.POWER,
    "outlet:pu": SensorDeviceClass.POWER,
    "electric:rt": SensorDeviceClass.POWER,
    "electric:tl": SensorDeviceClass.ENERGY,
    "gas:tl": SensorDeviceClass.GAS,
    "water:tl": SensorDeviceClass.WATER,
}

DEVICE_UNIT = {
    "light:pu": UnitOfPower.WATT,
    "outlet:cv": UnitOfPower.WATT,
    "outlet:pu": UnitOfPower.WATT,
    "electric:rt": UnitOfPower.WATT,
    "electric:tl": UnitOfEnergy.KILO_WATT_HOUR,
    "gas:rt": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "gas:tl": UnitOfVolume.CUBIC_METERS,
    "heat:rt": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "heat:tl": UnitOfVolume.CUBIC_METERS,
    "hotwater:rt": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "hotwater:tl": UnitOfVolume.CUBIC_METERS,
    "water:rt": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "water:tl": UnitOfVolume.CUBIC_METERS,
}

VALUE_CONVERSION = {
    "electric:tl": lambda val, _: round(val / 100, 2),
    "gas:tl": lambda val, _: round(val / 1000, 2),
    "gas:rt": lambda val, _: val / 10,
    "heat:tl": lambda val, _: round(val / 1000, 2),
    "heat:rt": lambda val, gentype: val if gentype == "normal" else val / 1000,
    "hotwater:tl": lambda val, _: round(val / 1000, 2),
    "hotwater:rt": lambda val, gentype: val if gentype == "normal" else val / 1000,
    "water:tl": lambda val, _: round(val / 1000, 2),
    "water:rt": lambda val, gentype: val if gentype == "normal" else val / 1000,
}


def extract_and_transform(identifier: str) -> str:
    """Extract and transform the identifier to a formatted string."""
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
    gateway: BestinGateway = BestinGateway.get_gateway(hass, entry)
    gateway.entity_groups[DOMAIN_SENSOR] = set()

    @callback
    def async_add_sensor(devices=None):
        if devices is None:
            devices = gateway.api.get_devices_from_domain(DOMAIN_SENSOR)

        entities = [
            BestinSensor(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entity_groups[DOMAIN_SENSOR]
        ]

        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_SENSOR), async_add_sensor
        )
    )
    async_add_sensor()


class BestinSensor(BestinDevice, SensorEntity):
    """Defined the Sensor."""
    TYPE = DOMAIN_SENSOR

    def __init__(self, device, gateway) -> None:
        """Initialize the sensor."""
        super().__init__(device, gateway)
        self._dev_id = extract_and_transform(self._device_info.device_id)
        self._attr_icon = DEVICE_ICON.get(self._dev_id)

    @property
    def native_value(self):
        """Return the state of the sensor."""
        factor = VALUE_CONVERSION.get(self._dev_id)
        if callable(factor):
            return factor(self._device_info.state, self.gateway.api.gen_type)
        return self._device_info.state
    
    @property
    def device_class(self):
        """Return the class of the sensor."""
        return DEVICE_CLASS.get(self._dev_id)

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this sensor."""
        return DEVICE_UNIT.get(self._dev_id)

    @property
    def state_class(self):
        """Type of this sensor state."""
        if self._device_info.device_type in ["light:pu", "outlet:pu", "energy"]:
            return "total_increasing" if "total" in self._dev_id else "measurement"
        return None
