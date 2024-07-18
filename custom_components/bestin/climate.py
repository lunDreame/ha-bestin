"""Climate platform for BESTIN"""

from __future__ import annotations

from homeassistant.components.climate import DOMAIN, ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LOGGER, NEW_CLIMATE
from .device import BestinDevice
from .gateway import load_gateway_from_entry


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Setup climate platform."""
    gateway = load_gateway_from_entry(hass, config_entry)
    gateway.entities[DOMAIN] = set()

    @callback
    def async_add_climate(devices=None):
        if devices is None:
            devices = gateway.api.climates

        entities = [
            BestinClimate(device, gateway) 
            for device in devices 
            if device.unique_id not in gateway.entities[DOMAIN]
        ]

        if entities:
            async_add_entities(entities)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_CLIMATE), async_add_climate
        )
    )
    async_add_climate()


class BestinClimate(BestinDevice, ClimateEntity):
    """Defined the Climate."""
    TYPE = DOMAIN
    
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, device, gateway):
        """Initialize the climate."""
        super().__init__(device, gateway)
        self._supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._supported_features |= ClimateEntityFeature.TURN_ON
        self._supported_features |= ClimateEntityFeature.TURN_OFF
        self._hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._preset_modes = []

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._supported_features
    
    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        return self._device.state["mode"]

    @property
    def hvac_modes(self) -> list:
        """Return the list of available hvac operation modes."""
        return self._hvac_modes

    async def async_turn_on(self) -> None:
        """Turn the entity on."""

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        
    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        if hvac_mode not in self.hvac_modes:
            raise ValueError(f"Unsupported HVAC mode {hvac_mode}")
        await self._on_command(mode=True if hvac_mode == HVACMode.HEAT else False)

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp.
        Requires ClimateEntityFeature.PRESET_MODE.
        """

    @property
    def preset_modes(self) -> list:
        """Return the list of available preset modes."""
        return self._preset_modes
 
    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""

    @property
    def hvac_action(self):
        """Return the current action."""

    @property
    def current_temperature(self) -> float:
        """Return the current temperature."""
        return self._device.state["current_temperature"]

    @property
    def target_temperature(self) -> float:
        """Return the target temperature."""
        return self._device.state["target_temperature"]

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            raise ValueError(f"Expected attribute {ATTR_TEMPERATURE}")
        await self._on_command(set_temperature=(float(kwargs[ATTR_TEMPERATURE])))

    @property
    def temperature_unit(self) -> UnitOfTemperature:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def max_temp(self):
        """Max tempreature."""
        return 40

    @property
    def min_temp(self):
        """Min tempreature."""
        return 5

    @property
    def target_temperature_step(self):
        """Step tempreature."""
        return 0.5
