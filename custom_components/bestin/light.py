"""Light platform for Bestin."""

from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType
from .entity_descriptions import LIGHT_DESCRIPTIONS
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin light platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def _add_device(ds: DeviceState):
        device_id = gateway.api.make_device_id(
            ds.device_type, ds.room_id, ds.device_index, ds.sub_type
        )
        if device_id not in gateway.entity_groups.setdefault("lights", set()):
            gateway.entity_groups["lights"].add(device_id)
            async_add_entities([BestinLight(gateway, ds)])
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_lights_{gateway.host}", _add_device)
    )


class BestinLight(BestinDevice, LightEntity):
    """Bestin light entity."""

    def __init__(self, gateway: BestinGateway, device_state: DeviceState):
        """Initialize light entity."""
        self.entity_description = next((
            d for d in LIGHT_DESCRIPTIONS 
            if d.device_type == device_state.device_type
        ), LIGHT_DESCRIPTIONS[0])
        super().__init__(gateway, device_state)
        
        if device_state.device_type == DeviceType.DIMMINGLIGHT and (
            isinstance(device_state.state, dict) and device_state.state.get("brightness") is not None
        ):
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF
    
    def _get_state(self) -> dict | bool:
        """Get current state."""
        state = self.gateway.api.get_device_state(self.device_id)
        return state.get("state") if state else False
    
    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        state = self._get_state()
        return state.get("is_on", False) if isinstance(state, dict) else bool(state)
    
    @property
    def brightness(self) -> int | None:
        """Return brightness (0-255)."""
        if self.entity_description.supports_brightness:
            state = self._get_state()
            if isinstance(state, dict) and (brightness_val := state.get("brightness")):
                return round(brightness_val * 2.55)
        return None
    
    async def async_turn_on(self, **kwargs) -> None:
        """Turn on light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        
        if self.device_type == DeviceType.DIMMINGLIGHT:
            cmd_kwargs = {"turn_on": True}
            if brightness is not None:
                cmd_kwargs["brightness"] = round(brightness / 2.55)
            await self.gateway.api.send_command(
                DeviceType.DIMMINGLIGHT, self.room_id, self.device_index, **cmd_kwargs
            )
        else:
            await self.gateway.api.send_command(
                DeviceType.LIGHT, self.room_id, self.device_index, turn_on=True
            )
    
    async def async_turn_off(self, **kwargs) -> None:
        """Turn off light."""
        await self.gateway.api.send_command(
            DeviceType.DIMMINGLIGHT 
            if self.device_type == DeviceType.DIMMINGLIGHT else DeviceType.LIGHT,
            self.room_id, self.device_index, turn_on=False
        )
