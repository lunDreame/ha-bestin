"""Climate platform for Bestin."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType, ThermostatMode
from .entity_descriptions import CLIMATE_DESCRIPTIONS
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin climate platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_climates_{gateway.host}",
                                 lambda ds: async_add_entities([BestinClimate(gateway, ds)]))
    )


class BestinClimate(BestinDevice, ClimateEntity):
    """Bestin climate entity."""
    
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.TURN_ON |
        ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5
    _attr_max_temp = 40
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, gateway: BestinGateway, device_state: DeviceState):
        """Initialize climate entity."""
        self.entity_description = CLIMATE_DESCRIPTIONS[0]
        super().__init__(gateway, device_state)

    def _get_state(self, key: str, default: Any = None) -> Any:
        """Get state value."""
        state = self.gateway.api.get_device_state(self.device_id)
        return state.get(key, default) if state else default

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        return self._get_state("hvac_mode", HVACMode.OFF)
    
    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        return self._get_state("current_temperature")
    
    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        return self._get_state("target_temperature")
    
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        await self.gateway.api.send_command(
            DeviceType.THERMOSTAT, self.room_id, self.device_index,
            mode=ThermostatMode.HEAT if hvac_mode == HVACMode.HEAT else ThermostatMode.OFF
        )
    
    async def async_set_temperature(self, **kwargs) -> None:
        """Set target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.gateway.api.send_command(
                DeviceType.THERMOSTAT, self.room_id, self.device_index, temperature=float(temp)
            )
    
    async def async_turn_on(self) -> None:
        """Turn on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)
    
    async def async_turn_off(self) -> None:
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
