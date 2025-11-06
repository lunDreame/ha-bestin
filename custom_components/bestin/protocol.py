"""Bestin wallpad protocol handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate.const import HVACMode

from .const import (
    LOGGER,
    DeviceType,
    DeviceSubType,
    FanMode,
    ElevatorState,
    EnergyType,
    IntercomType,
)


def calculate_checksum(packet: bytearray | bytes) -> int:
    """Calculate Bestin protocol checksum."""
    checksum = 3
    for byte in packet:
        checksum ^= byte
        checksum = (checksum + 1) & 0xFF
    return checksum


def calculate_intercom_checksum(packet: bytearray | bytes, include_end: bool = False) -> int:
    """Calculate intercom protocol checksum (XOR only)."""
    checksum = 0
    for byte in packet:
        checksum ^= byte
    if include_end:
        checksum ^= 0x03
    return checksum


def verify_checksum(packet: bytes) -> bool:
    """Verify packet checksum."""
    return len(packet) >= 4 and calculate_checksum(packet[:-1]) == packet[-1]


def verify_intercom_checksum(packet: bytes) -> bool:
    """Verify intercom packet checksum."""
    if len(packet) != 10 or packet[0] != 0x02 or packet[-1] != 0x03:
        return False
    
    header = packet[1]
    cmd = packet[3]
    expected = packet[-2]
    
    if header == 0x00 and cmd == 0x01:
        data = packet[:-2] + packet[-1:]
        calculated = calculate_intercom_checksum(data, include_end=False)
    elif header == 0x01:
        data = packet[1:-2] + packet[-1:]
        calculated = calculate_intercom_checksum(data, include_end=False)
    else:
        data = packet[:-2]
        calculated = calculate_intercom_checksum(data, include_end=False)
    return calculated == expected


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
    
    def _set(self, key: str, value: Any) -> None:
        """Set wallpad config value."""
        self.config[key] = value
    
    def build_thermostat_packet(
        self, room: int, *, mode: int | None = None, temperature: float | None = None, query: bool = False
    ) -> bytearray:
        """Build thermostat packet."""
        if query:
            packet = make_packet(0x28, 0x07, 0x11, self.spin_code)
            packet[5] = room & 0x0F
        else:
            packet = make_packet(0x28, 0x0E, 0x12, self.spin_code)
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
        is_aio = self._get("aio_generation")
        
        if query:
            packet = make_packet(0x31, 0x07, 0x11, self.spin_code)
            if is_aio:
                packet[1] = 0x50 + room
                packet[2] = 0x06
            else:
                packet[5] = room & 0x0F
        else:
            packet = make_packet(0x31, 0x0D, 0x01, self.spin_code)
            if is_aio:
                packet[1] = 0x50 + room
                packet[2:4] = [0x0A, 0x12]
                packet[5] = 0x01 if turn_on else 0x00
                packet[6] = 0x0A if index == 4 else (1 << index)
            else:
                packet[5] = room & 0x0F
                packet[6] = (1 << index) | (0x80 if turn_on else 0x00)
                packet[11] = 0x04 if turn_on else 0x00
        return finalize_packet(packet)
    
    def build_dimming_packet(
        self, room: int, index: int, *, turn_on: bool | None = None, brightness: int | None = None, query: bool = False
    ) -> bytearray:
        """Build dimming light packet."""
        if query:
            packet = make_packet(0x30 + room, 0x06, 0x11, self.spin_code)
            return finalize_packet(packet)
        
        packet = make_packet(0x30 + room, 0x0E, 0x21, self.spin_code)
        packet[5] = 0x01
        packet[6] = 0x00
        packet[7] = 0x01 + index
        packet[8] = (0x01 if turn_on else 0x02) if turn_on is not None else 0xFF
        packet[9] = (brightness & 0xFF) if brightness is not None else 0xFF
        packet[10:13] = [0xFF, 0x00, 0xFF]
        return finalize_packet(packet)
    
    def build_outlet_packet(
        self, room: int, index: int, *, turn_on: bool | None = None, standby_cutoff: bool | None = None, query: bool = False
    ) -> bytearray:
        """Build outlet packet."""
        is_dimming = self._get("dimming_generation")
        is_aio = self._get("aio_generation")
        
        if query:
            packet = make_packet(0x31, 0x07, 0x11, self.spin_code)
            if is_dimming:
                packet[1:3] = [0x30 + room, 0x06]
            elif is_aio:
                packet[1:3] = [0x50 + room, 0x06]
            else:
                packet[5] = room & 0x0F
        else:
            cmd = 0x01 if turn_on else 0x02
            
            if is_dimming:
                packet = make_packet(0x30 + room, 0x09, 0x22, self.spin_code)
                packet[5] = 0x01
                packet[6] = (index + 1) & 0x0F
                packet[7] = cmd if standby_cutoff is None else (cmd * 0x10)
            elif is_aio:
                packet = make_packet(0x50 + room, 0x0C, 0x12, self.spin_code)
                packet[8] = 0x01
                packet[9] = (index + 1) & 0x0F
                packet[10] = (cmd << 4) if standby_cutoff is not None else cmd
            else:
                packet = make_packet(0x31, 0x0D, 0x01, self.spin_code)
                packet[5] = room & 0x0F
                if standby_cutoff is not None:
                    packet[8] = 0x83 if turn_on else 0x03
                else:
                    position_flag = 0x80 if turn_on else 0x00
                    packet[7] = (1 << index) | position_flag
                    if turn_on:
                        packet[11] = 0x09 << index
        
        return finalize_packet(packet)
    
    def build_ventilator_packet(self, *, fan_mode: FanMode | None = None, query: bool = False) -> bytearray:
        """Build ventilator packet."""
        room_ventilation = self._get("room_ventilation")
        
        if query:
            if room_ventilation:
                return finalize_packet(make_packet(0x61, 0x06, 0x11, self.spin_code))
            else:
                return finalize_packet(bytearray([0x02, 0x61, 0x00, self.spin_code] + [0x00] * 6))
        
        if room_ventilation:
            packet = make_packet(0x61, 0x09, 0x21, self.spin_code)
            packet[5] = 0x01 if fan_mode == FanMode.OFF else 0x40
            packet[7] = {
                FanMode.OFF: 0x01,
                FanMode.LOW: 0x01,
                FanMode.MEDIUM: 0x02,
                FanMode.HIGH: 0x03
            }.get(fan_mode, 0x01)
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
        batch_header = self._get("batch_switch_header")
        
        if batch_header != 0xC1:
            packet = bytearray([0x02, batch_header, 0x04, 0x01, self.spin_code, 0x00, 0x00, 0x01 if turn_on else 0x00, 0x00, 0x00])
        else:
            packet = make_packet(0xC1, 0x0C, 0x91, self.spin_code)
            packet[6:11] = [0x01, 0x00, 0x01 if turn_on else 0x02, 0x01, 0x02]
        
        return finalize_packet(packet)
    
    def build_elevator_packet(self, *, direction: ElevatorState | None = None) -> bytearray:
        """Build elevator call packet."""
        packet = make_packet(0xC1, 0x0C, 0x91, self.spin_code)
        packet[5] = {
            ElevatorState.MOVING_DOWN: 0x10,
            ElevatorState.MOVING_UP: 0x20
        }.get(direction, 0x00)
        packet[6:11] = [0x01, 0x00, 0x02, 0x01, 0x02]
        return finalize_packet(packet)
    
    def build_intercom_packet(self, entrance_type: IntercomType, *, open_door: bool = False, force_view: bool = False) -> bytearray:
        """Build intercom control packet."""
        type_byte = 0x01 if entrance_type == IntercomType.HOME else 0x02
        
        if force_view and entrance_type == IntercomType.HOME:
            packet = bytearray([0x02, 0x01, 0x02, 0x05, type_byte, 0x00, 0x00, 0x00])
            data = packet[1:] + bytearray([0x03])
            checksum = calculate_intercom_checksum(data, include_end=False)
        elif open_door:
            packet = bytearray([0x02, 0x00, 0x02, 0x08, type_byte, 0x00, 0x00, 0x00])
            checksum = calculate_intercom_checksum(packet, include_end=False)
        else:
            packet = bytearray([0x02, 0x00, 0x01, 0x11, type_byte, 0x00, 0x00, 0x00])
            checksum = calculate_intercom_checksum(packet, include_end=False)
        
        packet.append(checksum)
        packet.append(0x03)
        return packet
    
    def parse_packet(self, packet: bytes) -> list[DeviceState]:
        """Parse packet and return device states."""
        if len(packet) < 4:
            return []
        
        header = packet[1]
        packet_len = len(packet)
        self.spin_code = packet[3] if packet_len == 10 else packet[4]
        
        if header in [0x15, 0x17]:
            return self._parse_batch_elevator(packet)
        elif header == 0x28:
            return self._parse_thermostat(packet)
        elif header == 0x41:
            if packet_len == 10:
                return self._parse_doorlock(packet)
            return []
        elif header == 0x61:
            return self._parse_ventilator(packet)
        elif header in [0x31, 0x32, 0x33, 0x34, 0x3F]:
            if packet_len == 10:
                return self._parse_gasvalve(packet)
            elif packet_len in [7, 30]:
                return self._parse_light_outlet(packet)
            else:
                return self._parse_dimming_outlet(packet)
        elif header in [0x51, 0x52, 0x53, 0x54, 0x55]:
            return self._parse_aio_light_outlet(packet)
        elif header in [0xA2, 0xC1]:
            return self._parse_batch_elevator(packet)
        elif header == 0xD1:
            return self._parse_energy(packet)
        else:
            return []
    
    def _parse_thermostat(self, packet: bytes) -> list[DeviceState]:
        """Parse thermostat packet."""
        if packet[3] not in [0x91, 0x92]:
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
        if packet[3] not in [0x91, 0x81]:
            return []
        
        room_id = packet[5] & 0x0F
        if room_id == 1:
            light_cnt, outlet_cnt = 4, 3
        else:
            light_cnt, outlet_cnt = 2, 2
        
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
            if len(packet) > power_idx + 2:
                power_usage = int.from_bytes(packet[power_idx:power_idx + 2], "big") / 10.0
                devices.append(self._create_device_state(DeviceType.OUTLET, room_id, i, power_usage, DeviceSubType.POWER_USAGE))
        
        return devices
    
    def _parse_aio_light_outlet(self, packet: bytes) -> list[DeviceState]:
        """Parse AIO generation light/outlet packet."""
        if packet[3] not in [0x91, 0x92]:
            return []
        
        if self._get("aio_generation", False) is False:
            self._set("aio_generation", True)
        
        room_id = packet[1] & 0x0F
        devices = []
        
        for i in range(min(packet[5], 8)):
            devices.append(self._create_device_state(DeviceType.LIGHT, room_id, i, bool(packet[6] & (1 << i))))
        
        for i in range(2):
            is_on = (packet[9 + 5 * i] & 0x0F) == 0x01
            standby_cutoff = packet[9 + 5 * i] in [0x11, 0x12, 0x13]
            power_usage = int.from_bytes(packet[10 + 5 * i:12 + 5 * i], "big") / 10.0
            
            devices.extend([
                self._create_device_state(DeviceType.OUTLET, room_id, i, is_on),
                self._create_device_state(DeviceType.OUTLET, room_id, i, standby_cutoff, DeviceSubType.STANDBY_CUTOFF),
                self._create_device_state(DeviceType.OUTLET, room_id, i, power_usage, DeviceSubType.POWER_USAGE),
            ])
        
        return devices
    
    def _parse_ventilator(self, packet: bytes) -> list[DeviceState]:
        """Parse ventilator packet."""
        if packet[2] in [0x80, 0x81, 0x83, 0x84, 0x87]:
            is_on = packet[5] & 0x01
            speed = packet[6] if is_on else 0
        elif packet[3] in [0x91, 0xA1]:
            if self._get("room_ventilation", False) is False:
                self._set("room_ventilation", True)
            
            is_on = packet[6]
            speed = packet[8] if is_on else 0
        else:
            return []
        
        fan_mode = {
            0: FanMode.OFF,
            1: FanMode.LOW,
            2: FanMode.MEDIUM,
            3: FanMode.HIGH
        }.get(speed, FanMode.OFF)
        
        return [
            self._create_device_state(DeviceType.VENTILATION, 0, 0, {"is_on": bool(is_on), "fan_mode": fan_mode, "speed": speed})
        ]
    
    def _parse_batch_elevator(self, packet: bytes) -> list[DeviceState]:
        """Parse batch switch and elevator packet."""
        pkt_len = packet[2]
        pkt_type = packet[3]
        devices = []
        
        if pkt_len == 0x0C and pkt_type == 0x91:
            elev_byte = packet[5]
            direction = {
                0x10: ElevatorState.MOVING_DOWN,
                0x20: ElevatorState.MOVING_UP
            }.get(elev_byte, ElevatorState.IDLE)
            
            devices.extend([
                self._create_device_state(DeviceType.ELEVATOR, 0, 0, direction != ElevatorState.IDLE),
                self._create_device_state(DeviceType.ELEVATOR, 0, 0, direction, DeviceSubType.DIRECTION),
                self._create_device_state(DeviceType.BATCHSWITCH, 0, 0, packet[8] != 0x02),
            ])
        
        elif pkt_len == 0x13 and pkt_type == 0x13:
            if packet[11] == 0x04:
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, False))
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, ElevatorState.ARRIVED, DeviceSubType.DIRECTION))
            
            if packet[12] != 0xFF:
                if packet[12] & 0x80:
                    floor = f"B{packet[12] & 0x7F}"
                else:
                    floor = str(packet[12])
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, floor, DeviceSubType.FLOOR))
        
        elif pkt_len in [0x80, 0x81, 0x84, 0x87]:
            if self._get("batch_switch_header", 0xC1) != packet[1]:
                self._set("batch_switch_header", packet[1])
            
            if packet[7] == 0x40:
                devices.append(self._create_device_state(DeviceType.ELEVATOR, 0, 0, ElevatorState.MOVING_DOWN, DeviceSubType.DIRECTION))
            else:
                devices.append(self._create_device_state(DeviceType.BATCHSWITCH, 0, 0, packet[7] == 0x01))
        
        return devices
    
    def _parse_dimming_outlet(self, packet: bytes) -> list[DeviceState]:
        """Parse dimming light/outlet packet."""
        if packet[3] not in [0x91, 0xA1, 0xA2]:
            return []
        
        if self._get("dimming_generation", False) is False:
            self._set("dimming_generation", True)
        
        room_id = packet[1] & 0x0F
        light_count = packet[10] & 0x0F
        outlet_count =  packet[11] & 0x0F
        
        if packet[10] >> 4 == 0x04:
            base_count = light_count + 1
        else:
            base_count = light_count
        
        light_idx = 17
        outlet_idx = 17 + base_count * 13
        devices = []
        
        for _ in range(light_count):
            if packet[light_idx] >> 4 == 0x08:
                light_idx += 13
                continue
            
            light_num = (packet[light_idx] & 0x0F) - 1
            is_on = bool(packet[light_idx + 1] & 0x01)
            brightness = packet[light_idx + 2]
            power = int.from_bytes(packet[light_idx + 9:light_idx + 11], "big") / 10.0
            
            if brightness > 0:
                device_type = DeviceType.DIMMINGLIGHT
                state = {"is_on": is_on, "brightness": brightness}
            else:
                device_type = DeviceType.DIMMINGLIGHT
                state = {"is_on": is_on}
            devices.append(self._create_device_state(device_type, room_id, light_num, state))
            
            if power > 0:
                devices.append(self._create_device_state(device_type, room_id, light_num, power, DeviceSubType.POWER_USAGE))
            
            light_idx += 13
        
        for _ in range(outlet_count):
            if packet[outlet_idx] >> 4 == 0x08:
                outlet_idx += 14
                continue
            
            outlet_num = (packet[outlet_idx] & 0x0F) - 1
            is_on = bool(packet[outlet_idx + 1] & 0x01)
            standby = bool(packet[outlet_idx + 1] & 0x10)
            cutoff = int.from_bytes(packet[outlet_idx + 7:outlet_idx + 9], "big") / 10.0
            power = int.from_bytes(packet[outlet_idx + 9:outlet_idx + 11], "big") / 10.0
            
            devices.extend([
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, is_on),
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, standby, DeviceSubType.STANDBY_CUTOFF),
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, cutoff, DeviceSubType.CUTOFF_VALUE),
                self._create_device_state(DeviceType.OUTLET, room_id, outlet_num, power, DeviceSubType.POWER_USAGE),
            ])
            
            outlet_idx += 14
        
        return devices
    
    def _parse_gasvalve(self, packet: bytes) -> list[DeviceState]:
        """Parse gas valve packet."""
        if packet[2] not in [0x80, 0x82]:
            return []
        return [self._create_device_state(DeviceType.GASVALVE, 0, 0, bool(packet[5]))]
    
    def _parse_doorlock(self, packet: bytes) -> list[DeviceState]:
        """Parse doorlock packet."""
        if packet[2] not in [0x80, 0x82]:
            return []
        return [self._create_device_state(DeviceType.DOORLOCK, 0, 0, bool(packet[5] & 0xAE))]
    
    def _parse_energy(self, packet: bytes) -> list[DeviceState]:
        """Parse HEMS energy packet."""
        if packet[3] not in [0x82]:
            return []

        i = next((j + 1 for j in range(5, min(10, len(packet))) if packet[j] == 0x80), None)
        if not i:
            return []

        count = packet[i]
        idx = i + 1
        energy_names = {1: "electric", 2: "water", 3: "hotwater", 4: "gas", 5: "heat"}
        devices = []

        for _ in range(min(count, 5)):
            eid = packet[idx]
            if eid & 0x80:  # not used
                idx += 2
                continue

            data = packet[idx + 1:idx + 8]
            total = int.from_bytes(data[:4], "big")
            realtime = int.from_bytes(data[4:6], "big")
            name = energy_names.get(eid & 0x7F, f"unknown_{eid & 0x7F}")

            devices.append(
                self._create_device_state(
                    DeviceType.ENERGY, 0, eid & 0x7F, {"total": total, "realtime": realtime}, attributes={"energy_type": name}
                )
            )
            idx += 8

        return devices
    
    def _parse_intercom(self, packet: bytes) -> list[DeviceState]:
        """Parse intercom (subphone) packet."""
        header = packet[1]
        cmd = packet[3]
        entrance_type_byte = packet[4]
        
        if entrance_type_byte == 0x01:
            entrance_type = IntercomType.HOME
            sub_type = DeviceSubType.HOME_ENTRANCE
        elif entrance_type_byte == 0x02:
            entrance_type = IntercomType.COMMON
            sub_type = DeviceSubType.COMMON_ENTRANCE
        else:
            LOGGER.debug("Unknown intercom entrance type: 0x%02X", entrance_type_byte)
            return []
        
        devices = []
        
        if cmd == 0x01 and header == 0x00:
            LOGGER.info("Intercom doorbell pressed: %s", "Home" if entrance_type == IntercomType.HOME else "Common")
            devices.append(
                self._create_device_state(
                    DeviceType.INTERCOM,
                    0,
                    entrance_type,
                    True,
                    sub_type=sub_type,
                    attributes={"event": "doorbell"}
                )
            )
        elif header == 0x02:
            pass
        
        return devices
