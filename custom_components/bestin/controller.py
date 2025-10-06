from __future__ import annotations

import asyncio
from typing import Any, Callable

from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    LOGGER,
    MAIN_DEVICES,
    DEVICE_PLATFORM_MAP,
    PLATFORM_SIGNAL_MAP,
    Device,
    DeviceKey,
    DeviceType,
    DeviceSubType,
)


class BestinController:

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
        
        self.device_storage: dict[str, Any] = {}
        self.devices: dict[str, Device] = {}
        self.tasks: list[asyncio.Task] = []

    async def start(self):
        """Start the controller tasks"""
        self.tasks = [
            self.hass.loop.create_task(self.process_incoming_data()),
            self.hass.loop.create_task(self.process_queue_data())
        ]

    async def stop(self):
        """Stop the controller tasks"""
        if self.tasks:
            for task in self.tasks:
                task.cancel()
            self.tasks = []

    @property
    def is_alive(self) -> bool:
        """Check if the connection is alive"""
        return self.connection.is_connected()
    
    async def receive_data(self) -> bytes:
        """Receive data if the connection is alive"""
        if self.is_alive:
            return await self.connection.receive()

    async def send_data(self, packet: bytearray):
        """Send data if the connection is alive"""
        if self.is_alive:
            await self.connection.send(packet)

    def calculate_checksum(self, packet: bytearray) -> int:
        """Calculate the checksum for a packet"""
        checksum = 3
        for i in range(len(packet) - 1):
            checksum ^= packet[i]
            checksum = (checksum + 1) & 0xFF
        return checksum
    
    def verify_checksum(self, packet: bytes) -> bool:
        """Verify the checksum of a packet"""
        if len(packet) < 6:
            return False
        
        checksum = 3
        for byte in packet[:-1]:
            checksum ^= byte
            checksum = (checksum + 1) & 0xFF
        return checksum == packet[-1]

    def get_devices_from_platform(self, platform: str) -> list:
        """Get devices from a specific platform"""
        entity_list = self.entity_groups.get(platform, [])
        return [self.devices.get(uid, {}) for uid in entity_list]

    def make_common_packet(self, header: int, length: int, packet_type: int, spin_code: int) -> bytearray:
        """Create a common packet structure"""
        packet = bytearray([
            0x02, 
            header & 0xFF, 
            length & 0xFF, 
            packet_type & 0xFF, 
            spin_code & 0xFF
        ])
        packet.extend(bytearray([0] * (length - 5)))
        return packet
    
    def make_light_packet(self, key: DeviceKey, value: bool | int, name: str | None) -> bytearray:
        """Create a packet for light control"""
        header = self.device_storage.get("lo_header")
        room   = key.room_index & 0x0F
        d_idx  = key.device_index & 0x0F
        is_bool = isinstance(value, bool)

        if header == 0x50:
            packet = self.make_common_packet(header + room, 0x0A, 0x12, 0)
        elif header == 0x30:
            packet = self.make_common_packet(header + room, 0x0E, 0x21, 0)
        else:
            packet = self.make_common_packet(0x31, 0x0D, 0x01, 0)
            packet[5] = room

        if header == 0x50:
            # [5]: on/off 플래그, [6]: 채널 비트(특이 케이스: index==4 -> 10)
            packet[5] = 0x01 if (value if is_bool else value > 0) else 0x00
            packet[6] = 10 if d_idx == 4 else (1 << d_idx)
        elif header == 0x30:
            # [5:13] = [mode, pad, device#, cmd(1/2), FF, FF, 00, FF]
            onoff_cmd = 0x01 if (value if is_bool else value > 0) else 0x02
            packet[5:13] = [0x01, 0x00, (d_idx + 1) & 0x0F, onoff_cmd, 0xFF, 0xFF, 0x00, 0xFF]

            # 밝기/디밍 값 처리 (value가 int인 경우만)
            if not is_bool:
                # 원 코드대로: [8]=0xFF 마킹 후 name 에 따라 [9] 또는 [10] 채움
                packet[8] = 0xFF
                dim = int(value) & 0xFF
                if name == "set_brightness":
                    packet[9] = dim
                else:
                    packet[10] = dim
        else:
            turn_on = (value if is_bool else value > 0)
            packet[6]  = ((0x01 << d_idx) | 0x80) if turn_on else 0x00
            packet[11] = 0x04 if turn_on else 0x00

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_outlet_packet(self, key: DeviceKey, value: bool) -> bytearray:
        """Create a packet for outlet control"""
        header = self.device_storage.get("lo_header")
        room = key.room_index & 0x0F
        dev_idx_1based = (key.device_index + 1) & 0x0F
        base_cmd = 0x01 if value else 0x02

        if header == 0x50:
            packet = self.make_common_packet(header + room, 0x0C, 0x12, 0)
        elif header == 0x30:
            packet = self.make_common_packet(header + room, 0x09, 0x22, 0)
        else:
            packet = self.make_common_packet(0x31, 0x0D, 0x01, 0)
            packet[5] = room

        if header == 0x50:
            # format: [8]=1, [9]=device#, [10]=cmd (서브타입 처리 포함)
            packet[8] = 0x01
            packet[9] = dev_idx_1based
            cmd = base_cmd
            if key.sub_type != DeviceSubType.NONE:
                cmd <<= 4
            packet[10] = cmd
        elif header == 0x30:
            # format: [5]=1, [6]=device#, [7]=cmd (STANDBY_CUTOFF이면 상위 니블)
            packet[5] = 0x01
            packet[6] = dev_idx_1based
            cmd = base_cmd
            if key.sub_type == DeviceSubType.STANDBY_CUTOFF:
                cmd <<= 4  # 0x01 -> 0x10, 0x02 -> 0x20
            packet[7] = cmd
        else:
            if key.sub_type == DeviceSubType.STANDBY_CUTOFF:
                # 0x83(ON)/0x03(OFF)
                packet[8] = 0x83 if value else 0x03
            else:
                if value:
                    packet[7]  = (0x01 << key.device_index) | 0x80
                    packet[11] = (0x09 << key.device_index)
                else:
                    packet[7]  = 0x00
                    packet[11] = 0x00

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_thermostat_packet(self, key: DeviceKey, value: bool | float, name: str | None) -> bytearray:
        """Create a packet for thermostat control"""
        packet = self.make_common_packet(0x28, 14, 0x12, 0)
        packet[5] = key.room_index & 0x0F
        
        if name == "set_temperature":
            value_int = int(value)
            value_float = value - value_int
            packet[7] = value_int & 0xFF
            if value_float != 0:
                packet[7] |= 0x40
        else:
            packet[6] = 0x01 if value else 0x02

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_gasvalve_packet(self, key: DeviceKey, value: bool) -> bytearray | None:
        """Create a packet for gas valve control"""
        if value == True:
            # only control closed
            return None
        packet = bytearray([0x02, 0x31, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_doorlock_packet(self, key: DeviceKey, value: bool) -> bytearray | None:
        """Create a packet for doorlock control"""
        if value == False:
            # only control open
            return None
        packet = bytearray([0x02, 0x41, 0x02, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
        packet[-1] = self.calculate_checksum(packet)
        return packet

    def make_ventilation_packet(self, key: DeviceKey, value: bool | int, name: str | None) -> bytearray:
        """Create a packet for ventilation control"""
        packet = bytearray([0x02, 0x61, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        if name == "set_percentage":
            packet[2] = 0x03
            packet[6] = value
        elif name == "preset_mode":
            packet[2] = 0x07
            packet[5] = 0x10 if value else 0x00
        else:
            packet[2] = 0x01
            packet[5] = 0x01 if value else 0x00
            packet[6] = 0x01

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    async def send_command(self, key: DeviceKey, value: Any, name: str | None):
        """Send a command to a device"""
        device_type = key.device_type
        
        if device_type == DeviceType.LIGHT:
            packet = self.make_light_packet(key, value, name)
        elif device_type == DeviceType.OUTLET:
            packet = self.make_outlet_packet(key, value)
        elif device_type == DeviceType.THERMOSTAT:
            packet = self.make_thermostat_packet(key, value, name)
        elif device_type == DeviceType.GASVALVE:
            packet = self.make_gasvalve_packet(key, value)
        elif device_type == DeviceType.DOORLOCK:
            packet = self.make_doorlock_packet(key, value)
        elif device_type == DeviceType.VENTILATION:
            packet = self.make_ventilation_packet(key, value, name)
        else:
            LOGGER.error(f"Faild to make packet caused by unsupported device type '{device_type}'")
            return
        
        if packet is None:
            return
        
        await self.send_data(packet)
    
    def initial_device(self, device_id: str, sub_id: str | None, state: Any) -> dict:
        """Initialize a device"""
        device_type, device_room = device_id.split("_")
    
        did_suffix = f"_{sub_id}" if sub_id else ""
        device_id = f"bestin_{device_id}{did_suffix}"
        if sub_id:
            sub_id_parts = sub_id.split("_")
            device_name = f"{device_type} {device_room} {' '.join(sub_id_parts)}".title()
        else:
            device_name = f"{device_type} {device_room}".title()
        
        if device_type not in ["energy"] and sub_id and not sub_id.isdigit():
            device_type = f"{device_type}:{''.join(filter(str.isalpha, sub_id))}"
        
        if device_type not in MAIN_DEVICES:
            uid_suffix = f"-{self.host}"
        else:
            uid_suffix = ""
        unique_id = f"{device_id}{uid_suffix}"

        if device_id not in self.devices:
            device_info = DeviceInfo(
                device_type=device_type,
                name=device_name,
                room=device_room,
                state=state,
                device_id=device_id,
            )
            self.devices[device_id] = DeviceProfile(
                enqueue_command=self.enqueue_command,
                domain=DEVICE_PLATFORM_MAP[device_type],
                unique_id=unique_id,
                info=device_info,
            )
        return self.devices[device_id]
    
    def set_device(self, device_id: str, state: Any, is_sub: bool = False):
        """Set the state of a device"""
        device_type, device_room = device_id.split("_")

        if device_type not in DEVICE_PLATFORM_MAP:
            LOGGER.error(f"Unsupported device type '{device_type}' in '{device_room}'")
            return
        
        sub_states = state.items() if is_sub else [(None, state)]
        for sub_id, sub_state in sub_states:
            device = self.initial_device(device_id, sub_id, sub_state)

            if device_type not in ["energy"] and sub_id and not sub_id.isdigit():
                format_device = f"{device_type}:{''.join(filter(str.isalpha, sub_id))}"
                device_platform = DEVICE_PLATFORM_MAP[format_device]
            else:
                device_platform = DEVICE_PLATFORM_MAP[device_type]
            
            device_uid = device.unique_id
            device_info = device.info
            if device_uid not in self.entity_groups.get(device_platform, []):
                signal = PLATFORM_SIGNAL_MAP[device_platform]
                self.add_device_callback(signal, device)

            if device_info.state != sub_state:
                device_info.state = sub_state
                device.update_callbacks()

    def parse_thermostat(self, packet: bytearray) -> dict:
        """Parse thermostat data from a packet"""
        is_on = packet[6] & 0x01
        hvac_mode = HVACMode.HEAT if is_on else HVACMode.OFF
        target_temperature = (packet[7] & 0x3F) + (packet[7] & 0x40 > 0) * 0.5
        current_temperature = int.from_bytes(packet[8:10], byteorder="big") / 10.0

        return {
            "device_type": DeviceType.THERMOSTAT,
            "room_id": packet[5] & 0x0F,
            "device_index": 1,
            "state": {
                "hvac_mode": hvac_mode,
                "set_temperature": target_temperature,
                "current_temperature": current_temperature
            }
        }
    
    def parse_gas(self, packet: bytearray) -> dict:
        """Parse gas data from a packet"""
        return {
            "device_type": DeviceType.GASVALVE,
            "room_id": 0,
            "device_index": 1,
            "state": packet[5]
        }
    
    def parse_doorlock(self, packet: bytearray) -> dict:
        """Parse doorlock data from a packet"""
        return {
            "device_type": DeviceType.DOORLOCK,
            "room_id": 0,
            "device_index": 1,
            "state": packet[5] & 0xAE
        }
    
    def parse_ventilation(self, packet: bytearray) -> dict:
        """Parse ventilation data from a packet"""
        is_natural_ventilation = packet[5] >> 4 & 1
        preset_mode	= "natural" if is_natural_ventilation else "none"
        return {
            "device_type": DeviceType.VENTILATION,
            "room_id": 0,
            "device_index": 1,
            "state": {
                "is_on": packet[5] & 0x01,
                "speed": packet[6],
                "preset_mode": preset_mode,
            },
            "attributes": {
                "speed_list": [1, 2, 3],
                "preset_modes": ["natural", "none"],
            }
        }
    
    def parse_state_light(self, packet: bytearray) -> dict:
        """Parse light state data from a packet"""
        result = {"devices": []}
        
        room_id = packet[5] & 0x0F
        if room_id == 1:
            light_cnt, outlet_cnt = 4, 3
        else:
            light_cnt, outlet_cnt = 2, 2

        for i in range(light_cnt):
            light_state = bool(packet[6] & (0x01 << i))
            power = int.from_bytes(packet[12:14], 'big') / 10.0
            result["devices"].append({
                "device_type": DeviceType.LIGHT,
                "room_id": room_id,
                "device_index": i,
                "state": light_state,
            })
            result["devices"].append({
                "device_type": DeviceType.LIGHT,
                "room_id": room_id,
                "device_index": i,
                "state": power,
                "sub_type": DeviceSubType.POWER_USAGE,
            })

        for i in range(outlet_cnt): 
            idx = 14 + 2 * i
            idx2 = idx + 2

            if len(packet) > idx2:
                value = int.from_bytes(packet[idx:idx2], byteorder="big")
                power = value / 10.
            else:
                power = 0.
            
            if i < 2:
                idx = 8 + 2 * i
                idx2 = idx + 2

                cutoff_value = int.from_bytes(packet[idx:idx2], byteorder="big") / 10
                result["devices"].append({
                    "device_type": DeviceType.OUTLET,
                    "room_id": room_id,
                    "device_index": i,
                    "state": cutoff_value,
                    "sub_type": DeviceSubType.CUTOFF_VALUE,
                })

            state = bool(packet[7] & (0x01 << i))
            standby_cutoff = bool(packet[7] >> 4 & 1)

            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": state,
            })
            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": standby_cutoff,
                "sub_type": DeviceSubType.STANDBY_CUTOFF,
            })

        return result
        
    def parse_state_dimming(self, packet: bytearray) -> dict:
        """Parse dimming light state data from a packet"""
        result = {"devices": []}
        
        room_id = packet[1] & 0x0F
        if room_id % 2:
            light_cnt = packet[10]
            outlet_cnt = packet[11]
            base_count = light_cnt
        else:
            light_cnt = packet[10] & 0x0F
            outlet_cnt = packet[11]
            base_count = outlet_cnt

        light_idx = 18
        outlet_idx = light_idx + (base_count * 13)

        for i in range(light_cnt):
            brightness, color_temp = packet[light_idx + 1], packet[light_idx + 2]
            power = int.from_bytes(packet[light_idx + 8:light_idx + 10], byteorder="big") / 10
            
            device_type = DeviceType.LIGHT
            state = {
                "is_on": packet[light_idx] == 0x01,
            }
            if brightness > 0:
                device_type = DeviceType.DIMMINGLIGHT
                state["brightness"] = brightness
            if color_temp > 0:
                device_type = DeviceType.DIMMINGLIGHT
                state["color_temp"] = color_temp
            
            result["devices"].append({
                "device_type": device_type,
                "room_id": room_id,
                "device_index": i,
                "state": state,
            })
            result["devices"].append({
                "device_type": device_type,
                "room_id": room_id,
                "device_index": i,
                "state": power,
                "sub_type": DeviceSubType.POWER_USAGE,
            })

            light_idx += 13

        for i in range(outlet_cnt):
            outlet_state = packet[outlet_idx] & 0x01
            standby_cutoff = packet[outlet_idx] & 0x10
            cutoff_value = int.from_bytes(packet[outlet_idx + 6:outlet_idx + 8], byteorder="big") / 10
            power = int.from_bytes(packet[outlet_idx + 8:outlet_idx + 10], byteorder="big") / 10

            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": outlet_state,
            })
            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": standby_cutoff,
                "sub_type": DeviceSubType.STANDBY_CUTOFF,
            })
            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": cutoff_value,
                "sub_type": DeviceSubType.CUTOFF_VALUE,
            })
            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": power,
                "sub_type": DeviceSubType.POWER_USAGE,
            })
            outlet_idx += 14

        return result

    def parse_state_aio(self, packet: bytearray) -> dict:
        """Parse AIO light and outlet state data from a packet"""
        result = {"devices": []}
        room_id = packet[1] & 0x0F

        for i in range(packet[5]):
            light_state = bool(packet[6] & (1 << i))
            result["devices"].append({
                "device_type": DeviceType.LIGHT,
                "room_id": room_id,
                "device_index": i,
                "state": light_state,
            })

        for i in range(2):
            idx = 9 + 5 * i    # state
            idx2 = 10 + 5 * i  # power usage

            outlet_state = packet[idx] in [0x21, 0x11]
            standby_cutoff = packet[idx] in [0x11, 0x13, 0x12]
            power = (packet[idx2] << 8 | packet[idx2 + 1]) / 10

            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": outlet_state,
            })
            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": standby_cutoff,
                "sub_type": DeviceSubType.STANDBY_CUTOFF,
            })
            result["devices"].append({
                "device_type": DeviceType.OUTLET,
                "room_id": room_id,
                "device_index": i,
                "state": power,
                "sub_type": DeviceSubType.POWER_USAGE,
            })

        return result
    
    def parse_energy(self, packet: bytearray) -> dict:
        """Parse energy data from a packet"""

    def handle_device_packet(self, packet: bytes):
        """Handle a device packet"""
        

    async def handle_packet_queue(self, queue: dict):
        """Handle a packet from the queue"""

    async def process_incoming_data(self):
        """Process incoming data"""
        while True:
            if not self.is_alive:
                await asyncio.sleep(5)
                continue

            try:
                received_data = await self.receive_data()
                if not received_data:
                    continue

                checksum_valid = self.verify_checksum(received_data)
                if checksum_valid:
                    self.handle_device_packet(received_data)
            except Exception as ex:
                LOGGER.error(f"Failed to process incoming data: {ex}", exc_info=True)

    async def process_queue_data(self):
        """Process data in the queue"""
        while True:
            try:
                await asyncio.sleep(0.1)
            except Exception as ex:
                LOGGER.error(f"Failed to process task queue: {ex}", exc_info=True)
