"""Entity descriptions for Bestin integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.fan import FanEntityDescription
from homeassistant.components.light import LightEntityDescription
from homeassistant.components.sensor import SensorEntityDescription, SensorDeviceClass, SensorStateClass
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)

from .const import DeviceType, DeviceSubType


@dataclass(frozen=True, kw_only=True)
class BestinClimateEntityDescription(ClimateEntityDescription):
    """Climate entity description for Bestin."""
    device_type: DeviceType = DeviceType.THERMOSTAT


CLIMATE_DESCRIPTIONS: tuple[BestinClimateEntityDescription, ...] = (
    BestinClimateEntityDescription(
        key="thermostat",
        translation_key="thermostat",
        icon="mdi:thermostat",
        device_type=DeviceType.THERMOSTAT,
    ),
)


@dataclass(frozen=True, kw_only=True)
class BestinFanEntityDescription(FanEntityDescription):
    """Fan entity description for Bestin."""
    device_type: DeviceType = DeviceType.VENTILATION
    speed_count: int = 3
    supports_preset: bool = True


FAN_DESCRIPTIONS: tuple[BestinFanEntityDescription, ...] = (
    BestinFanEntityDescription(
        key="ventilator",
        translation_key="ventilator",
        icon="mdi:fan",
        device_type=DeviceType.VENTILATION,
        speed_count=3,
        supports_preset=True,
    ),
)


@dataclass(frozen=True, kw_only=True)
class BestinLightEntityDescription(LightEntityDescription):
    """Light entity description for Bestin."""
    device_type: DeviceType
    supports_brightness: bool = False
    supports_color_temp: bool = False


LIGHT_DESCRIPTIONS: tuple[BestinLightEntityDescription, ...] = (
    BestinLightEntityDescription(
        key="light",
        translation_key="light",
        icon="mdi:lightbulb",
        device_type=DeviceType.LIGHT,
    ),
    BestinLightEntityDescription(
        key="dimming_light",
        translation_key="dimming_light",
        icon="mdi:lightbulb",
        device_type=DeviceType.DIMMINGLIGHT,
        supports_brightness=True,
        supports_color_temp=True,
    ),
)


@dataclass(frozen=True, kw_only=True)
class BestinSensorEntityDescription(SensorEntityDescription):
    """Sensor entity description for Bestin."""
    device_type: DeviceType
    sub_type: DeviceSubType = DeviceSubType.NONE
    value_fn: Callable[[Any], Any] | None = None


SENSOR_DESCRIPTIONS: tuple[BestinSensorEntityDescription, ...] = (
    BestinSensorEntityDescription(
        key="light_power",
        translation_key="light_power",
        icon="mdi:flash",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_type=DeviceType.LIGHT,
        sub_type=DeviceSubType.POWER_USAGE,
    ),
    BestinSensorEntityDescription(
        key="dimming_light_power",
        translation_key="dimming_light_power",
        icon="mdi:flash",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_type=DeviceType.DIMMINGLIGHT,
        sub_type=DeviceSubType.POWER_USAGE,
    ),
    BestinSensorEntityDescription(
        key="outlet_power",
        translation_key="outlet_power",
        icon="mdi:flash",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_type=DeviceType.OUTLET,
        sub_type=DeviceSubType.POWER_USAGE,
    ),
    BestinSensorEntityDescription(
        key="outlet_cutoff",
        translation_key="outlet_cutoff",
        icon="mdi:power-sleep",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_type=DeviceType.OUTLET,
        sub_type=DeviceSubType.CUTOFF_VALUE,
    ),
    BestinSensorEntityDescription(
        key="energy_electric_power",
        translation_key="electric_power",
        icon="mdi:flash",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_electric_total",
        translation_key="electric_total",
        icon="mdi:lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_water_power",
        translation_key="water_rate",
        icon="mdi:water-pump",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_water_total",
        translation_key="water_total",
        icon="mdi:water-pump",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_gas_power",
        translation_key="gas_rate",
        icon="mdi:gas-cylinder",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_gas_total",
        translation_key="gas_total",
        icon="mdi:gas-cylinder",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_hotwater_power",
        translation_key="hotwater_rate",
        icon="mdi:water-boiler",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_hotwater_total",
        translation_key="hotwater_total",
        icon="mdi:water-boiler",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_heat_power",
        translation_key="heat_rate",
        icon="mdi:radiator",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="energy_heat_total",
        translation_key="heat_total",
        icon="mdi:thermometer-lines",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_type=DeviceType.ENERGY,
        sub_type=DeviceSubType.NONE,
    ),
    BestinSensorEntityDescription(
        key="elevator_direction",
        translation_key="elevator_direction",
        icon="mdi:elevator",
        device_type=DeviceType.ELEVATOR,
        sub_type=DeviceSubType.DIRECTION,
        value_fn=lambda x: x.name if hasattr(x, 'name') else str(x),
    ),
    BestinSensorEntityDescription(
        key="elevator_floor",
        translation_key="elevator_floor",
        icon="mdi:elevator",
        device_type=DeviceType.ELEVATOR,
        sub_type=DeviceSubType.FLOOR,
    ),
)


@dataclass(frozen=True, kw_only=True)
class BestinSwitchEntityDescription(SwitchEntityDescription):
    """Switch entity description for Bestin."""
    device_type: DeviceType
    sub_type: DeviceSubType = DeviceSubType.NONE


SWITCH_DESCRIPTIONS: tuple[BestinSwitchEntityDescription, ...] = (
    BestinSwitchEntityDescription(
        key="outlet",
        translation_key="outlet",
        icon="mdi:power-socket-eu",
        device_type=DeviceType.OUTLET,
    ),
    BestinSwitchEntityDescription(
        key="outlet_standby_cutoff",
        translation_key="outlet_standby_cutoff",
        icon="mdi:power-sleep",
        device_type=DeviceType.OUTLET,
        sub_type=DeviceSubType.STANDBY_CUTOFF,
    ),
    BestinSwitchEntityDescription(
        key="gasvalve",
        translation_key="gasvalve",
        icon="mdi:valve",
        device_type=DeviceType.GASVALVE,
    ),
    BestinSwitchEntityDescription(
        key="doorlock",
        translation_key="doorlock",
        icon="mdi:door-closed",
        device_type=DeviceType.DOORLOCK,
    ),
    BestinSwitchEntityDescription(
        key="elevator",
        translation_key="elevator",
        icon="mdi:elevator-down",
        device_type=DeviceType.ELEVATOR,
    ),
    BestinSwitchEntityDescription(
        key="batch_switch",
        translation_key="batch_switch",
        icon="mdi:lightbulb-multiple-off",
        device_type=DeviceType.BATCHSWITCH,
    ),
)
