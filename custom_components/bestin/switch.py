"""Switch platform for Bestin."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType, DeviceSubType, ElevatorState, IntercomType
from .entity_descriptions import SWITCH_DESCRIPTIONS
from .device import BestinDevice
from .gateway import BestinGateway
from .protocol import DeviceState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Bestin switch platform."""
    gateway: BestinGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def _add_device(ds: DeviceState):
        device_id = gateway.api.make_device_id(
            ds.device_type, ds.room_id, ds.device_index, ds.sub_type
        )
        if device_id not in gateway.entity_groups.setdefault("switchs", set()):
            gateway.entity_groups["switchs"].add(device_id)
            async_add_entities([BestinSwitch(gateway, ds)])
    
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_switchs_{gateway.host}", _add_device)
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
        
        if self.device_type == DeviceType.INTERCOM:
            if self.sub_type == DeviceSubType.HOME_ENTRANCE:
                self._attr_name = "세대현관 열기"
                self._attr_translation_key = "intercom_home_open"
            elif self.sub_type == DeviceSubType.HOME_ENTRANCE_SCHEDULE:
                self._attr_name = "세대현관 열림 예약"
                self._attr_translation_key = "intercom_home_schedule"
            elif self.sub_type == DeviceSubType.COMMON_ENTRANCE:
                self._attr_name = "공동현관 열기"
                self._attr_translation_key = "intercom_common_open"
            elif self.sub_type == DeviceSubType.COMMON_ENTRANCE_SCHEDULE:
                self._attr_name = "공동현관 열림 예약"
                self._attr_translation_key = "intercom_common_schedule"
    
    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        state = self.gateway.api.get_device_state(self.device_id)
        return bool(state.get("state", False)) if state else False
    
    async def async_turn_on(self, **kwargs) -> None:
        """Turn on switch."""
        if self.device_type == DeviceType.INTERCOM:
            if self.sub_type in [DeviceSubType.HOME_ENTRANCE_SCHEDULE, DeviceSubType.COMMON_ENTRANCE_SCHEDULE]:
                await self.gateway.api.send_command(
                    self.device_type, self.room_id, self.device_index, self.sub_type, enable_schedule=True
                )
            else:
                await self.gateway.api.send_command(
                    self.device_type, self.room_id, self.device_index, self.sub_type, open_door=True
                )
            return
        
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
        if self.device_type == DeviceType.INTERCOM:
            if self.sub_type in [DeviceSubType.HOME_ENTRANCE_SCHEDULE, DeviceSubType.COMMON_ENTRANCE_SCHEDULE]:
                await self.gateway.api.send_command(
                    self.device_type, self.room_id, self.device_index, self.sub_type, disable_schedule=True
                )
            return
        
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
