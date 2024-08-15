import re
import asyncio
import traceback
from typing import Any, Optional, Callable

from homeassistant.components.climate import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    LOGGER,
    DEFAULT_MAX_TRANSMISSION,
    DEFAULT_PACKET_VIEWER,
    PRESET_NATURAL_VENTILATION,
    PRESET_NONE,
    ELEMENT_BYTE_RANGE,
    DEVICE_TYPE_MAP,
    DEVICE_PLATFORM_MAP,
    SPEED_INT_LOW,
    SPEED_INT_MEDIUM,
    SPEED_INT_HIGH,
    Device,
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
        entities: dict,
        hub_id: str, 
        communicator,
        async_add_device: Callable,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.entities = entities
        self.hub_id = hub_id
        self.communicator = communicator
        self.async_add_device = async_add_device
        self.gateway_type: str = entry.data["gateway_mode"][0]
        self.room_to_command: dict[bytes] = entry.data["gateway_mode"][1]
        
        self.devices: dict = {}
        self.stop_event: asyncio.Event = asyncio.Event()
        self.queue: AsyncQueue = AsyncQueue()
        self.tasks: list = []

    async def start(self) -> None:
        """Start main loop with asyncio."""
        self.stop_event.clear()
        await asyncio.sleep(1)
        self.tasks.append(asyncio.create_task(self.process_incoming_data()))

    async def stop(self) -> None:
        """Stop main loop and cancel all tasks."""
        self.stop_event.set()
        for task in self.tasks:
            task.cancel()

    @property
    def is_alive(self) -> bool:
        """Check if the communicator is alive"""
        return self.communicator.is_connected()
    
    async def receive_data(self) -> bytes:
        """Receive data from communicator."""
        if self.is_alive:
            return await self.communicator.receive()

    async def send_data(self, packet: bytearray) -> None:
        """Send packet data to the communicator."""
        if self.is_alive:
            await self.communicator.send(packet)

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

    def convert_unique_id(self, unique_id: str) -> tuple[str, Optional[str]]:
        """Convert device_id, sub_id from unique_id."""
        parts = unique_id.split("-")[0].split("_")
        if len(parts) > 3:
            sub_id = "_".join(parts[3:])
            device_id = "_".join(parts[1:3])
        else:
            sub_id = None
            device_id = "_".join(parts[1:3])

        return device_id, sub_id

    def get_devices_from_domain(self, domain: str) -> list[dict]:
        """Retrieve devices associated with a specific domain."""
        entity_list = self.entities.get(domain, [])
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
    async def on_command(self, unique_id: str, value: Any, **kwargs: Optional[dict]):
        """Queue a command for the device identified by unique_id."""
        parts = unique_id.split("-")[0].split("_")    
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
            "transmission": 1,
            "timestamp": self.timestamp,
            "device_type": device_type,
            "room_id": room_id,
            "pos_id": pos_id,
            "sub_type": sub_type,
            "value": value,
            "command": getattr(self, f"make_{device_type}_packet"),
            "response": None,
        }
        LOGGER.debug(f"Create queue task: {queue_task}")
        await self.queue.put(queue_task)
    
    def initialize_device(self, device_id: str, sub_id: Optional[str], state: Any) -> dict:
        """Initialize devices using a unique_id derived from device_id and sub_id."""
        device_type, device_room = device_id.split("_")
        
        base_unique_id = f"bestin_{device_id}"
        unique_id = f"{base_unique_id}_{sub_id}" if sub_id else base_unique_id
        full_unique_id = f"{unique_id}-{self.hub_id}"
        
        if device_type != "energy" and sub_id and not sub_id.isdigit():
            letter_sub_id = ''.join(filter(str.isalpha, sub_id))
            device_type = f"{device_type}:{letter_sub_id}"
        
        platform = DEVICE_PLATFORM_MAP.get(device_type)
        if not platform:
            raise ValueError(f"Unsupported platform type for device: {device_type}")

        if full_unique_id not in self.devices:
            device_info = DeviceInfo(
                id=full_unique_id,
                type=device_type,
                name=unique_id,
                room=device_room,
                state=state,
            )
            device = Device(
                info=device_info,
                platform=platform,
                on_command=self.on_command,
                callbacks=set()
            )
            self.devices[full_unique_id] = device

        return self.devices[full_unique_id]
    
    def setup_device(self, device_id: str, state: Any, is_sub=False) -> None:
        """Set up device with specified state."""        
        device_type = device_id.split("_")[0]
        if device_type not in DEVICE_TYPE_MAP:
            raise ValueError(f"Unsupported device type: {device_type}")
        
        final_states = state.items() if is_sub else [(None, state)]
        for sub_id, sub_state in final_states:
            device = self.initialize_device(device_id, sub_id, sub_state)

            if device_type != "energy" and sub_id and not sub_id.isdigit():
                letter_sub_id = ''.join(filter(str.isalpha, sub_id))
                device_key = f"{device_type}:{letter_sub_id}"
                _device_type = DEVICE_TYPE_MAP[device_key]
            else:
                _device_type = DEVICE_TYPE_MAP[device_type]
            self.async_add_device(_device_type, device)

            if device.info.state != sub_state:
                device.info.state = sub_state
                for callback in device.callbacks:
                    assert callable(callback), "Callback should be callable"
                    callback()

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
            iterations = 4, 3
        else:
            iterations = 2, 2

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
        element_offset = 1 if self.gateway_type == "AIO" else 0

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
            command = queue["command"](
                queue["timestamp"], queue["room_id"], queue["pos_id"], queue["sub_type"], queue["value"]
            )
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
            queue["timestamp"] += 1
            command = queue["command"](
                queue["timestamp"], queue["room_id"], queue["pos_id"], queue["sub_type"], queue["value"]
            )

            LOGGER.info(
                "Sending %s command for %s device. Command Packet: %s, attempts: %d",
                queue["value"], queue["device_type"], command.hex(), queue["transmission"]
            )
            queue["transmission"] += 1
            await self.send_data(command)
        except Exception as e:
            LOGGER.error("Error in send_packet_queue: %s", e)

    def handle_device_packet(self, packet: bytes) -> None:
        """Parse and process an incoming device packet."""
        header = packet[1]
        packet_len = len(packet)
        room_id = device_state = device_id = None
        self.timestamp = 0x00

        if packet_len == 10:
            command = packet[2]
            #self.timestamp = packet[3]
        else:
            command = packet[3]
            #self.timestamp = packet[4]

        if packet_len != 10 and command in [0x81, 0x82, 0x91, 0x92, 0xB2]:
            if header == 0x28:
                room_id, device_state = self.parse_thermostat(packet)
                device_id = f"thermostat_{room_id}"
                self.setup_device(device_id, device_state)
            elif header == 0x31 or packet_len in [20, 22]:
                room_id, device_state = getattr(self, f"parse_state_{self.gateway_type}")(packet)
                for device, state in device_state.items():
                    device_id = f"{device}_{room_id}"
                    self.setup_device(device_id, state, is_sub=True)
            elif header == 0xD1:
                device_state = self.parse_energy(packet)
                for room_id, state in device_state.items():
                    device_id = f"energy_{room_id}"
                    self.setup_device(device_id, state, is_sub=True)

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
                self.setup_device(device_id, device_state)

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
        try:
            while True:
                if self.is_alive:
                    received_data = await self.receive_data()
                else:
                    received_data = None
                if received_data and self.verify_checksum(received_data):
                    if self.entry.options.get("packet_viewer", DEFAULT_PACKET_VIEWER):
                        LOGGER.debug("Received data: %s", received_data)
                    self.handle_device_packet(received_data)

                    if await self.queue.size() > 0:
                        queue_item = await self.queue.get()
                        await self.handle_packet_queue(queue_item)
                        self.check_command_response_packet(received_data, queue_item)
        except Exception as e:
            LOGGER.error("Error in process_incoming_data: %s", e)
