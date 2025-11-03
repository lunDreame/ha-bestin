"""Switch platform for Bestin."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType, DeviceSubType, ElevatorState
from .entity_descriptions import SWITCH_DESCRIPTIONS
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin switch platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_switchs_{gateway.host}",
                                 lambda ds: async_add_entities([BestinSwitch(gateway, ds)]))
    )


class BestinSwitch(BestinDevice, SwitchEntity):
    """Bestin switch entity."""

    def __init__(self, gateway: BestinGateway, device_state: DeviceState):
        """Initialize switch entity."""
        self.entity_description = next(
            (d for d in SWITCH_DESCRIPTIONS 
            if d.device_type == device_state.device_type and d.sub_type == device_state.sub_type),
            SWITCH_DESCRIPTIONS[0]
        )
        super().__init__(gateway, device_state)
    
    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        state = self.gateway.api.get_device_state(self.device_id)
        return bool(state.get("state", False)) if state else False
    
    async def async_turn_on(self, **kwargs) -> None:
        """Turn on switch."""
        commands = {
            DeviceType.OUTLET: {"turn_on": True} \
                if self.sub_type != DeviceSubType.STANDBY_CUTOFF else {"standby_cutoff": True},
            DeviceType.DOORLOCK: {"unlock": True},
            DeviceType.BATCHSWITCH: {"turn_on": True},
            DeviceType.ELEVATOR: {"direction": ElevatorState.CALLED},
        }
        
        if cmd := commands.get(self.device_type):
            await self.gateway.api.send_command(
                self.device_type, self.room_id, self.device_index, self.sub_type, **cmd
            )
    
    async def async_turn_off(self, **kwargs) -> None:
        """Turn off switch."""
        commands = {
            DeviceType.OUTLET: {"turn_on": False} \
                if self.sub_type != DeviceSubType.STANDBY_CUTOFF else {"standby_cutoff": False},
            DeviceType.GASVALVE: {"close": True},
            DeviceType.BATCHSWITCH: {"turn_on": False},
        }
        
        if cmd := commands.get(self.device_type):
            await self.gateway.api.send_command(
                self.device_type, self.room_id, self.device_index, self.sub_type, **cmd
            )
