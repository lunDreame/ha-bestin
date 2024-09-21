import asyncio
from typing import Any, Callable

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    LOGGER,
    DEFAULT_MAX_TRANSMISSION,
    DEFAULT_PACKET_VIEWER,
    BRAND_PREFIX,
    PRESET_NATURAL_VENTILATION,
    PRESET_NONE,
    ELEMENT_BYTE_RANGE,
    MAIN_DEVICES,
    SIGNAL_MAP,
    DOMAIN_MAP,
    SPEED_INT_LOW,
    SPEED_INT_MEDIUM,
    SPEED_INT_HIGH,
    DeviceProfile,
    DeviceInfo,
)


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
    """Bestin Controller Class."""

    def __init__(
        self, 
        hass: HomeAssistant,
        entry: ConfigEntry,
        entity_groups,
        hub_id, 
        connection,
        add_device_callback: Callable,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.entity_groups = entity_groups
        self.hub_id = hub_id
        self.connection = connection
        self.add_device_callback = add_device_callback
        self.gateway_type: str = entry.data["gateway_mode"][0]
        self.room_to_command: dict[bytes] = entry.data["gateway_mode"][1]
        
        self.devices: dict = {}
        self.stop_event: asyncio.Event = asyncio.Event()
        self.queue: AsyncQueue = AsyncQueue()
        self.tasks: list = []

    async def start(self) -> None:
        """Start main loop with asyncio."""
        self.tasks.append(asyncio.create_task(self.process_incoming_data()))
        self.tasks.append(asyncio.create_task(self.process_queue_data()))
        await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop main loop and cancel all tasks."""
        for task in self.tasks:
            task.cancel()

    @property
    def is_alive(self) -> bool:
        """Check if the connection is alive"""
        return self.connection.is_connected()
    
    async def receive_data(self) -> bytes:
        """Receive data from connection."""
        if self.is_alive:
            return await self.connection.receive()

    async def send_data(self, packet: bytearray) -> None:
        """Send packet data to the connection."""
        if self.is_alive:
            await self.connection.send(packet)

    def calculate_checksum(self, packet: bytearray) -> int:
        """Compute checksum from packet data."""
        checksum = 3
        for i in range(len(packet) - 1):
            checksum ^= packet[i]
            checksum = (checksum + 1) & 0xFF
        return checksum
    
    def verify_checksum(self, packet: bytes) -> bool:
        """Checksum verification of packet data."""
        if len(packet) < 6:
            return False
        
        checksum = 3
        for byte in packet[:-1]:
            checksum ^= byte
            checksum = (checksum + 1) & 0xFF
        return checksum == packet[-1]

    def get_devices_from_domain(self, domain: str) -> list[dict]:
        """Retrieve devices associated with a specific domain."""
        entity_list = self.entity_groups.get(domain, [])
        return [self.devices.get(uid, {}) for uid in entity_list]

    def make_light_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool
    ) -> bytearray:
        """Create a light control packet."""
        aio_gateway = self.gateway_type == "AIO"
        onoff_value = 0x01 if value else 0x00
        onoff_value2 = 0x04 if value else 0x00
        position_flag = 0x80 if value else 0x00
        
        if aio_gateway:
            room_id_conv = 0x50 + room_id
            packet = self.make_common_packet(room_id_conv, 0x0A, 0x12, timestamp)
            packet[5] = onoff_value
            packet[6] = 10 if pos_id == 4 else 1 << pos_id
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
        """Create an outlet control packet."""
        aio_gateway = self.gateway_type == "AIO"
        onoff_value = 0x01 if value else 0x02
        onoff_value2 = (0x09 << pos_id) if value else 0x00
        position_flag = 0x80 if value else 0x00

        if aio_gateway:
            room_id_conv = 0x50 + room_id 
            packet = self.make_common_packet(room_id_conv, 0x0C, 0x12, timestamp)
        else:
            packet = self.make_common_packet(0x31, 0x0D, 0x01, timestamp)
            packet[5] = room_id & 0x0F

        if aio_gateway:
            packet[8] = 0x01
            packet[9] = (pos_id + 1) & 0x0F
            packet[10] = onoff_value >> (onoff_value + 3) if sub_type else onoff_value
        else:
            if sub_type == "cutoff":
                packet[8] = 0x83 if value else 0x03
            else:
                packet[7] = (0x01 << pos_id) | position_flag
                packet[11] = onoff_value2

        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_thermostat_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool | float
    ) -> bytearray:
        """Create an thermostat control packet."""
        packet = self.make_common_packet(0x28, 14, 0x12, timestamp)
        packet[5] = room_id & 0x0F
        
        if sub_type == "set_temperature":
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
        """Create an gas control packet."""
        packet = bytearray(
            [0x02, 0x31, 0x02, timestamp & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        )
        packet[-1] = self.calculate_checksum(packet)
        return packet
    
    def make_doorlock_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool
    ) -> bytearray:
        """Create an doorlock control packet."""
        packet = bytearray(
            [0x02, 0x41, 0x02, timestamp & 0xFF, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]
        )
        packet[-1] = self.calculate_checksum(packet)
        return packet

    def make_fan_packet(
        self, timestamp: int, room_id: int, pos_id: int, sub_type: str, value: bool | int
    ) -> bytearray:
        """Create an fan control packet."""
        packet = bytearray(
            [0x02, 0x61, 0x00, timestamp & 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        )
        if sub_type == "speed":
            packet[2] = 0x03
            packet[6] = value
        elif sub_type == "preset":
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
        """Queue a command for the device identified by device_id."""
        parts = device_id.split("_")
        device_type = parts[1]
        room_id = int(parts[2])
        pos_id = 0
        sub_type = None
        timestamp = 0
        
        if kwargs:
            sub_type, value = next(iter(kwargs.items()))
        if len(parts) == 4 and not parts[3].isdigit():
            sub_type = parts[3]
        elif len(parts) == 4 and parts[3].isdigit():
            pos_id = int(parts[3])    
        if len(parts) > 4:
            pos_id = int(parts[4])
            sub_type = parts[3]

        def coomand_func():
            packet_func = getattr(self, f"make_{device_type}_packet", None)
            if packet_func is None:
                LOGGER.error(f"Unknown 'make_{device_type}_packet' method")
                return None

            nonlocal timestamp
            if device_type in ["gas", "fan", "doorlock"]:
                timestamp = self.timestamp2
            else:
                timestamp = self.timestamp
            timestamp += 1
            return packet_func(timestamp, room_id, pos_id, sub_type, value)
        
        queue_task = {
            "transmission": 1,
            "timestamp": timestamp,
            "device_type": device_type,
            "room_id": room_id,
            "pos_id": pos_id,
            "sub_type": sub_type,
            "value": value,
            "command": coomand_func,
            "response": None,
        }
        LOGGER.debug(f"Create queue task: {queue_task}")
        await self.queue.put(queue_task)
    
    def initial_device(self, device_id: str, sub_id: str | None, state: Any) -> dict:
        """Initialize a device and add it to the devices list."""
        device_type, device_room = device_id.split("_")
    
        did_suffix = f"_{sub_id}" if sub_id else ""
        device_id = f"{BRAND_PREFIX}_{device_id}{did_suffix}"
        if sub_id:
            sub_id_parts = sub_id.split("_")
            device_name = f"{device_type} {device_room} {' '.join(sub_id_parts)}".title()
        else:
            device_name = f"{device_type} {device_room}".title()

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
                domain=DOMAIN_MAP[device_type],
                unique_id=unique_id,
                info=device_info,
            )
        return self.devices[device_id]
    
    def set_device(self, device_id: str, state: Any, is_sub: bool = False) -> None:
        """Set up device with specified state."""
        device_type, device_room = device_id.split("_")

        if device_type not in DOMAIN_MAP:
            raise ValueError(f"Unsupported device type: {device_type}")
        
        sub_states = state.items() if is_sub else [(None, state)]
        for sub_id, sub_state in sub_states:
            device = self.initial_device(device_id, sub_id, sub_state)

            if device_type != "energy" and sub_id and not sub_id.isdigit():
                letter_sub_id = ''.join(filter(str.isalpha, sub_id))
                letter_device_type = f"{device_type}:{letter_sub_id}"
                domain = DOMAIN_MAP[letter_device_type]
            else:
                domain = DOMAIN_MAP[device_type]
            signal = SIGNAL_MAP[domain]
            
            device_uid = device.unique_id
            device_info = device.info
            if device_uid not in self.entity_groups.get(domain, set()):
                self.add_device_callback(signal, device)

            if device_info.state != sub_state:
                device_info.state = sub_state
                device.update_callbacks()

    def make_common_packet(
        self,
        header: int, # In case of AIO gateway, room_id is assigned
        length: int,
        packet_type: int,
        timestamp: int,
    ) -> bytearray:
        """Create a base structure for common packets."""
        packet = bytearray([
            0x02, 
            header & 0xFF, 
            length & 0xFF, 
            packet_type & 0xFF, 
            timestamp & 0xFF
        ])
        packet.extend(bytearray([0] * (length - 5)))
        return packet

    def parse_thermostat(self, packet: bytearray) -> tuple[int, dict]:
        """Thermostat parse from packet data."""
        room_id = packet[5] & 0x0F
        is_heating = bool(packet[6] & 0x01)
        target_temperature = (packet[7] & 0x3F) + (packet[7] & 0x40 > 0) * 0.5
        current_temperature = int.from_bytes(packet[8:10], byteorder="big") / 10.0
        hvac_mode = HVACMode.HEAT if is_heating else HVACMode.OFF

        thermostat_state = {
            "hvac_mode": hvac_mode,
            "target_temperature": target_temperature,
            "current_temperature": current_temperature
        }
        return room_id, thermostat_state
    
    def parse_gas(self, packet: bytearray) -> tuple[int, bool]:
        """Gas parse from packet data."""
        room_id = 0
        gas_state = bool(packet[5])
        return room_id, gas_state
    
    def parse_doorlock(self, packet: bytearray) -> tuple[int, bool]:
        """Doorlock parse from packet data."""
        room_id = 0
        doorlock_state = bool(packet[5] & 0xAE)
        return room_id, doorlock_state
    
    def parse_fan(self, packet: bytearray) -> tuple[int, dict]:
        """Fan parse from packet data."""
        room_id = 0
        is_natural_ventilation = bool(packet[5] >> 4 & 1)
        preset_mode	= PRESET_NATURAL_VENTILATION if is_natural_ventilation else PRESET_NONE

        fan_state = {
            "is_on": bool(packet[5] & 0x01),
            "speed": packet[6],
            "speed_list": [SPEED_INT_LOW, SPEED_INT_MEDIUM, SPEED_INT_HIGH],
            "preset_modes": [PRESET_NATURAL_VENTILATION, PRESET_NONE],
            "preset_mode": preset_mode,
        }
        return room_id, fan_state
    
    def parse_state_General(self, packet: bytearray) -> tuple[int, dict]:
        """Energy state General-gateway parse from packet data."""
        state_general = {"light": {}, "outlet": {}}
        room_id = packet[5] & 0x0F
        if room_id == 1:
            iterations = (4, 3)
        else:
            iterations = (2, 2)

        for i in range(iterations[0]):
            light_state = bool(packet[6] & (0x01 << i))
            state_general["light"][str(i)] = light_state

        for i in range(iterations[1]): 
            idx = 14 + 2 * i
            idx2 = idx + 2

            if len(packet) > idx2:
                value = int.from_bytes(packet[idx:idx2], byteorder="big")
                consumption = value / 10.
            else:
                consumption = 0.

            outlet_state = bool(packet[7] & (0x01 << i))
            outlet_cutoff = bool(packet[7] >> 4 & 1)

            state_general["outlet"][str(i)] = outlet_state
            state_general["outlet"]["cutoff"] = outlet_cutoff
            state_general["outlet"][f"consumption_{str(i)}"] = consumption

        return room_id, state_general
    
    def parse_state_Gen2(self, packet: bytearray) -> tuple[int, dict]:
        """Energy state Gen2-gateway parse from packet data."""
        state_gen2 = {"light": {}, "outlet": {}}

        room_id = packet[1] & 0x0F
        if room_id % 2 == 0:
            lcnt, ocnt = packet[10] & 0x0F, packet[11]
            base_cnt = ocnt
        else:
            lcnt, ocnt = packet[10], packet[11]
            base_cnt = lcnt

        lsidx = 18
        osidx = lsidx + (base_cnt * 13)

        for i in range(lcnt):
            light_state = {
                "is_on": packet[lsidx] == 0x01,
                "brightness": packet[lsidx + 1],
                "color_temp": packet[lsidx + 2],
            }
            state_gen2["light"][str(i)] = light_state
            lsidx += 13

        for i in range(ocnt): 
            idx = osidx + 8
            idx2 = osidx + 10

            outlet_state = bool(packet[osidx] & 0x01)
            outlet_cutoff = bool(packet[osidx] & 0x10)
            outlet_consumption = int.from_bytes(packet[idx:idx2], byteorder="big") / 10

            state_gen2["outlet"][str(i)] = outlet_state
            state_gen2["outlet"][f"cutoff_{str(i)}"] = outlet_cutoff
            state_gen2["outlet"][f"consumption_{str(i)}"] = outlet_consumption
            osidx += 14

        return room_id, state_gen2

    def parse_state_AIO(self, packet: bytearray) -> tuple[int, dict]:
        """Energy state AIO(all-in-one)-gateway parse from packet data."""
        state_aio = {"light": {}, "outlet": {}}
        room_id = packet[1] & 0x0F

        for i in range(packet[5]):
            light_state = bool(packet[6] & (1 << i))
            state_aio["light"][str(i)] = light_state

        for i in range(2):
            idx = 9 + 5 * i  # state
            idx2 = 10 + 5 * i  # consumption

            outlet_state = packet[idx] in [0x21, 0x11]
            outlet_cutoff = packet[idx] in [0x11, 0x13, 0x12]
            outlet_consumption = (packet[idx2] << 8 | packet[idx2 + 1]) / 10

            state_aio["outlet"][str(i)] = outlet_state
            state_aio["outlet"][f"cutoff_{str(i)}"] = outlet_cutoff
            state_aio["outlet"][f"consumption_{str(i)}"] = outlet_consumption

        return room_id, state_aio
    
    def parse_energy(self, packet: bytearray) -> dict:
        """Energy parse from packet data."""
        index = 13
        energy_state = {}
        element_offset = 1 if self.gateway_type == "AIO" or len(packet) == 34 else 0

        if element_offset == 1:
            elements = ["electric", "water", "gas"] 
        else:
            elements = ["electric", "water", "hotwater", "gas", "heat"]

        for element in elements:
            total_value = float(packet[ELEMENT_BYTE_RANGE[element][element_offset]].hex())
            realtime_value = int(packet[index:index + 2].hex())

            energy_state[element] = {"total": total_value, "realtime": realtime_value}
            index += 8

        return energy_state

    def check_command_response_packet(self, packet: bytes, queue: dict) -> None:
        """Check the response packet after the command."""
        try:
            general_gateway = self.gateway_type == "General"
            command = queue["command"]()
            header_byte = command[1]

            offset = 2 if general_gateway and len(command) == 10 else 3
            command_4bit = 0x9 if not general_gateway or header_byte == 0x28 else 0x8

            overview = (command_4bit << 4) | (command[offset] & 0x0F)  # Line 0-3
            packet_value = packet[offset]

            if header_byte == packet[1] and (overview == packet_value or packet_value == 0x81):
                queue["response"] = packet
        except Exception as e:
            LOGGER.error("Error in check_command_response_packet: %s", e)

    async def send_packet_queue(self, queue: dict) -> None:
        """Sends queued command packet data."""
        try:
            if (command := queue["command"]) is None:
                return
            
            LOGGER.info(
                "Sending %s command for %s device. Command Packet: %s, attempts: %d",
                queue["value"], queue["device_type"], command().hex(), queue["transmission"]
            )
            queue["transmission"] += 1
            await self.send_data(command())
        except Exception as e:
            LOGGER.error("Error in send_packet_queue: %s", e)

    def handle_device_packet(self, packet: bytes) -> None:
        """Parse and process an incoming device packet."""
        packet_len = len(packet)
        header = packet[1]
        command = packet[2] if packet_len == 10 else packet[3]
        room_id = device_state = device_id = None
        self.timestamp = self.timestamp2 = 0
        
        if packet_len >= 20 or packet_len in [7, 8]:
            # energy
            self.timestamp = packet[4]
        elif packet_len == 10:
            # control
            self.timestamp2 = packet[3]
        #LOGGER.debug(f"timestamp: {self.timestamp}, timestamp2: {self.timestamp2}")

        if packet_len != 10 and command in [0x81, 0x82, 0x91, 0x92, 0xB2]:  # response
            if header == 0x28:
                room_id, device_state = self.parse_thermostat(packet)
                device_id = f"thermostat_{room_id}"
                self.set_device(device_id, device_state)
            elif ((self.gateway_type == "General" and packet_len == 30)
                or (self.gateway_type == "AIO" and packet_len in [20, 22])
                or (self.gateway_type == "Gen2" and packet_len in [59, 72, 98])
            ):
                room_id, device_state = getattr(self, f"parse_state_{self.gateway_type}")(packet)
                for device, state in device_state.items():
                    device_id = f"{device}_{room_id}"
                    self.set_device(device_id, state, is_sub=True)
            elif header == 0xD1:
                device_state = self.parse_energy(packet)
                for room_id, state in device_state.items():
                    device_id = f"energy_{room_id}"
                    self.set_device(device_id, state, is_sub=True)
        elif packet_len == 10 and command != 0x00:  # response
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
        elif command not in [0x00, 0x11, 0x21, 0xA1]:  # query
            pass
            #LOGGER.warning(f"Unknown device packet: {packet.hex()}")
    
    async def handle_packet_queue(self, queue: dict) -> None:
        """Processes the queued command packet data."""
        try:
            await self.send_packet_queue(queue)
            max_transmission = self.entry.options.get("max_transmission", DEFAULT_MAX_TRANSMISSION)

            if response := queue["response"]:
                LOGGER.info(
                    "Device: %s, Value: %s - Command successful. Response: %s, Attempts: %d",
                    queue["device_type"], queue["value"], response.hex(), queue["transmission"]
                )
                await self.queue.delete()
            elif queue["transmission"] > max_transmission:
                LOGGER.warning(
                    "Device: %s - Command failed after %d attempts. Operation cancelled.",
                    queue["device_type"], max_transmission
                )
                await self.queue.delete()
        except Exception as e:
            LOGGER.error("Error in handle_packet_queue: %s", e)

    async def process_incoming_data(self) -> None:
        """Handles incoming data, processes it if valid, and manages a task queue."""
        while True:
            if not self.is_alive:
                await asyncio.sleep(0.1)
                continue

            try:
                received_data = await self.receive_data()
                if received_data and self.verify_checksum(received_data):
                    if self.entry.options.get("packet_viewer", DEFAULT_PACKET_VIEWER):
                        LOGGER.debug(
                            "Packet viewer: %s",
                            ' '.join(f'{byte:02X}' for byte in received_data)
                        )
                    self.handle_device_packet(received_data)
                    
                    if await self.queue.size() > 0:
                        queue_item = await self.queue.get()
                        self.check_command_response_packet(received_data, queue_item)
            except Exception as e:
                LOGGER.error(f"Error in process_incoming_data: {e}")

    async def process_queue_data(self) -> None:
        """Processes items in the task queue."""
        while True:
            try:
                if await self.queue.size() > 0:
                    queue_item = await self.queue.get()
                    await self.handle_packet_queue(queue_item)
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                LOGGER.error(f"Error in process_queue_data: {e}")
