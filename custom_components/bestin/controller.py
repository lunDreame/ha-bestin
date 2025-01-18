import asyncio
from typing import Any, Callable

from homeassistant.components.climate.const import (
    SERVICE_SET_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ATTR_CURRENT_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.fan import SERVICE_SET_PERCENTAGE
from homeassistant.components.light import (
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import ATTR_STATE, WIND_SPEED

from .const import (
    LOGGER,
    DEFAULT_MAX_SEND_RETRY,
    DEFAULT_PACKET_VIEWER,
    BRAND_PREFIX,
    PRESET_NV,
    PRESET_NONE,
    MAIN_DEVICES,
    DEVICE_PLATFORM_MAP,
    PLATFORM_SIGNAL_MAP,
    SPEED_INT_LOW,
    SPEED_INT_MEDIUM,
    SPEED_INT_HIGH,
    DeviceProfile,
    DeviceInfo,
)

ENERGY_BYTE_RANGE = {
    "electric": (slice(8, 12), slice(8, 12)),
    "gas": (slice(32, 36), slice(25, 29)),
    "heat": (slice(40, 44), slice(40, 44)),
    "hotwater": (slice(24, 28), slice(24, 28)),
    "water": (slice(17, 20), slice(17, 20)),
}


class AsyncQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def put(self, item):
        """Function to put data into the queue"""
        await self.queue.put(item)
    
    async def get(self):
        """Function to get data from the queue (only retrieve, not delete)"""
        if not self.queue.empty():
            item = await self.queue.get()
            await self.queue.put(item)
            return item
        return None
    
    async def delete(self):
        """Function to delete data from the queue"""
        if not self.queue.empty():
            return await self.queue.get()
        return None
    
    async def size(self):
        """Function to return the size of the queue"""
        return self.queue.qsize()


class BestinController:
    """Controller for managing Bestin devices and communication."""

    def __init__(
        self, 
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_groups: dict[str, set[str]],
        hub_id: str, 
        connection,
        add_device_callback: Callable,
    ) -> None:
        """Initialize the BestinController."""
        self.hass = hass
        self.entry = entry
        self.entity_groups = entity_groups
        self.hub_id = hub_id
        self.connection = connection
        self.add_device_callback = add_device_callback
        self.gateway_type: str = entry.data["gateway_mode"][0]
        self.room_to_command: dict[bytes] = entry.data["gateway_mode"][1]
        
        self.devices: dict[str, DeviceProfile] = {}
        self.queue = AsyncQueue()
        self.tasks: list[asyncio.Task] = []
        self.timestamp = 0

    async def start(self):
        """Start the controller tasks"""
        self.tasks = [
            self.hass.loop.create_task(self.process_incoming_data()),
            self.hass.loop.create_task(self.process_queue_data())
        ]
        await asyncio.sleep(1)

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
            if self.gateway_type == "Gen2":
                interval = 0.22
            else:
                interval = 0.12
            await self.connection.send(packet, interval)

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

    def get_devices_from_domain(self, domain: str) -> list:
        """Get devices from a specific domain"""
        entity_list = self.entity_groups.get(domain, [])
        return [self.devices.get(uid, {}) for uid in entity_list]

    def make_light_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool | int
    ) -> bytearray:
        """Create a packet for light control"""
        aio_gateway = self.gateway_type == "AIO"
        onoff_value = 0x01 if value else 0x00
        onoff_value2 = 0x04 if value else 0x00
        position_flag = 0x80 if value else 0x00
        
        if aio_gateway:
            room_id_conv = 0x50 + room_id
            packet = self.make_common_packet(room_id_conv, 0x0A, 0x12, timestamp)
            packet[5] = onoff_value
            packet[6] = 10 if pos_id == 4 else 1 << pos_id
        elif self.gateway_type == "Gen2":
            room_id_conv = 0x30 + room_id
            packet = self.make_common_packet(room_id_conv, 0x0E, 0x21, timestamp)
            
            pos_id += 1
            onoff_value = 0x01 if value else 0x02
            
            packet[5:13] = [
                0x01, 0x00, pos_id, onoff_value, 0xFF, 0xFF, 0x00, 0xFF
            ]
            if not isinstance(value, bool):
                packet[8] = 0xFF
                if sub_type == COLOR_MODE_BRIGHTNESS:
                    packet[9] = value
                else:
                    packet[10] = value
        else:
            packet = self.make_common_packet(0x31, 0x0D, 0x01, timestamp)
            packet[5] = room_id & 0x0F
            packet[6] = (0x01 << pos_id) | position_flag
            packet[11] = onoff_value2

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_outlet_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str | None, value: bool
    ) -> bytearray:
        """Create a packet for outlet control"""
        aio_gateway = self.gateway_type == "AIO"
        onoff_value = 0x01 if value else 0x02
        onoff_value2 = (0x09 << pos_id) if value else 0x00
        position_flag = 0x80 if value else 0x00

        if aio_gateway:
            room_id_conv = 0x50 + room_id 
            packet = self.make_common_packet(room_id_conv, 0x0C, 0x12, timestamp)
        elif self.gateway_type == "Gen2":
            room_id_conv = 0x30 + room_id
            packet = self.make_common_packet(room_id_conv, 0x09, 0x22, timestamp)
        else:
            packet = self.make_common_packet(0x31, 0x0D, 0x01, timestamp)
            packet[5] = room_id & 0x0F

        if aio_gateway:
            packet[8] = 0x01
            packet[9] = (pos_id + 1) & 0x0F
            packet[10] = onoff_value >> (onoff_value + 3) if sub_type else onoff_value
        elif self.gateway_type == "Gen2":
            packet[5] = 0x01
            packet[6] = (pos_id + 1) & 0x0F
            packet[7] = 0x01 if value else 0x02
            if sub_type == "standbycut":
                packet[7] *= 0x10
        else:
            if sub_type == "standbycut":
                packet[8] = 0x83 if value else 0x03
            else:
                packet[7] = (0x01 << pos_id) | position_flag
                packet[11] = onoff_value2

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_thermostat_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool | float
    ) -> bytearray:
        """Create a packet for thermostat control"""
        packet = self.make_common_packet(0x28, 14, 0x12, timestamp)
        packet[5] = room_id & 0x0F
        
        if sub_type == SERVICE_SET_TEMPERATURE:
            value_int = int(value)
            value_float = value - value_int
            packet[7] = value_int & 0xFF
            if value_float != 0:
                packet[7] |= 0x40
        else:
            packet[6] = 0x01 if value else 0x02

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_gas_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool
    ) -> bytearray:
        """Create a packet for gas control"""
        packet = bytearray(
            [0x02, 0x31, 0x02, timestamp & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        )
        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_doorlock_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool
    ) -> bytearray:
        """Create a packet for doorlock control"""
        packet = bytearray(
            [0x02, 0x41, 0x02, timestamp & 0xFF, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]
        )
        packet[-1] = self.calculate_checksum(packet)
        return packet

    def make_fan_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool | int
    ) -> bytearray:
        """Create a packet for fan control"""
        packet = bytearray(
            [0x02, 0x61, 0x00, timestamp & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        )
        if sub_type == SERVICE_SET_PERCENTAGE:
            packet[2] = 0x03
            packet[6] = value
        elif sub_type == ATTR_PRESET_MODE:
            packet[2] = 0x07
            packet[5] = 0x10 if value else 0x00
        else:
            packet[2] = 0x01
            packet[5] = 0x01 if value else 0x00
            packet[6] = 0x01

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    @callback
    async def enqueue_command(self, device_id: str, value: Any, **kwargs: dict | None):
        """Enqueue a command for a device"""
        parts = device_id.split("_")
        device_type = parts[1]
        room_id = int(parts[2])
        pos_id = 0
        sub_type = None
        
        if kwargs:
            sub_type, value = next(iter(kwargs.items()))
        if len(parts) == 4 and not parts[3].isdigit():
            sub_type = parts[3]
        elif len(parts) == 4 and parts[3].isdigit():
            pos_id = int(parts[3])
        if len(parts) > 4:
            pos_id = int(parts[4])
            sub_type = parts[3]

        queue_task = {
            "send_retry": 1,
            "timestamp": self.timestamp,
            "device_type": device_type,
            "room_id": room_id,
            "pos_id": pos_id,
            "sub_type": sub_type,
            "value": value,
            "command_packet": None,
            "acknowledgment": None,
        }
        LOGGER.debug(f"Create queue task: {queue_task}")
        await self.queue.put(queue_task)
    
    def initial_device(self, device_id: str, sub_id: str | None, state: Any) -> dict:
        """Initialize a device"""
        device_type, device_room = device_id.split("_")
    
        did_suffix = f"_{sub_id}" if sub_id else ""
        device_id = f"{BRAND_PREFIX}_{device_id}{did_suffix}"
        if sub_id:
            sub_id_parts = sub_id.split("_")
            device_name = f"{device_type} {device_room} {' '.join(sub_id_parts)}".title()
        else:
            device_name = f"{device_type} {device_room}".title()
        
        if device_type not in ["energy"] and sub_id and not sub_id.isdigit():
            device_type = f"{device_type}:{''.join(filter(str.isalpha, sub_id))}"
        
        if device_type not in MAIN_DEVICES:
            uid_suffix = f"-{self.hub_id}"
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

    def make_common_packet(
        self,
        header: int,
        length: int,
        packet_type: int,
        timestamp: int,
    ) -> bytearray:
        """Create a common packet structure"""
        packet = bytearray([
            0x02, 
            header & 0xFF, 
            length & 0xFF, 
            packet_type & 0xFF, 
            timestamp & 0xFF
        ])
        packet.extend(bytearray([0] * (length - 5)))
        return packet

    def parse_thermostat(self, packet: bytearray) -> tuple[dict, int]:
        """Parse thermostat data from a packet"""
        room_id = packet[5] & 0x0F
        is_heating = bool(packet[6] & 0x01)
        target_temperature = (packet[7] & 0x3F) + (packet[7] & 0x40 > 0) * 0.5
        current_temperature = int.from_bytes(packet[8:10], byteorder="big") / 10.0
        hvac_mode = HVACMode.HEAT if is_heating else HVACMode.OFF

        thermostat_state = {
            ATTR_HVAC_MODE: hvac_mode,
            SERVICE_SET_TEMPERATURE: target_temperature,
            ATTR_CURRENT_TEMPERATURE: current_temperature
        }
        return room_id, thermostat_state
    
    def parse_gas(self, packet: bytearray) -> tuple[int, bool]:
        """Parse gas data from a packet"""
        room_id = 0
        gas_state = bool(packet[5])
        return room_id, gas_state
    
    def parse_doorlock(self, packet: bytearray) -> tuple[bool, int]:
        """Parse doorlock data from a packet"""
        room_id = 0
        doorlock_state = bool(packet[5] & 0xAE)
        return room_id, doorlock_state
    
    def parse_fan(self, packet: bytearray) -> tuple[dict, int]:
        """Parse fan data from a packet"""
        room_id = 0
        is_natural_ventilation = bool(packet[5] >> 4 & 1)
        preset_mode	= PRESET_NV if is_natural_ventilation else PRESET_NONE

        fan_state = {
            ATTR_STATE: bool(packet[5] & 0x01),
            WIND_SPEED: packet[6],
            "speed_list": [SPEED_INT_LOW, SPEED_INT_MEDIUM, SPEED_INT_HIGH],
            ATTR_PRESET_MODES: [PRESET_NV, PRESET_NONE],
            ATTR_PRESET_MODE: preset_mode,
        }
        return room_id, fan_state
    
    def parse_state_general(self, packet: bytearray) -> tuple[dict, int]:
        """Parse general state data from a packet"""
        state_general = {"light": {}, "outlet": {}}
        
        room_id = packet[5] & 0x0F
        if room_id == 1:
            iterations = (4, 3)
        else:
            iterations = (2, 2)

        for i in range(iterations[0]):
            light_state = bool(packet[6] & (0x01 << i))
            dc_value = int.from_bytes(packet[12:14], 'big') / 10.0
            state_general["light"][str(i)] = light_state
            state_general["light"][f"dcvalue"] = dc_value

        for i in range(iterations[1]): 
            idx = 14 + 2 * i
            idx2 = idx + 2

            if len(packet) > idx2:
                value = int.from_bytes(packet[idx:idx2], byteorder="big")
                power_cons = value / 10.
            else:
                power_cons = 0.
            
            if i < 2:
                idx = 8 + 2 * i
                idx2 = idx + 2

                cut_value = int.from_bytes(packet[idx:idx2], byteorder="big")
                state_general["outlet"][f"cutvalue_{str(i)}"] = cut_value / 10

            outlet_state = bool(packet[7] & (0x01 << i))
            standby_cut = bool(packet[7] >> 4 & 1)

            state_general["outlet"][str(i)] = outlet_state
            state_general["outlet"]["standbycut"] = standby_cut
            state_general["outlet"][f"powercons_{str(i)}"] = power_cons

        return room_id, state_general
    
    def parse_state_gen2(self, packet: bytearray) -> tuple[dict, int]:
        """Parse Gen2 state data from a packet"""
        state_gen2 = {"light": {}, "outlet": {}}
        room_id = packet[1] & 0x0F

        l_count = packet[10] if room_id % 2 else packet[10] & 0x0F
        o_count = packet[11]
        base_count = l_count if room_id % 2 else o_count

        l_idx = 18
        o_idx = l_idx + (base_count * 13)

        for i in range(l_count):
            brightness, color_temp = packet[l_idx + 1], packet[l_idx + 2]
            dc_value = int.from_bytes(packet[l_idx + 8:l_idx + 10], byteorder="big") / 10

            if brightness and color_temp:
                state_gen2["light"][str(i)] = {
                    ATTR_STATE: packet[l_idx] == 0x01,
                    COLOR_MODE_BRIGHTNESS: brightness,
                    COLOR_MODE_COLOR_TEMP: color_temp,
                }
                state_gen2["light"][f"dcvalue_{str(i)}"] = dc_value
            l_idx += 13

        for i in range(o_count):
            outlet_state = bool(packet[o_idx] & 0x01)
            standby_cut = bool(packet[o_idx] & 0x10)
            power_cons = int.from_bytes(packet[o_idx + 8:o_idx + 10], byteorder="big") / 10
            cut_value = int.from_bytes(packet[o_idx + 6:o_idx + 8], byteorder="big") / 10

            state_gen2["outlet"][str(i)] = outlet_state
            state_gen2["outlet"][f"standbycut_{str(i)}"] = standby_cut
            state_gen2["outlet"][f"powercons_{str(i)}"] = power_cons
            state_gen2["outlet"][f"cutvalue_{str(i)}"] = cut_value
            o_idx += 14

        return room_id, state_gen2

    def parse_state_aio(self, packet: bytearray) -> tuple[dict, int]:
        """Parse AIO state data from a packet"""
        state_aio = {"light": {}, "outlet": {}}
        room_id = packet[1] & 0x0F

        for i in range(packet[5]):
            light_state = bool(packet[6] & (1 << i))
            state_aio["light"][str(i)] = light_state

        for i in range(2):
            idx = 9 + 5 * i    # state
            idx2 = 10 + 5 * i  # consumption

            outlet_state = packet[idx] in [0x21, 0x11]
            standby_cut = packet[idx] in [0x11, 0x13, 0x12]
            power_cons = (packet[idx2] << 8 | packet[idx2 + 1]) / 10

            state_aio["outlet"][str(i)] = outlet_state
            state_aio["outlet"][f"standbycut_{str(i)}"] = standby_cut
            state_aio["outlet"][f"powercons_{str(i)}"] = power_cons

        return room_id, state_aio
    
    def parse_energy(self, packet: bytearray) -> dict:
        """Parse energy data from a packet"""
        index = 13
        energy_state = {}
        element_offset = 1 if self.gateway_type == "AIO" or len(packet) == 34 else 0

        if element_offset == 1:
            elements = ["electric", "water", "gas"] 
        else:
            elements = ["electric", "water", "hotwater", "gas", "heat"]

        for element in elements:
            total_value = float(packet[ENERGY_BYTE_RANGE[element][element_offset]].hex())
            realtime_value = int(packet[index:index + 2].hex())

            energy_state[element] = {"total": total_value, "realtime": realtime_value}
            index += 8

        return energy_state

    def validate_response(self, packet: bytes, queue: dict):
        """Validate the response packet against the queued command"""
        general_gateway = self.gateway_type == "General"
        command_packet = queue["command_packet"]
        header_byte = command_packet[1]

        offset = 2 if general_gateway and len(command_packet) == 10 else 3
        command_4bit = 0x9 if not general_gateway or header_byte == 0x28 else 0x8

        overview = (command_4bit << 4) | (command_packet[offset] & 0x0F)
        packet_value = packet[offset]

        if header_byte == packet[1] and (
            overview == packet_value or packet_value == 0x81
        ):
            queue["acknowledgment"] = packet

    async def send_packet_queue(self, queue: dict):
        """Send a packet from the queue"""
        command_packet = getattr(self, f"make_{queue['device_type']}_packet", None)(
            queue["timestamp"],
            queue["room_id"],
            queue["pos_id"],
            queue["sub_type"],
            queue["value"]
        )
        if command_packet is None:
            LOGGER.error("No packet maker for device '%s'", queue["device_type"])
            return
        queue["command_packet"] = command_packet

        LOGGER.info(
            "Sending '%s' to '%s' (Packet: %s, Attempts: %d)",
            queue["value"], queue["device_type"], queue["command_packet"].hex(), queue["send_retry"]
        )
        queue["send_retry"] += 1
        queue["timestamp"] += 1
        await self.send_data(queue["command_packet"])

    def handle_device_packet(self, packet: bytes):
        """Handle a device packet"""
        packet_len = len(packet)
        header = packet[1]
        command = packet[2] if packet_len == 10 else packet[3]
        room_id = device_state = device_id = None
        
        if packet_len >= 20 or packet_len in [7, 8]:
            self.timestamp = packet[4]
        elif packet_len == 10:
            self.timestamp = packet[3]

        if packet_len != 10 and command in [0x81, 0x82, 0x91, 0x92, 0xB2]:
            if header == 0x28:
                room_id, device_state = self.parse_thermostat(packet)
                device_id = f"thermostat_{room_id}"
                self.set_device(device_id, device_state)
            elif (
                (self.gateway_type == "General" and packet_len == 30) or
                (self.gateway_type == "AIO" and packet_len in [20, 22]) or
                (self.gateway_type == "Gen2" and packet_len in [59, 72, 98, 150])
            ):
                room_id, device_state = getattr(
                    self, f"parse_state_{self.gateway_type}".lower()
                )(packet)
                for device, state in device_state.items():
                    device_id = f"{device}_{room_id}"
                    self.set_device(device_id, state, is_sub=True)
            elif header == 0xD1:
                device_state = self.parse_energy(packet)
                for room_id, state in device_state.items():
                    device_id = f"energy_{room_id}"
                    self.set_device(device_id, state, is_sub=True)
        elif packet_len == 10 and command != 0x00:
            parser_mapping = {
                0x31: (self.parse_gas, "gas"),
                0x41: (self.parse_doorlock, "doorlock"),
                0x61: (self.parse_fan, "fan"),
            }
            if header in parser_mapping:
                parse_func, device_type = parser_mapping[header]
                room_id, device_state = parse_func(packet)
                device_id = f"{device_type}_{room_id}"
                self.set_device(device_id, device_state)
        elif command not in [0x00, 0x11, 0x21, 0xA1]:
            pass
            #LOGGER.warning(f"Unknown device packet: {packet.hex()}")
    
    async def handle_packet_queue(self, queue: dict):
        """Handle a packet from the queue"""
        await self.send_packet_queue(queue)
        acknowledgment = queue["acknowledgment"]
        send_retry = queue["send_retry"]
        max_retry = self.entry.options.get("max_send_retry", DEFAULT_MAX_SEND_RETRY)

        if acknowledgment:
            LOGGER.info(
                "%s: Success (ACK: %s, Attempts: %d)",
                queue["device_type"], acknowledgment.hex(), queue["send_retry"]
            )
            await self.queue.delete()
        elif send_retry > max_retry:
            LOGGER.warning(
                "%s: Failed after %d attempts", queue["device_type"], max_retry
            )
            await self.queue.delete()

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
                self.log_packet_viewer(received_data, checksum_valid)

                if checksum_valid:
                    self.handle_device_packet(received_data)

                    if await self.queue.size() > 0:
                        queue_item = await self.queue.get()
                        self.validate_response(received_data, queue_item)
            except Exception as ex:
                LOGGER.error(f"Failed to process incoming data: {ex}", exc_info=True)

    def log_packet_viewer(self, data: bytes, checksum_valid: bool):
        """Log packet data for debugging"""
        if self.entry.options.get("packet_viewer", DEFAULT_PACKET_VIEWER):
            checksum_status = "valid" if checksum_valid else "invalid"
            formatted_data = ' '.join(f'{byte:02X}' for byte in data)
            LOGGER.debug("Packet viewer - Data: %s | Checksum: %s", formatted_data, checksum_status)

    async def process_queue_data(self):
        """Process data in the queue"""
        while True:
            try:
                if await self.queue.size() > 0:
                    queue_item = await self.queue.get()
                    await self.handle_packet_queue(queue_item)
                else:
                    await asyncio.sleep(0.1)
            except Exception as ex:
                LOGGER.error(f"Failed to process task queue: {ex}", exc_info=True)
