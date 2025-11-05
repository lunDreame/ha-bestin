"""Controller for Bestin wallpad integration."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable
from collections import defaultdict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import dispatcher
from homeassistant.components.climate.const import HVACMode

from .const import (
    LOGGER,
    DOMAIN,
    NEW_BINARY_SENSOR,
    NEW_CLIMATE,
    NEW_FAN,
    NEW_LIGHT,
    NEW_SENSOR,
    NEW_SWITCH,
    DeviceType,
    DeviceSubType,
    FanMode,
    IntercomType,
)
from .protocol import BestinProtocol, DeviceState, verify_checksum, verify_intercom_checksum


class BestinController:
    """Controller for Bestin wallpad integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_groups: dict[str, set[str]],
        host: str,
        connection,
        add_device_callback: Callable,
    ) -> None:
        """Initialize the BestinController."""
        self.hass = hass
        self.entry = entry
        self.entity_groups = entity_groups
        self.host = host
        self.connection = connection
        self.add_device_callback = add_device_callback
        
        self.wallpad_config = {
            "dimming_generation": False,
            "aio_generation": False,
            "batch_switch_header": 0xC1,
            "room_ventilation": False,
        }
        
        self.protocol = BestinProtocol(self.wallpad_config)
        self.devices: dict[str, dict[str, Any]] = {}
        self._callbacks: dict[str, list[Callable]] = defaultdict(list)
        self._buffer = bytearray()
        self._tasks: list[asyncio.Task] = []
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._pending_commands: dict[str, dict[str, Any]] = {}
        
        self._last_rx_time: float = 0
        self._last_tx_time: float = 0
        self._last_spin_code: int = 0
        self._command_timeout: float = 2.0
        self._max_retries: int = 3
        
        self._intercom_auto_open: dict[int, bool] = {}
        self._intercom_opening: dict[int, bool] = {}

    async def start(self):
        """Start the controller tasks."""
        self._tasks = [
            self.hass.loop.create_task(self._process_incoming_data()),
            self.hass.loop.create_task(self._process_command_queue()),
            self.hass.loop.create_task(self._cleanup_pending_commands()),
        ]
        LOGGER.info("Controller started")

    async def stop(self):
        """Stop the controller tasks."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        LOGGER.info("Controller stopped")

    @property
    def is_alive(self) -> bool:
        """Check if the connection is alive."""
        return self.connection and self.connection.is_connected()
    
    def make_device_id(
        self, 
        device_type: DeviceType, room_id: int, device_index: int, sub_type: DeviceSubType = DeviceSubType.NONE
    ) -> str:
        """Make device ID string."""
        parts = [device_type.name.lower(), str(room_id), str(device_index)]
        if sub_type != DeviceSubType.NONE:
            parts.append(sub_type.name.lower())
        return "_".join(parts)
    
    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        """Get device state by ID."""
        return self.devices.get(device_id)
    
    def update_device_state(self, device_id: str, state: dict[str, Any]) -> None:
        """Update device state and trigger callbacks only if changed."""
        if device_id not in self.devices:
            self.devices[device_id] = {}
        
        current_state = self.devices[device_id].copy()
        self.devices[device_id].update(state)
        
        if device_id in self._pending_commands:
            self._verify_command_success(device_id, state)
        
        if current_state != self.devices[device_id]:
            for callback in self._callbacks.get(device_id, []):
                try:
                    callback()
                except Exception as ex:
                    LOGGER.error("Callback error for %s: %s", device_id, ex)
    
    def register_callback(self, device_id: str, callback: Callable) -> None:
        """Register a callback for device updates."""
        self._callbacks[device_id].append(callback)
    
    def remove_callback(self, device_id: str, callback: Callable) -> None:
        """Remove a callback for device updates."""
        if device_id in self._callbacks:
            self._callbacks[device_id].remove(callback)
    
    async def send_command(
        self, 
        device_type: DeviceType, room_id: int, device_index: int, sub_type: DeviceSubType = DeviceSubType.NONE, **kwargs
    ) -> None:
        """Queue command for sending."""
        await self._command_queue.put({
            "device_type": device_type,
            "room_id": room_id,
            "device_index": device_index,
            "sub_type": sub_type,
            "kwargs": kwargs,
            "timestamp": time.time(),
            "retry_count": 0,
        })
    
    async def _process_command_queue(self):
        """Process command queue with timing control."""
        while True:
            try:
                command = await self._command_queue.get()
                await self._wait_for_idle_line()
                
                packet = self._build_packet(command)
                if packet:
                    device_id = self.make_device_id(
                        command["device_type"], command["room_id"], command["device_index"], command["sub_type"]
                    )
                    
                    self._pending_commands[device_id] = {
                        "expected_state": self._build_expected_state(command),
                        "timestamp": time.time(),
                        "command": command,
                        "packet": packet.hex(" "),
                        "retry_count": command["retry_count"],
                    }
                    
                    await self._send_packet(packet)
                
                self._command_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as ex:
                LOGGER.error("Command queue error: %s", ex, exc_info=True)
                await asyncio.sleep(0.1)
    
    def _build_expected_state(self, command: dict) -> dict[str, Any]:
        """Build expected device state from command."""
        device_type, kwargs = command["device_type"], command["kwargs"]
        
        state_builders = {
            DeviceType.THERMOSTAT: lambda: {
                k: (HVACMode.HEAT if v else HVACMode.OFF) if k == "mode" else v
                for k, v in kwargs.items() if k in ["mode", "temperature"]
            } | ({"hvac_mode": HVACMode.HEAT if kwargs.get("mode") else HVACMode.OFF} if "mode" in kwargs else {}),
            
            DeviceType.LIGHT: lambda: {"state": kwargs.get("turn_on", True)} 
            if "turn_on" in kwargs else {},
            DeviceType.DIMMINGLIGHT: lambda: {"state": {"is_on": kwargs.get("turn_on", True)}} 
            if "turn_on" in kwargs or "brightness" in kwargs else {},
            DeviceType.OUTLET: lambda: {"state": kwargs.get("turn_on") or kwargs.get("standby_cutoff")} 
            if "turn_on" in kwargs or "standby_cutoff" in kwargs else {},
            DeviceType.VENTILATION: lambda: {"is_on": kwargs["fan_mode"] != FanMode.OFF, "fan_mode": kwargs["fan_mode"]} 
            if "fan_mode" in kwargs else {},
            DeviceType.GASVALVE: lambda: {"state": not kwargs.get("close", False)} 
            if "close" in kwargs else {},
            DeviceType.DOORLOCK: lambda: {"state": not kwargs.get("unlock", False)} 
            if "unlock" in kwargs else {},
            DeviceType.ELEVATOR: lambda: {"state": kwargs.get("direction")} 
            if "direction" in kwargs else {},
            DeviceType.BATCHSWITCH: lambda: {"state": kwargs.get("turn_on", False)} 
            if "turn_on" in kwargs else {},
            DeviceType.INTERCOM: lambda: self._build_intercom_expected_state(kwargs),
        }
        
        builder = state_builders.get(device_type)
        return builder() if builder else {}
    
    def _build_intercom_expected_state(self, kwargs: dict) -> dict[str, Any]:
        """Build expected state for intercom commands."""
        if kwargs.get("disable_schedule"):
            return {"state": False}
        elif kwargs.get("enable_schedule"):
            return {"state": True}
        elif kwargs.get("open_door"):
            return {"state": True}
        return {}
    
    def _build_packet(self, command: dict) -> bytearray | None:
        """Build command packet."""
        self.protocol.spin_code = self._last_spin_code
        device_type, room, index, kwargs = \
            command["device_type"], command["room_id"], command["device_index"], command["kwargs"]
        
        packet_builders = {
            DeviceType.THERMOSTAT: lambda: self.protocol.build_thermostat_packet(room, **kwargs),
            DeviceType.LIGHT: lambda: self.protocol.build_light_packet(room, index, **kwargs),
            DeviceType.DIMMINGLIGHT: lambda: self.protocol.build_dimming_packet(room, index, **kwargs),
            DeviceType.OUTLET: lambda: self.protocol.build_outlet_packet(room, index, **kwargs),
            DeviceType.VENTILATION: lambda: self.protocol.build_ventilator_packet(**kwargs),
            DeviceType.GASVALVE: lambda: self.protocol.build_gasvalve_packet(**kwargs),
            DeviceType.DOORLOCK: lambda: self.protocol.build_doorlock_packet(**kwargs),
            DeviceType.ELEVATOR: lambda: self.protocol.build_elevator_packet(**kwargs),
            DeviceType.BATCHSWITCH: lambda: self.protocol.build_batchswitch_packet(**kwargs),
            DeviceType.INTERCOM: lambda: self._build_intercom_packet(index, **kwargs),
        }
        
        try:
            builder = packet_builders.get(device_type)
            return builder() if builder else None
        except Exception as ex:
            LOGGER.error("Packet build error for %s: %s", device_type, ex, exc_info=True)
            return None
    
    def _build_intercom_packet(self, entrance_type: int, **kwargs) -> bytearray | None:
        """Build intercom control packet and manage state."""
        intercom_type = IntercomType(entrance_type)
        
        if kwargs.get("enable_schedule"):
            self._intercom_auto_open[entrance_type] = True
            return None
        elif kwargs.get("disable_schedule"):
            self._intercom_auto_open[entrance_type] = False
            return None
        
        elif kwargs.get("open_door"):
            if intercom_type == IntercomType.HOME and not self._intercom_opening.get(entrance_type):
                self._intercom_opening[entrance_type] = True
                self.hass.loop.call_later(
                    3.0,
                    lambda: asyncio.create_task(self._send_intercom_door_open(entrance_type))
                )
                return self.protocol.build_intercom_packet(intercom_type, force_view=True)
            else:
                self._intercom_opening[entrance_type] = True
                return self.protocol.build_intercom_packet(intercom_type, open_door=True)
        
        return None
    
    async def _send_intercom_door_open(self, entrance_type: int):
        """Send door open packet after force view."""
        try:
            intercom_type = IntercomType(entrance_type)
            packet = self.protocol.build_intercom_packet(intercom_type, open_door=True)
            if packet:
                await self._send_packet(packet)
                
                self.hass.loop.call_later(
                    2.0,
                    lambda: self._turn_off_intercom_switch(entrance_type)
                )
        except Exception as ex:
            LOGGER.error("Failed to send intercom door open: %s", ex)
            self._intercom_opening[entrance_type] = False
    
    def _turn_off_intercom_switch(self, entrance_type: int):
        """Turn off intercom manual open switch after door opens."""
        try:
            self._intercom_opening[entrance_type] = False
            
            sub_type = DeviceSubType.HOME_ENTRANCE if entrance_type == IntercomType.HOME else DeviceSubType.COMMON_ENTRANCE
            device_id = self.make_device_id(DeviceType.INTERCOM, 0, entrance_type, sub_type)
            
            self.update_device_state(device_id, {"state": False})
        except Exception as ex:
            LOGGER.error("Failed to turn off intercom switch: %s", ex)
    
    def _verify_command_success(self, device_id: str, received_state: dict[str, Any]) -> None:
        """Verify if command was successful by comparing states."""
        if device_id not in self._pending_commands:
            return
        
        pending = self._pending_commands[device_id]
        expected = pending["expected_state"]
        
        if not expected or self._states_match(expected, received_state):
            elapsed = time.time() - pending["timestamp"]
            retry_info = f" (retry {pending['retry_count']})" if pending['retry_count'] > 0 else ""
            LOGGER.info("Command success for %s (%.2fs)%s: %s", device_id, elapsed, retry_info, pending["packet"])
            del self._pending_commands[device_id]
    
    def _states_match(self, expected: dict, received: dict) -> bool:
        """Compare expected and received states."""
        for key, exp_val in expected.items():
            if key not in received:
                return False
            
            rec_val = received[key]
            
            if isinstance(exp_val, dict) and isinstance(rec_val, dict):
                if not self._states_match(exp_val, rec_val):
                    return False
            elif isinstance(exp_val, float):
                if abs(exp_val - float(rec_val)) > 0.1:
                    return False
            elif exp_val != rec_val:
                return False
        
        return True
    
    async def _cleanup_pending_commands(self):
        """Clean up expired pending commands and retry."""
        while True:
            try:
                await asyncio.sleep(0.5)
                current_time = time.time()
                
                to_retry, to_remove = [], []
                
                for device_id, pending in list(self._pending_commands.items()):
                    if current_time - pending["timestamp"] > self._command_timeout:
                        if pending["retry_count"] < self._max_retries:
                            to_retry.append((device_id, pending))
                            LOGGER.warning(
                                "Retry %d/%d for %s: %s",
                                pending["retry_count"] + 1, self._max_retries, device_id, pending["packet"]
                            )
                        else:
                            to_remove.append(device_id)
                            LOGGER.error(
                                "Failed after %d retries for %s: %s", self._max_retries, device_id, pending["packet"]
                            )
                
                for device_id in to_remove:
                    del self._pending_commands[device_id]
                
                for device_id, pending in to_retry:
                    del self._pending_commands[device_id]
                    cmd = pending["command"].copy()
                    cmd["retry_count"] += 1
                    cmd["timestamp"] = time.time()
                    await self._command_queue.put(cmd)
                    
            except asyncio.CancelledError:
                break
            except Exception as ex:
                LOGGER.error("Cleanup error: %s", ex)
    
    async def _wait_for_idle_line(self):
        """Wait for line to be idle before sending."""
        min_idle, max_wait = 0.15, 2.0
        start = time.time()
        
        while time.time() - start < max_wait:
            if time.time() - self._last_rx_time >= min_idle and time.time() - self._last_tx_time >= min_idle:
                return
            await asyncio.sleep(0.05)
        
        LOGGER.warning("Idle timeout, forcing transmission")
    
    async def _send_packet(self, packet: bytearray):
        """Send packet with retry."""
        for attempt in range(2):
            try:
                if self.is_alive:
                    await self.connection.send(packet)
                    self._last_tx_time = time.time()
                    LOGGER.debug("TX%s: %s", f" (attempt {attempt + 1})" if attempt else "", packet.hex(" "))
                    return
            except Exception as ex:
                LOGGER.error("TX error (attempt %d): %s", attempt + 1, ex)
                if attempt < 1:
                    await asyncio.sleep(0.05)
    
    async def _process_incoming_data(self):
        """Process incoming data from wallpad."""
        while True:
            if not self.is_alive:
                await asyncio.sleep(5)
                continue
            
            try:
                data = await self.connection.receive()
                if data:
                    self._last_rx_time = time.time()
                    self._buffer.extend(data)
                    await self._process_buffer()
            except asyncio.CancelledError:
                break
            except Exception as ex:
                LOGGER.error("RX error: %s", ex, exc_info=True)
                await asyncio.sleep(1)
    
    async def _process_buffer(self):
        """Process packet buffer."""
        while len(self._buffer) >= 4:
            if self._buffer[0] != 0x02:
                try:
                    start_idx = self._buffer.index(0x02)
                    self._buffer = self._buffer[start_idx:]
                except ValueError:
                    self._buffer.clear()
                    break
            
            if len(self._buffer) < 3:
                break
            
            if len(self._buffer) >= 10 and self._buffer[9] == 0x03:
                packet = bytes(self._buffer[:10])
                if verify_intercom_checksum(packet):
                    self._buffer = self._buffer[10:]
                    LOGGER.debug("RX (Intercom): %s", packet.hex(" "))
                    
                    try:
                        for device_state in self.protocol.parse_packet(packet):
                            await self._handle_device_state(device_state)
                    except Exception as ex:
                        LOGGER.error("Parse error for intercom packet %s: %s", packet.hex(" "), ex, exc_info=True)
                    continue
            
            header, length = self._buffer[1], self._buffer[2]
            
            if header in [0x15, 0x17] or length in [0x00, 0x02, 0x15] or (length >> 4 == 0x08):
                length = 10
            
            if len(self._buffer) < length:
                break
            
            packet = bytes(self._buffer[:length])
            self._buffer = self._buffer[length:]
            
            if not verify_checksum(packet):
                #LOGGER.warning("Checksum error: %s", packet.hex(" "))
                continue
            
            LOGGER.debug("RX: %s", packet.hex(" "))
            
            if len(packet) > 4:
                self._last_spin_code = packet[3] if length == 10 else packet[4]
            
            #self._detect_features(packet)
            
            try:
                for device_state in self.protocol.parse_packet(packet):
                    await self._handle_device_state(device_state)
            except Exception as ex:
                LOGGER.error("Parse error for %s: %s", packet.hex(" "), ex, exc_info=True)
    
    def _detect_features(self, packet: bytes):
        """Detect wallpad features from packets."""
    
    async def _handle_device_state(self, device_state: DeviceState):
        """Handle parsed device state."""
        if device_state.device_type == DeviceType.ENERGY:
            return await self._handle_energy_state(device_state)
        
        if device_state.device_type == DeviceType.INTERCOM:
            await self._handle_intercom_event(device_state)
            return
        
        device_id = self.make_device_id(
            device_state.device_type, device_state.room_id, device_state.device_index, device_state.sub_type
        )
        
        self.update_device_state(device_id, device_state.state 
                                 if isinstance(device_state.state, dict) else {"state": device_state.state})
        
        if not self._is_device_registered(device_id):
            self._dispatch_new_device(device_state)
    
    async def _handle_intercom_event(self, device_state: DeviceState):
        """Handle intercom doorbell event."""
        entrance_type = device_state.device_index
        
        sensor_id = self.make_device_id(
            DeviceType.INTERCOM, 0, entrance_type, device_state.sub_type
        )
        
        self.update_device_state(sensor_id, {"state": True})
        
        if not self._is_device_registered(sensor_id):
            self._dispatch_new_device(device_state)
        
        self.hass.loop.call_later(2.0, lambda: self.update_device_state(sensor_id, {"state": False}))
        
        if self._intercom_auto_open.get(entrance_type, False):
            LOGGER.info("Auto-opening %s entrance (scheduled)", "home" if entrance_type == IntercomType.HOME else "common")
            manual_sub_type = DeviceSubType.HOME_ENTRANCE if entrance_type == IntercomType.HOME else DeviceSubType.COMMON_ENTRANCE
            await self.send_command(
                DeviceType.INTERCOM, 0, entrance_type, manual_sub_type, open_door=True
            )
        
        manual_sub_type = DeviceSubType.HOME_ENTRANCE if entrance_type == IntercomType.HOME else DeviceSubType.COMMON_ENTRANCE
        manual_switch_id = self.make_device_id(DeviceType.INTERCOM, 0, entrance_type, manual_sub_type)
        
        if manual_switch_id not in self.entity_groups.get("switchs", set()):
            manual_switch_state = DeviceState(
                device_type=DeviceType.INTERCOM,
                room_id=0,
                device_index=entrance_type,
                state=False,
                sub_type=manual_sub_type,
            )
            self._dispatch_new_device(manual_switch_state)
        
        schedule_sub_type = DeviceSubType.HOME_ENTRANCE_SCHEDULE if entrance_type == IntercomType.HOME else DeviceSubType.COMMON_ENTRANCE_SCHEDULE
        schedule_switch_id = self.make_device_id(DeviceType.INTERCOM, 0, entrance_type, schedule_sub_type)
        
        if schedule_switch_id not in self.entity_groups.get("switchs", set()):
            schedule_switch_state = DeviceState(
                device_type=DeviceType.INTERCOM,
                room_id=0,
                device_index=entrance_type,
                state=self._intercom_auto_open.get(entrance_type, False),
                sub_type=schedule_sub_type,
            )
            self._dispatch_new_device(schedule_switch_state)
    
    async def _handle_energy_state(self, device_state: DeviceState):
        """Handle energy device state."""
        if not device_state.attributes or "energy_type" not in device_state.attributes:
            return
        
        energy_type = device_state.attributes["energy_type"]
        state_data = device_state.state
        
        if not isinstance(state_data, dict) or "total" not in state_data or "realtime" not in state_data:
            return
        
        for sensor_type, value_key in [("power", "realtime"), ("total", "total")]:
            device_id = f"energy_{energy_type}_{sensor_type}_0_0"
            self.update_device_state(device_id, {"state": state_data[value_key]})
            
            if not self._is_device_registered(device_id):
                self.entity_groups.setdefault("sensors", set()).add(device_id)
                dispatcher.async_dispatcher_send(
                    self.hass,
                    f"{DOMAIN}_{NEW_SENSOR}_{self.host}",
                    DeviceState(
                        device_type=DeviceType.ENERGY,
                        room_id=0,
                        device_index=device_state.device_index,
                        state=state_data,
                        attributes={"energy_type": energy_type, "sensor_type": sensor_type},
                    ),
                )
    
    def _is_device_registered(self, device_id: str) -> bool:
        """Check if device is already registered."""
        return device_id in (
            self.entity_groups.get("binary_sensors", set()) |
            self.entity_groups.get("climates", set()) |
            self.entity_groups.get("fans", set()) |
            self.entity_groups.get("lights", set()) |
            self.entity_groups.get("sensors", set()) |
            self.entity_groups.get("switchs", set())
        )
    
    def _dispatch_new_device(self, device_state: DeviceState):
        """Dispatch new device discovery."""
        if device_state.device_type == DeviceType.INTERCOM:
            if device_state.attributes and device_state.attributes.get("event") == "doorbell":
                signal = NEW_BINARY_SENSOR
                entity_group = "binary_sensors"
            else:
                signal = NEW_SWITCH
                entity_group = "switchs"
            
            device_id = self.make_device_id(
                device_state.device_type, device_state.room_id, device_state.device_index, device_state.sub_type
            )
            self.entity_groups.setdefault(entity_group, set()).add(device_id)
            dispatcher.async_dispatcher_send(self.hass, f"{DOMAIN}_{signal}_{self.host}", device_state)
            return
        
        if device_state.sub_type in [
            DeviceSubType.POWER_USAGE,
            DeviceSubType.CUTOFF_VALUE,
            DeviceSubType.DIRECTION,
            DeviceSubType.FLOOR
        ]:
            signal = NEW_SENSOR
        elif device_state.device_type == DeviceType.THERMOSTAT:
            signal = NEW_CLIMATE
        elif device_state.device_type == DeviceType.VENTILATION:
            signal = NEW_FAN
        elif device_state.device_type in [DeviceType.LIGHT, DeviceType.DIMMINGLIGHT]:
            signal = NEW_LIGHT
        elif device_state.device_type in [
            DeviceType.OUTLET,
            DeviceType.GASVALVE,
            DeviceType.DOORLOCK,
            DeviceType.ELEVATOR,
            DeviceType.BATCHSWITCH
        ]:
            signal = NEW_SWITCH
        else:
            return
        
        dispatcher.async_dispatcher_send(self.hass, f"{DOMAIN}_{signal}_{self.host}", device_state)
