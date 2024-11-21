from enum import StrEnum
from dataclasses import dataclass

import re
import socket
import time
import logging
from typing import Any
import serial # type: ignore

logging.basicConfig(
    filename=None,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class Communicator:
    def __init__(self, conn_str):
        self.conn_str = conn_str
        self.is_serial = False
        self.is_socket = False
        self.connection = None
        self.reconnect_attempts = 0
        self.last_reconnect_attempt = None
        self.next_attempt_time = None

        self.chunk_size = 1024
        self._parse_conn_str()

    def _parse_conn_str(self):
        if re.match(r'COM\d+|/dev/tty\w+', self.conn_str):
            self.is_serial = True
        elif re.match(r'\d+\.\d+\.\d+\.\d+:\d+', self.conn_str):
            self.is_socket = True
        else:
            raise ValueError("Invalid connection string")

    def connect(self):
        try:
            if self.is_serial:
                self._connect_serial()
            elif self.is_socket:
                self._connect_socket()
            self.reconnect_attempts = 0
            logging.info("Connection established successfully.")
        except Exception as e:
            logging.error(f"Connection failed: {e}")
            self.reconnect()

    def _connect_serial(self):
        self.connection = serial.Serial(self.conn_str, baudrate=9600, timeout=30) # type: ignore
        logging.info(f"Serial connection established on {self.conn_str}")

    def _connect_socket(self):
        host, port = self.conn_str.split(':')
        self.connection = socket.socket()
        self.connection.settimeout(10)
        self.connection.connect((host, int(port)))
        logging.info(f"Socket connection established to {host}:{port}")

    def is_connected(self):
        try:
            if self.is_serial:
                return self.connection.is_open
            elif self.is_socket:
                return self.connection is not None
        except socket.error:
            return False

    def reconnect(self):
        self.connection = None

        current_time = time.time()
        if self.next_attempt_time and current_time < self.next_attempt_time:
            return
        
        self.reconnect_attempts += 1
        delay = min(2 ** self.reconnect_attempts, 60) if self.last_reconnect_attempt else 1
        self.last_reconnect_attempt = current_time
        self.next_attempt_time = current_time + delay
        logging.info(f"Reconnection attempt {self.reconnect_attempts} after {delay} seconds delay...")

        self.connect()
        if self.is_connected():
            logging.info(f"Successfully reconnected on attempt {self.reconnect_attempts}.")
            self.reconnect_attempts = 0
            self.next_attempt_time = None

    def send(self, data):
        try:
            if self.is_serial:
                self.connection.write(data)
            elif self.is_socket:
                self.connection.send(data)
        except Exception as e:
            logging.error(f"Failed to send packet data: {e}")
            self.reconnect()

    def receive(self):
        try:
            if self.is_serial:
                return self.connection.read(self.chunk_size)
            elif self.is_socket:
                return self.connection.recv(self.chunk_size)
        except Exception as e:
            logging.error(f"Failed to receive packet data: {e}")
            self.reconnect()
            return None

    def close(self):
        if self.connection:
            logging.info("Connection closed.")
            self.connection.close()
            self.connection = None


class DeviceType(StrEnum):
    """Enum for device types."""
    THERMOSTAT = "thermostat"
    GEC = "gas/ec"
    EC = "ec"
    FAN = "fan"
    GAS = "gas"
    ELEVATOR = "elevator"
    ENERGY = "energy"
    IGNORE = "ignore"

class PacketType(StrEnum):
    """Enum for packet types."""
    QUERY = "query"
    RES = "res"
    ACK = "ack"

class EnergyType(StrEnum):
    """Enum for energy types."""
    ELECTRIC = "electric"
    WATER = "water"
    HOTWATER = "hotwater"
    GAS = "gas"
    HEAT = "heat"

INT_TO_ENERGY_TYPE = {
    0x1: EnergyType.ELECTRIC,
    0x2: EnergyType.WATER,
    0x3: EnergyType.HOTWATER,
    0x4: EnergyType.GAS,
    0x5: EnergyType.HEAT
}

@dataclass
class Packet:
    """Class to represent a packet."""
    device_type: DeviceType
    packet_type: PacketType
    seq_number: int
    data: bytes
    is_valid: bool
    
    def __str__(self) -> str:
        """Return a string representation of the packet."""
        return f"Device: {self.device_type}, Type: {self.packet_type}, Seq: {self.seq_number}, Data: {self.data}, Valid: {self.is_valid}"

@dataclass
class DevicePacket:
    """Class to represent a device packet."""
    trans_key: str
    room_id: int | str
    sub_id: str | None
    device_state: Any

    def __str__(self) -> str:
        """Return a string representation of the device packet."""
        return f"Key: {self.trans_key}, Room: {self.room_id}, Sub: {self.sub_id}, State: {self.device_state}"
    
class PacketParser:
    """"Class to parse packets."""

    HEADER_BYTES: dict[int, str] = {
        0x28: DeviceType.THERMOSTAT,
        0x31: DeviceType.GEC,
        0x41: DeviceType.IGNORE,
        0x42: DeviceType.IGNORE,
        0x61: DeviceType.FAN,
        0xC1: DeviceType.ELEVATOR,
        0xD1: DeviceType.ENERGY,
    }
    
    def __init__(self):
        """Initialize the packet parser."""
        self.current_position = 0
        self.data = bytes()
    
    def set_data(self, data: bytes) -> None:
        """Set new data to parse and reset position."""
        self.data = data
        self.current_position = 0
        
    def find_next_packet_start(self) -> int | None:
        """Find the next packet start marker (0x02) from the current position."""
        try:
            start_pos = self.data.index(0x02, self.current_position)
            return start_pos
        except ValueError:
            return None
    
    def get_packet_length(self, start_idx: int, device_type: str) -> int:
        """Determine packet length based on device type and packet data."""
        length = self.data[start_idx + 2]
        
        if device_type == DeviceType.GEC:
            if length in [0x00, 0x80, 0x02, 0x82]:
                length = 10
        elif device_type in [DeviceType.FAN, DeviceType.GAS]:
            length = 10
        
        return length
        
    def get_device_type(self, header_byte: int, start_idx: int) -> DeviceType | None:
        """Determine device type based on header byte and packet type."""
        device_type = self.HEADER_BYTES.get(header_byte)
        
        def check_ec_condition(hex_value):
            """Check if the hex value meets the condition"""
            if (
                (hex_value & 0xF0 in [0x30, 0x50]) 
                and (hex_value & 0x0F in range(1, 7)
                or hex_value & 0x0F == 0xF)
            ):
                return True
            else:
                return False
        
        if device_type == DeviceType.GEC or (
            device_type is None and check_ec_condition(header_byte)
        ):
            if self.data[start_idx + 2] in [0x00, 0x80, 0x02, 0x82]:
                return DeviceType.GAS
            return DeviceType.EC
        
        return device_type
        
    def check_checksum(self, data: bytes) -> bool:
        """Validate the checksum of the packet."""
        checksum = 3
        for byte in data[:-1]:
            checksum ^= byte
            checksum = (checksum + 1) & 0xFF
        return checksum == data[-1]
            
    def parse_single_packet(self, start_idx: int) -> tuple[Packet | None, int]:
        """Parse a single packet starting from the given index."""
        if start_idx + 3 > len(self.data):
            return None, len(self.data)
            
        if self.data[start_idx] != 0x02:
            return None, start_idx + 1
        
        header = self.data[start_idx + 1]
        device_type = self.get_device_type(header, start_idx)
        
        #if device_type is None:
        #    logging.warning(f"Unknown device type at index {start_idx}: {self.data.hex()}")
        #    return None, start_idx + 1
        
        length = self.get_packet_length(start_idx, device_type)
        packet_type, seq_number = self.get_packet_info(length, start_idx)

        if start_idx + length > len(self.data):
            return None, len(self.data)
        
        packet_data = self.data[start_idx:start_idx + length]
        is_valid = self.check_checksum(packet_data)
        return Packet(device_type, packet_type, seq_number, packet_data, is_valid), start_idx + length
    
    def get_packet_info(self, length: int, start_idx: int) -> tuple[PacketType, int]:
        """Get packet information based on the data."""
        if length in [10]:
            if self.data[start_idx + 2] in [0x00]:
                packet_type = PacketType.QUERY
            elif self.data[start_idx + 2] in [0x80]:
                packet_type = PacketType.RES
            else:
                packet_type = PacketType.ACK
            return packet_type, self.data[start_idx + 3]
        else:
            if self.data[start_idx + 3] in [0x02, 0x11, 0x21]:
                packet_type = PacketType.QUERY
            elif self.data[start_idx + 3] in [0x82, 0x91, 0xA1, 0xB1]:
                packet_type = PacketType.RES
            else:
                packet_type = PacketType.ACK
            return packet_type, self.data[start_idx + 4]
        
    def parse_packets(self) -> list[Packet]:
        """Parse all valid packets from the current data."""
        packets: list[Packet] = []
        
        while True:
            start_idx = self.find_next_packet_start()
            if start_idx is None:
                break
                
            packet, next_idx = self.parse_single_packet(start_idx)
            if packet:
                packets.append(packet)
            self.current_position = next_idx
                
        return packets
        
    @classmethod
    def parse(cls, data: bytes) -> list[Packet]:
        """Class method for convenient one-shot parsing."""
        parser = cls()
        parser.set_data(data)
        return parser.parse_packets()


class DevicePacketParser:
    """Class for parsing device packets."""

    def __init__(self, packet: Packet) -> None:
        """Initialize the parser with a packet."""
        self.device_type = packet.device_type
        self.packet_type = packet.packet_type
        self.seq_number = packet.seq_number
        self.data = packet.data
        self.is_valid = packet.is_valid

    def parse(self) -> DevicePacket | list[DevicePacket] | None:
        """Parse the packet data based on the device type."""
        try:
            if self.device_type is None:
                logging.error(f"Unknown device type at {self.data[1]:#x}: {self.data.hex()}")
                return None
            device_parse = getattr(self, f"parse_{self.device_type.value}", None)
            if device_parse is None:
                logging.error(f"Device parsing method not found for {self.device_type.value}")
                return None
            return device_parse()
        except Exception as e:
            logging.error(f"Error parsing {self.device_type.value} packet({e}): {self.data.hex()}")
            return None

    def parse_energy(self) -> list[DevicePacket]:
        """Parse the packet data for energy devices."""
        device_packets = []
        start_idx = 7
        repeat_cnt = (len(self.data) - 8) // 8 
        
        for _ in range(repeat_cnt):
            id = self.data[start_idx]
            increment = 10 if (id & 0xF0) == 0x80 else 8

            energy_type = INT_TO_ENERGY_TYPE.get(id & 0x0F)
            if energy_type is None:
                logging.warning(f"Unknown energy type for ID: {id & 0x0F}")
                continue

            device_packet = DevicePacket(
                trans_key=DeviceType.ENERGY.value,
                room_id=energy_type.value,
                sub_id=None,
                device_state={
                    "today_usage": self.data[start_idx + 1],
                    "yesterday_usage": self.data[start_idx + 2],
                    "generation_usage": self.data[start_idx + 3],
                    "average_usage": self.data[start_idx + 4],
                    "realtime_usage": int.from_bytes(
                        self.data[start_idx + 6:start_idx + 8], byteorder="big"
                    ),
                }
            )
            device_packets.append(device_packet)
            start_idx += increment

        return device_packets
    
    def parse_fan(self) -> DevicePacket:
        """Parse the packet data for a fan."""
        return DevicePacket(
            trans_key=DeviceType.FAN.value,
            room_id=self.data[4],
            sub_id=None,
            device_state={
                "state": bool(self.data[5] & 0x01),
                "natural_state": bool(self.data[5] >> 4 & 1),
                "wind_speed": self.data[6],
            }
        )
    
    def parse_gas(self) -> DevicePacket:
        """""Parse the packet data for a gas."""
        return DevicePacket(
            trans_key=DeviceType.GAS.value,
            room_id=self.data[4],
            sub_id=None,
            device_state=bool(self.data[5])
        )

    def parse_thermostat(self) -> list[DevicePacket]:
        """Parse the packet data for thermostat devices."""
        device_packets = []
        
        if len(self.data) == 16:
            device_packets.append(DevicePacket(
                trans_key=DeviceType.THERMOSTAT.value,
                room_id=self.data[5] & 0x0F,
                sub_id=None,
                device_state={
                    "state": bool(self.data[6] & 0x01),
                    "set_temperature": (self.data[7] & 0x3F) + (self.data[7] & 0x40 > 0) * 0.5,
                    "cur_temperature": int.from_bytes(self.data[8:10], byteorder='big') / 10.0,
                }
            ))
            device_packets.append(DevicePacket(
                trans_key="",
                room_id=self.data[5] & 0x0F,
                sub_id="",
                device_state=self.data[11],
            ))
            device_packets.append(DevicePacket(
                trans_key="",
                room_id=self.data[5] & 0x0F,
                sub_id="",
                device_state=self.data[12],
            ))
            device_packets.append(DevicePacket(
                trans_key="",
                room_id=self.data[5] & 0x0F,
                sub_id="",
                device_state=self.data[13],
            ))
            device_packets.append(DevicePacket(
                trans_key="",
                room_id=self.data[5] & 0x0F,
                sub_id="",
                device_state=self.data[14],
            ))
        elif len(self.data) == 14:
            device_packets.append(DevicePacket(
                trans_key="heating_water",
                room_id=None,
                sub_id=None,
                device_state={
                    "water_min": self.data[6],
                    "water_max": self.data[7],
                    "water_set": self.data[8],
                }
            ))
            device_packets.append(DevicePacket(
                trans_key="hot_water",
                room_id=None,
                sub_id=None,
                device_state={
                    "water_min": self.data[9],
                    "water_max": self.data[10],
                    "water_set": self.data[11],
                }
            ))
        return device_packets


if __name__ == "__main__":
    comm = Communicator(":8899")
    comm.connect()

    while True:
        receive = comm.receive()
        packets = PacketParser.parse(receive)
        for packet in packets:
            if packet.packet_type == PacketType.RES:
                parse_data = DevicePacketParser(packet).parse()
                if parse_data is not None:
                    #print(' '.join(f'{byte:02X}' for byte in packet.data))
                    print(parse_data)
