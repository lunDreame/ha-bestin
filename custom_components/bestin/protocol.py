"""Bestin wallpad protocol handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate.const import HVACMode

from .const import (
    LOGGER,
    DeviceType,
    DeviceSubType,
    PacketHeader,
    PacketType,
    FanMode,
    ElevatorState,
    EnergyType,
)


def calculate_checksum(packet: bytearray | bytes) -> int:
    """Calculate Bestin protocol checksum."""
    checksum = 3
    for byte in packet:
        checksum ^= byte
        checksum = (checksum + 1) & 0xFF
    return checksum


def verify_checksum(packet: bytes) -> bool:
    """Verify packet checksum."""
    return len(packet) >= 4 and calculate_checksum(packet[:-1]) == packet[-1]


def make_packet(header: int, length: int, pkt_type: int, spin: int = 0) -> bytearray:
    """Create basic packet structure."""
    packet = bytearray([0x02, header & 0xFF, length & 0xFF, pkt_type & 0xFF, spin & 0xFF])
    packet.extend(bytearray(length - 5))
    return packet


def finalize_packet(packet: bytearray) -> bytearray:
    """Add checksum and return packet."""
    packet[-1] = calculate_checksum(packet[:-1])
    return packet


@dataclass
class DeviceState:
    """Device state from parsed packet."""
    device_type: DeviceType
    room_id: int
    device_index: int
    state: Any
    sub_type: DeviceSubType = DeviceSubType.NONE
    attributes: dict[str, Any] | None = None


class BestinProtocol:
    """Bestin wallpad protocol handler."""
    
    def __init__(self, wallpad_config: dict | None = None):
        """Initialize protocol handler."""
        self.config = wallpad_config or {}
        self.spin_code = 0
    
    def _get(self, key: str, default: Any = None) -> Any:
        """Get wallpad config value."""
        return self.config.get(key, default)
    
    def build_thermostat_packet(
        self, room: int, *, mode: int | None = None, temperature: float | None = None, query: bool = False
    ) -> bytearray:
        """Build thermostat packet."""
        if query:
            packet = make_packet(PacketHeader.THERMOSTAT, 0x07, PacketType.QUERY, self.spin_code)
            packet[5] = room & 0x0F
        else:
            packet = make_packet(PacketHeader.THERMOSTAT, 0x0E, PacketType.CONTROL_ACK, self.spin_code)
            packet[5] = room & 0x0F
            if mode is not None:
                packet[6] = 0x01 if mode else 0x02
            if temperature is not None:
                packet[7] = int(temperature) & 0xFF
                if temperature % 1:
                    packet[7] |= 0x40
        return finalize_packet(packet)
    
    def build_light_packet(
        self, room: int, index: int, *, turn_on: bool | None = None, query: bool = False
    ) -> bytearray:
        """Build light packet."""
        is_aio = self._get("aio_generation", False)
        
        if query:
            packet = make_packet(0x31, 0x07, PacketType.QUERY, self.spin_code)
            if is_aio:
                packet[1] = 0x50 + room
                packet[2] = 0x06
            else:
                packet[5] = room & 0x0F
        else:
            packet = make_packet(0x31, 0x0D, PacketType.CONTROL, self.spin_code)
            if is_aio:
                packet[1] = 0x50 + room
                packet[2:4] = [0x0A, PacketType.CONTROL_ACK]
                packet[5] = 0x01 if turn_on else 0x00
                packet[6] = 0x0A if index == 4 else (1 << index)
            else:
                packet[5] = room & 0x0F
                packet[6] = (1 << index) | (0x80 if turn_on else 0x00)
                if turn_on:
                    packet[11] = 0x04
        return finalize_packet(packet)
    
    def build_dimming_packet(
        self, room: int, index: int, *, turn_on: bool | None = None, brightness: int | None = None, query: bool = False
    ) -> bytearray:
        """Build dimming light packet."""
        if query:
            if self._get("dimming_version") == 2:
                packet = make_packet(0x30 + room, 0x10, PacketType.QUERY, self.spin_code)
                packet[5:10] = [0x02, 0x81, 0x00, 0x00, 0x02]
            else:
                packet = make_packet(0x30 + room, 0x06, PacketType.QUERY, self.spin_code)
            return finalize_packet(packet)
        
        packet = make_packet(0x30 + room, 0x0E, PacketType.STATE, self.spin_code)
        packet[5] = 0x01
        packet[7] = 0x01 + index
        packet[8] = (0x01 if turn_on else 0x02) if turn_on is not None else 0xFF
        packet[9] = (brightness & 0xFF) if brightness is not None else 0xFF
        packet[10:13] = [0xFF, 0x00, 0xFF]
        return finalize_packet(packet)
    
    def build_outlet_packet(
        self, room: int, index: int, *, turn_on: bool | None = None, standby_cutoff: bool | None = None, query: bool = False
    ) -> bytearray:
        """Build outlet packet."""
        dimming_ver = self._get("dimming_version", 1)
        is_aio = self._get("aio_generation", False)
        
        if query:
            packet = make_packet(0x31, 0x07, PacketType.QUERY, self.spin_code)
            if dimming_ver == 1:
                packet[1:3] = [0x30 + room, 0x06]
            elif is_aio:
                packet[1:3] = [0x50 + room, 0x06]
            else:
                packet[5] = room & 0x0F
        else:
            packet = make_packet(0x31, 0x0D, PacketType.CONTROL, self.spin_code)
            cmd = 0x01 if turn_on else 0x02
            
            if dimming_ver == 1:
                packet[1:4] = [0x30 + room, 0x09, 0x22]
                packet[5:8] = [0x01, (index + 1) & 0x0F, cmd]
            elif is_aio:
                packet[1:4] = [0x50 + room, 0x0C, PacketType.CONTROL_ACK]
                packet[8:11] = [0x01, (index + 1) & 0x0F, cmd if standby_cutoff is None else cmd << 4]
            else:
                packet[5] = room & 0x0F
                if turn_on:
                    packet[7] = (1 << index) | 0x80
                    packet[11] = 0x09 << index
        
        return finalize_packet(packet)
    
    def build_ventilator_packet(self, *, fan_mode: FanMode | None = None, query: bool = False) -> bytearray:
        """Build ventilator packet."""
        vent_variable = self._get("vent_len_variable", False)
        
        if query:
            return finalize_packet(
                make_packet(0x61, 0x06, PacketType.QUERY, self.spin_code) if vent_variable
                else bytearray([0x02, 0x61, 0x00, self.spin_code] + [0x00] * 6)
            )
        
        if vent_variable:
            packet = make_packet(0x61, 0x09, PacketType.STATE, self.spin_code)
            packet[5] = 0x01 if fan_mode == FanMode.OFF else 0x40
            packet[7] = {FanMode.OFF: 0x01, FanMode.LOW: 0x01, FanMode.MEDIUM: 0x02, FanMode.HIGH: 0x03}.get(fan_mode, 0x01)
        else:
            packet = bytearray([0x02, 0x61, 0x01 if fan_mode != FanMode.OFF else 0x01, self.spin_code] + [0x00] * 6)
            packet[5] = 0x00 if fan_mode == FanMode.OFF else 0x01
            packet[6] = 0x01
        
        return finalize_packet(packet)
    
    def build_gasvalve_packet(self, *, close: bool = False) -> bytearray | None:
        """Build gas valve packet (close only)."""
        return finalize_packet(bytearray([0x02, 0x31, 0x02, self.spin_code] + [0x00] * 6)) if close else None
    
    def build_doorlock_packet(self, *, unlock: bool = False) -> bytearray | None:
        """Build doorlock packet (unlock only)."""
        return finalize_packet(bytearray([0x02, 0x41, 0x02, self.spin_code, 0x01] + [0x00] * 5)) if unlock else None
    
    def build_batchswitch_packet(self, *, turn_on: bool = False) -> bytearray:
        """Build batch switch packet."""
        batch_type = self._get("batch_switch_type")
        
        if batch_type in [1, 2]:
            packet = bytearray([0x02, 0x15 if batch_type == 1 else 0x17, 0x04, 0x01, self.spin_code, 0x00, 0x00, 0x01 if turn_on else 0x00, 0x00, 0x00])
        else:
            packet = make_packet(0xC1, 0x0C, PacketType.STATE_QUERY_ACK, self.spin_code)
            packet[6:11] = [0x01, 0x00, 0x01 if turn_on else 0x02, 0x01, 0x02]
        
        return finalize_packet(packet)
    
    def build_elevator_packet(self, *, direction: ElevatorState | None = None) -> bytearray:
        """Build elevator call packet."""
        packet = make_packet(0xC1, 0x0C, PacketType.STATE_QUERY_ACK, self.spin_code)
        packet[5] = {ElevatorState.MOVING_DOWN: 0x10, ElevatorState.MOVING_UP: 0x20}.get(direction, 0x00)
        packet[6:11] = [0x01, 0x00, 0x02, 0x01, 0x02]
        return finalize_packet(packet)
    
    def parse_packet(self, packet: bytes) -> list[DeviceState]:
        """Parse packet and return device states."""
        if len(packet) < 4:
            return []
        
        header = packet[1]
        self.spin_code = packet[4] if len(packet) != 10 else packet[3]
        
        parser_map = {
            PacketHeader.THERMOSTAT: self._parse_thermostat,
            PacketHeader.VENTILATOR: self._parse_ventilator,
            PacketHeader.ENERGY: self._parse_energy,
            PacketHeader.DOORLOCK: self._parse_doorlock,
        }
        
        if header in parser_map:
            return parser_map[header](packet)
        
        if header == PacketHeader.DIMMING_LIGHT or header in range(0x30, 0x40):
            dimming_ver = self._get("dimming_version")
            if dimming_ver == 2 or header == PacketHeader.DIMMING_LIGHT:
                return self._parse_dimming_gen2(packet)
            elif dimming_ver == 1:
                return self._parse_dimming_gen1(packet)
            return self._parse_light_outlet(packet)
        
        if header in range(0x50, 0x56):
            return self._parse_aio_light_outlet(packet)
        
        if header in [PacketHeader.BATCH_SWITCH_1, PacketHeader.BATCH_SWITCH_2, PacketHeader.SMART_SWITCH, PacketHeader.SMART_SWITCH_C]:
            return self._parse_batch_elevator(packet)
        
        if header == PacketHeader.LIGHT_OUTLET_GAS:
            if len(packet) == 10:
                return self._parse_gasvalve(packet)
            elif len(packet) in [6, 13] and packet[3] in [PacketType.STATE_A1, PacketType.STATE_CONTROL_ACK]:
                return self._parse_cooktop(packet)
        
        return []
    
    def _parse_thermostat(self, packet: bytes) -> list[DeviceState]:
        """Parse thermostat packet."""
        if packet[3] not in [PacketType.STATE_QUERY_ACK, PacketType.STATE_CONTROL_ACK]:
            return []
        
        room_id = packet[5] & 0x0F
        is_on = packet[6] & 0x01
        target_temp = (packet[7] & 0x3F) + (0.5 if packet[7] & 0x40 else 0)
        current_temp = int.from_bytes(packet[8:10], "big") / 10.0
        
        return [DeviceState(
            device_type=DeviceType.THERMOSTAT,
            room_id=room_id,
            device_index=0,
            state={
                "hvac_mode": HVACMode.HEAT if is_on else HVACMode.OFF,
                "target_temperature": target_temp,
                "current_temperature": current_temp,
            },
        )]
    
    def _create_device_state(self, device_type: DeviceType, room_id: int, index: int, state: Any, sub_type: DeviceSubType = DeviceSubType.NONE, **attrs) -> DeviceState:
        """Helper to create DeviceState."""
        return DeviceState(
            device_type=device_type,
            room_id=room_id,
            device_index=index,
            state=state,
            sub_type=sub_type,
            attributes=attrs if attrs else None,
        )
    
    def _parse_light_outlet(self, packet: bytes) -> list[DeviceState]:
        """Parse standard light/outlet packet."""
        if packet[3] not in [PacketType.STATE_QUERY_ACK, PacketType.STATE_CONTROL_ACK, 0x81] or len(packet) < 14:
            return []
        
        room_id = packet[5] & 0x0F
        light_cnt, outlet_cnt = (4, 3) if room_id == 1 else (2, 2)
        devices = []
        
        light_power = int.from_bytes(packet[12:14], "big") / 10.0
        for i in range(light_cnt):
            devices.append(self._create_device_state(DeviceType.LIGHT, room_id, i, bool(packet[6] & (1 << i))))
            if light_power > 0:
                devices.append(self._create_device_state(DeviceType.LIGHT, room_id, i, light_power, DeviceSubType.POWER_USAGE))
        
        standby_cutoff = bool(packet[7] >> 4 & 1)
        for i in range(outlet_cnt):
            devices.append(self._create_device_state(DeviceType.OUTLET, room_id, i, bool(packet[7] & (1 << i))))
            devices.append(self._create_device_state(DeviceType.OUTLET, room_id, i, standby_cutoff, DeviceSubType.STANDBY_CUTOFF))
            
            if i < 2:
                cutoff_value = int.from_bytes(packet[8 + 2*i:10 + 2*i], "big") / 10.0
                devices.append(self._create_device_state(DeviceType.OUTLET, room_id, i, cutoff_value, DeviceSubType.CUTOFF_VALUE))
            
            power_idx = 14 + 2 * i
            if len(packet) > power_idx + 1:
                power_usage = int.from_bytes(packet[power_idx:power_idx + 2], "big") / 10.0
                devices.append(self._create_device_state(DeviceType.OUTLET, room_id, i, power_usage, DeviceSubType.POWER_USAGE))
        
        return devices
    
    def _parse_aio_light_outlet(self, packet: bytes) -> list[DeviceState]:
        """Parse AIO generation light/outlet packet."""
        if packet[3] not in [PacketType.STATE_QUERY_ACK, PacketType.STATE_CONTROL_ACK]:
            return []
        
        room_id = packet[1] & 0x0F
        devices = []
        
        for i in range(min(packet[5], 8)):
            devices.append(self._create_device_state(DeviceType.LIGHT, room_id, i, bool(packet[6] & (1 << i))))
        
        for i in range(2):
            idx = 9 + 5 * i
            if idx + 2 >= len(packet):
                break
            
            is_on = (packet[idx] & 0x0F) == 0x01
            standby_cutoff = packet[idx] in [0x11, 0x13, 0x12]
            power_usage = int.from_bytes(packet[idx + 1:idx + 3], "big") / 10.0
            
            devices.extend([
                self._create_device_state(DeviceType.OUTLET, room_id, i, is_on),
                self._create_device_state(DeviceType.OUTLET, room_id, i, standby_cutoff, DeviceSubType.STANDBY_CUTOFF),
                self._create_device_state(DeviceType.OUTLET, room_id, i, power_usage, DeviceSubType.POWER_USAGE),
            ])
        
        return devices
    
    def _parse_ventilator(self, packet: bytes) -> list[DeviceState]:
        """Parse ventilator packet."""
        if len(packet) < 7:
            return []
        
        if packet[2] in [0x80, 0x81, 0x83, 0x84, 0x87]:
            is_on, speed = packet[5] & 0x01, packet[6] if packet[5] & 0x01 else 0
        else:
            is_on, speed = packet[6] if len(packet) > 6 else 0, packet[8] if len(packet) > 8 and packet[6] else 0
        
        fan_mode = {0: FanMode.OFF, 1: FanMode.LOW, 2: FanMode.MEDIUM, 3: FanMode.HIGH}.get(speed, FanMode.OFF)
        
        return [self._create_device_state(
            DeviceType.VENTILATION, 0, 0,
            {"is_on": bool(is_on), "fan_mode": fan_mode, "speed": speed}
        )]
    
    def _parse_batch_elevator(self, packet: bytes) -> list[DeviceState]:
        """Parse batch switch and elevator packet."""
        pkt_len, pkt_type = packet[2], packet[3]
        devices = []
        
        if pkt_len == 0x0C and pkt_type == PacketType.STATE_QUERY_ACK:
            elev_byte = packet[5]
            direction = {0x10: ElevatorState.MOVING_DOWN, 0x20: ElevatorState.MOVING_UP}.get(elev_byte, ElevatorState.IDLE)
            
            devices.extend([
                self._create_device_state(DeviceType.ELEVATOR, 0, 0, direction, DeviceSubType.DIRECTION),
                self._create_device_state(DeviceType.BATCHSWITCH, 0, 0, packet[8] != 0x02),
            ])
        
        elif pkt_len == 0x13 and pkt_type == 0x13:
            if packet[11] == 0x04:
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, ElevatorState.ARRIVED, DeviceSubType.DIRECTION))
            
            if len(packet) > 12 and packet[12] != 0xFF:
                floor = f"B{packet[12] & 0x7F}" if packet[12] & 0x80 else str(packet[12])
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, floor, DeviceSubType.FLOOR))
        
        elif pkt_len in [0x80, 0x81, 0x84, 0x87] and len(packet) > 7:
            if packet[7] == 0x40:
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, ElevatorState.MOVING_DOWN, DeviceSubType.DIRECTION))
            else:
                devices.append(self._create_device_state(DeviceType.BATCHSWITCH, 0, 0, packet[7] == 0x01))
        
        return devices
    
    def _parse_dimming_gen1(self, packet: bytes) -> list[DeviceState]:
        """Parse Gen1 dimming light packet."""
        if packet[3] not in [PacketType.STATE_QUERY_ACK, PacketType.STATE_A1, PacketType.STATE_A2] or len(packet) < 18:
            return []
        
        room_id = packet[1] & 0x0F
        light_count, outlet_count = packet[10] & 0x0F, packet[11] & 0x0F
        base_count = light_count + 1 if packet[10] >> 4 == 0x04 else light_count
        
        light_idx, outlet_idx = 17, 17 + base_count * 13
        devices = []
        
        for _ in range(light_count):
            if light_idx + 12 >= len(packet) or packet[light_idx] >> 4 == 0x08:
                light_idx += 13
                continue
            
            light_num = (packet[light_idx] & 0x0F) - 1
            is_on, brightness = bool(packet[light_idx + 1] & 0x01), packet[light_idx + 2]
            power = int.from_bytes(packet[light_idx + 8:light_idx + 10], "big") / 10.0
            
            state = {"is_on": is_on, "brightness": brightness} if brightness > 0 else {"is_on": is_on}
            devices.append(self._create_device_state(DeviceType.DIMMINGLIGHT 
                                                     if brightness > 0 else DeviceType.LIGHT, room_id, light_num, state))
            
            if power > 0:
                devices.append(self._create_device_state(DeviceType.DIMMINGLIGHT 
                                                         if brightness > 0 else DeviceType.LIGHT, room_id, light_num, power, DeviceSubType.POWER_USAGE))
            
            light_idx += 13
        
        for _ in range(outlet_count):
            if outlet_idx + 13 >= len(packet) or packet[outlet_idx] >> 4 == 0x08:
                outlet_idx += 14
                continue
            
            outlet_num = (packet[outlet_idx] & 0x0F) - 1
            is_on, standby = bool(packet[outlet_idx + 1] & 0x01), bool(packet[outlet_idx] & 0x10)
            cutoff = int.from_bytes(packet[outlet_idx + 6:outlet_idx + 8], "big") / 10.0
            power = int.from_bytes(packet[outlet_idx + 8:outlet_idx + 10], "big") / 10.0
            
            devices.extend([
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, is_on),
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, standby, DeviceSubType.STANDBY_CUTOFF),
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, cutoff, DeviceSubType.CUTOFF_VALUE),
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, power, DeviceSubType.POWER_USAGE),
            ])
            
            outlet_idx += 14
        
        return devices
    
    def _parse_dimming_gen2(self, packet: bytes) -> list[DeviceState]:
        """Parse Gen2 dimming light packet."""
        if packet[3] not in [PacketType.STATE_QUERY_ACK, PacketType.STATE_A1, PacketType.STATE_A2] or len(packet) < 11:
            return []
        
        room_id = 15 if packet[1] == 0x21 else packet[1] & 0x0F
        light_count = packet[10] & 0x0F
        
        light_increment = 4 if packet[1] == 0x21 and packet[2] == 0x12 else 3
        outlet_count = 0 if light_increment == 4 else packet[10 + light_count * 3 + 2] \
            if len(packet) > 10 + light_count * 3 + 2 else 0
        
        light_idx, outlet_idx = 11, 11 + light_count * light_increment + 2
        devices = []
        
        for i in range(light_count):
            if light_idx + 2 >= len(packet):
                break
            
            is_on, brightness = packet[light_idx] == 0x01, packet[light_idx + 1]
            state = {"is_on": is_on, "brightness": brightness} if brightness > 0 else {"is_on": is_on}
            devices.append(self._create_device_state(DeviceType.DIMMINGLIGHT 
                                                     if brightness > 0 else DeviceType.LIGHT, room_id, i, state))
            light_idx += light_increment
        
        for i in range(outlet_count):
            if outlet_idx + 12 >= len(packet):
                break
            
            is_on, standby = (packet[outlet_idx] & 0x0F) == 0x01, bool(packet[outlet_idx] & 0x10)
            cutoff = int.from_bytes(packet[outlet_idx + 6:outlet_idx + 8], "big") / 10.0
            power = int.from_bytes(packet[outlet_idx + 8:outlet_idx + 10], "big") / 10.0
            
            devices.extend([
                self._create_device_state(DeviceType.OUTLET, room_id, i, is_on),
                self._create_device_state(DeviceType.OUTLET, room_id, i, standby, DeviceSubType.STANDBY_CUTOFF),
                self._create_device_state(DeviceType.OUTLET, room_id, i, cutoff, DeviceSubType.CUTOFF_VALUE),
                self._create_device_state(DeviceType.OUTLET, room_id, i, power, DeviceSubType.POWER_USAGE),
            ])
            
            outlet_idx += 13
        
        return devices
    
    def _parse_gasvalve(self, packet: bytes) -> list[DeviceState]:
        """Parse gas valve packet."""
        return [self._create_device_state(DeviceType.GASVALVE, 0, 0, packet[5] == 0x01)] \
            if len(packet) >= 6 and packet[2] in [0x80, 0x82] else []
    
    def _parse_cooktop(self, packet: bytes) -> list[DeviceState]:
        """Parse cooktop packet."""
        return [self._create_device_state(DeviceType.GASVALVE, 0, 0, packet[7] == 0x03)] \
            if len(packet) >= 8 else []
    
    def _parse_doorlock(self, packet: bytes) -> list[DeviceState]:
        """Parse doorlock packet."""
        return [self._create_device_state(DeviceType.DOORLOCK, 0, 0, not bool(packet[5] & 0xAE))] \
            if len(packet) >= 6 else []
    
    def _parse_energy(self, packet: bytes) -> list[DeviceState]:
        """Parse HEMS energy packet."""
        if len(packet) < 8:
            return []
        
        try:
            hems_idx = next((i + 1 for i in range(5, min(10, len(packet))) if packet[i] == 0x80), None)
            if not hems_idx or hems_idx >= len(packet):
                return []
            
            hems_count, current_idx, devices = packet[hems_idx], hems_idx + 1, []
            energy_names = {1: "electric", 2: "water", 3: "hotwater", 4: "gas", 5: "heat"}
            
            for _ in range(min(hems_count, 5)):
                if current_idx >= len(packet):
                    break
                
                energy_id = packet[current_idx]
                is_used = (energy_id & 0x80) == 0
                
                if not is_used:
                    current_idx += 2
                    continue
                
                if current_idx + 7 >= len(packet):
                    break
                
                data = packet[current_idx + 1:current_idx + 8]
                total, realtime = int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:6], "big")
                energy_name = energy_names.get(energy_id & 0x7F, f"unknown_{energy_id & 0x7F}")
                
                devices.append(self._create_device_state(
                    DeviceType.ENERGY, 0, energy_id & 0x7F,
                    {"total": total, "realtime": realtime},
                    attributes={"energy_type": energy_name}
                ))
                
                current_idx += 8
            
        except Exception as ex:
            LOGGER.error("Error parsing energy packet: %s", ex, exc_info=True)
        
        return devices
