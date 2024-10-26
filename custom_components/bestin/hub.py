"""Manages the hub connection and communication."""
import re
import time
import asyncio
import serial_asyncio
import socket

from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    NAME,
    VERSION,
    LOGGER,
    SMART_HOME_1,
    SMART_HOME_2,
    NEW_CLIMATE,
    NEW_FAN,
    NEW_LIGHT,
    NEW_SENSOR,
    NEW_SWITCH,
)
from .center import BestinCenterAPI
from .controller import BestinController
from .until import check_ip_or_serial


class ConnectionManager:
    """Handles hub connections."""
    
    def __init__(self, conn_str: str) -> None:
        """Initialize the ConnectionManager."""
        self.conn_str = conn_str
        self.is_serial = False
        self.is_socket = False
        self.reader: asyncio.StreamReader = None
        self.writer: asyncio.StreamWriter = None
        self.reconnect_attempts: int = 0
        self.last_reconnect_attempt: float = None
        self.next_attempt_time: float = None

        self.chunk_size = 64
        self.constant_packet_length = 10
        self._parse_conn_str()

    def _parse_conn_str(self) -> bool:
        """Parse the connection string to determine connection type."""
        if re.match(r"COM\d+|/dev/tty\w+", self.conn_str):
            self.is_serial = True
        elif re.match(r"\d+\.\d+\.\d+\.\d+:\d+", self.conn_str):
            self.is_socket = True
        else:
            raise ValueError("Invalid connection string")

    async def connect(self, timeout: int = 5) -> None:
        """Establish a connection."""
        try:
            if self.is_serial:
                await self._connect_serial()
            elif self.is_socket:
                await self._connect_socket()
            self.reconnect_attempts = 0
            LOGGER.info("Connection established successfully.")
        except Exception as e:
            LOGGER.error(f"Connection failed: {e}")
            await self.reconnect()

    async def _connect_serial(self) -> None:
        """Establish a serial connection."""
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.conn_str, baudrate=9600
        )
        LOGGER.info(f"Serial connection established on {self.conn_str}")

    async def _connect_socket(self) -> None:
        """Establish a socket connection."""
        host, port = self.conn_str.split(":")
        self.reader, self.writer = await asyncio.open_connection(host, int(port))
        LOGGER.info(f"Socket connection established to {host}:{port}")

    def is_connected(self) -> bool:
        """Check if the connection is active."""
        try:
            if self.is_serial:
                return self.writer is not None and not self.writer.transport.is_closing()
            elif self.is_socket:
                return self.writer is not None
        except Exception:
            return False

    async def reconnect(self) -> bool | None:
        """Attempt to reconnect with exponential backoff."""
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()

        current_time = time.time()
        if self.next_attempt_time and current_time < self.next_attempt_time:
            return False
        
        self.reconnect_attempts += 1
        delay = min(2 ** self.reconnect_attempts, 60) if self.last_reconnect_attempt else 1
        self.last_reconnect_attempt = current_time
        self.next_attempt_time = current_time + delay
        LOGGER.info(f"Reconnection attempt {self.reconnect_attempts} after {delay} seconds delay...")

        await asyncio.sleep(delay)
        await self.connect()
        if self.is_connected():
            LOGGER.info(f"Successfully reconnected on attempt {self.reconnect_attempts}.")
            self.reconnect_attempts = 0
            self.next_attempt_time = None

    async def send(self, packet: bytearray, interval: int) -> None:
        """Send a packet."""
        try:
            self.writer.write(packet)
            await self.writer.drain()
            await asyncio.sleep(interval)
        except Exception as e:
            LOGGER.error(f"Failed to send packet data: {e}")
            await self.reconnect()

    async def receive(self, size: int = 64) -> bytes | None:
        """Receive data."""
        try:
            if self.chunk_size == size: 
                return await self._receive_socket()
            else:
                return await self.reader.read(size)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            LOGGER.error(f"Failed to receive packet data: {e}")
            await self.reconnect()
            return None

    async def _receive_socket(self) -> bytes:
        """Receive data from a socket connection."""
        
        async def recv_exactly(n):
            data = b''
            while len(data) < n:
                chunk = await self.reader.read(n - len(data))
                if not chunk:
                    raise socket.error("Connection closed")
                data += chunk
            return data

        packet = b''
        try:
            while True:
                while True:
                    initial_data = await self.reader.read(1)
                    if not initial_data:
                        return b''
                    packet += initial_data
                    if 0x02 in packet:
                        start_index = packet.index(0x02)
                        packet = packet[start_index:]
                        break
                
                packet += await recv_exactly(3 - len(packet))
                
                if (
                    packet[1] not in [0x28, 0x31, 0x41, 0x42, 0x61, 0xD1]
                    and packet[1] & 0xF0 != 0x50   # For AIO (0x51-0x55)
                    and packet[1] & 0x30 != 0x30   # For Gen2 (0x3F, 0x31-0x36)
                ):
                    return b''

                if (
                    (packet[1] == 0x31 and packet[2] in [0x00, 0x02, 0x80, 0x82])
                    or packet[1] == 0x61
                    or packet[1] == 0x17  # For AIO
                ):
                    packet_length = self.constant_packet_length
                else:
                    packet_length = packet[2]
                
                if packet_length <= 0:
                    #LOGGER.error(f"Invalid packet length in packet: {packet.hex()}")
                    return b''

                packet += await recv_exactly(packet_length - len(packet))
                
                if len(packet) >= packet_length:
                    return packet[:packet_length]

        except socket.error as e:
            LOGGER.error(f"Socket error: {e}")
            await self.reconnect()
        
        return b''
    
    async def close(self) -> None:
        """Close the connection."""
        if self.writer:
            LOGGER.info("Connection closed.")
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None


class BestinHub:
    """Represents a Bestin Hub for managing smart home devices."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the BestinHub."""
        self.hass = hass
        self.entry = entry
        self.api: BestinCenterAPI | BestinController = None
        self.connection: ConnectionManager = None
        self.gateway_mode: tuple[str, dict[bytes] | None] = None
        self.entity_groups: dict[str, set[str]] = {}
        self.entity_to_id: dict[str, str] = {}

    @staticmethod
    def get_hub(hass: HomeAssistant, entry: ConfigEntry) -> BestinCenterAPI | BestinController:
        """Get the hub instance."""
        return hass.data[DOMAIN][entry.entry_id]

    @property
    def hub_id(self) -> str:
        """Get the hub ID."""
        return cast(str, self.entry.unique_id)

    @property
    def port(self) -> int:
        """Get the port number."""
        return cast(int, self.entry.data.get(CONF_PORT))

    @property
    def gw_type(self) -> str:
        """Get the gateway type."""
        return cast(str, self.gateway_mode[0])
    
    @property
    def available(self) -> bool:
        """Check if the hub is available."""
        if self.connection:
            return self.connection.is_connected()
        return True
    
    @property
    def model(self) -> str:
        """Get the model of the hub."""
        return DOMAIN

    @property
    def name(self) -> str:
        """Get the name of the hub."""
        return NAME
    
    @property
    def sw_version(self) -> str:
        """Get the software version of the hub."""
        return VERSION

    @property
    def cntr_version(self) -> str:
        """Get the controller version."""
        if CONF_USERNAME in self.entry.data:
            return SMART_HOME_1
        return SMART_HOME_2
    
    @property
    def is_polling(self) -> bool:
        """Check if the hub is in polling mode."""
        if check_ip_or_serial(self.hub_id):
            return False
        else:
            return True

    @property
    def wp_version(self) -> str:
        """Get the WP version."""
        if check_ip_or_serial(self.hub_id):
            return f"{self.gw_type}-generation"
        else:
            return self.cntr_version

    def conn_str(self, host: str | None, port: int | None) -> str:
        """Generate the connection string."""
        host = getattr(self, "hub_id", host)
        if not re.match(r"/dev/tty(USB|AMA)\d+", host):
            return f"{host}:{str(getattr(self, CONF_PORT, port))}"
        return host
    
    async def determine_gateway_mode(self) -> None:
        """Determine the gateway mode."""
        chunk_storage: list = []
        aio_data: dict = {}
        gen2_data: dict = {}
        try:
            while len(b''.join(chunk_storage)) < 1024:
                received_data = await self.connection._receive_socket()
                if not received_data:
                    break
                chunk_storage.append(received_data)

            for chunk in chunk_storage:
                if len(chunk) < 4:
                    raise ValueError(f"Chunk length is too short: length={len(chunk)}, chunk={chunk.hex()}")     
                chunk_length = chunk[2]
                room_byte = chunk[1]
                command_byte = chunk[3]

                LOGGER.debug(
                    "Received chunk: length=%d, room_byte=%s, command_byte=%s, hex=%s",
                    chunk_length, hex(room_byte), hex(command_byte), chunk.hex()
                )
                if (chunk_length in [20, 22] and command_byte in [0x91, 0xB2]):
                    aio_data[room_byte] = command_byte
                elif (chunk_length in [59, 72, 98, 150] and command_byte == 0x91):
                    gen2_data[room_byte] = command_byte

            if aio_data:
                self.gateway_mode = ("AIO", aio_data)
                LOGGER.debug(f"AIO mode set with data: {aio_data}")
            elif gen2_data:
                self.gateway_mode = ("Gen2", gen2_data)
                LOGGER.debug(f"Gen2 mode set with data: {gen2_data}")
            else:
                self.gateway_mode = ("General", None)
                LOGGER.debug("General mode set")
        except Exception as e:
            problematic_packet = locals().get("received_data", None)
            raise RuntimeError(
                f"Error during gateway mode determination: {e}. "
                f"Problematic packet: {problematic_packet.hex() if problematic_packet else 'None'}"
            )

    @callback
    def async_signal_new_device(self, device_type: str) -> str:
        """Generate a signal for a new device."""
        new_device = {
            NEW_CLIMATE: "bestin_new_climate",
            NEW_FAN: "bestin_new_fan",
            NEW_LIGHT: "bestin_new_light",
            NEW_SENSOR: "bestin_new_sensor",
            NEW_SWITCH: "bestin_new_switch",
        }
        return f"{new_device[device_type]}_{self.hub_id}"

    @callback
    def async_add_device_callback(
        self, device_type: str, device=None, force: bool = False
    ) -> None:
        """Add a new device callback."""
        domain = device.domain
        unique_id = device.unique_id
        device_info = device.info
        
        if (
            unique_id in self.entity_groups.get(domain, set()) or
            device_info.device_id in self.entity_to_id
        ):
            return
        
        args = []
        if device is not None and not isinstance(device, list):
            args.append([device])

        async_dispatcher_send(
            self.hass,
            self.async_signal_new_device(device_type),
            *args,
        )
    
    async def connect(self, host: str = None, port: int = None) -> bool:
        """Connect to the hub."""
        if not self.connection or not self.available:
            self.connection = ConnectionManager(self.conn_str(host, port))
        else:
            await self.connection.close()

        await self.connection.connect()
        return self.available
    
    async def async_close(self) -> None:
        """Close the hub connection."""
        if self.api:
            await self.api.stop()
        if self.connection and self.available:
            await self.connection.close()
        if self.gateway_mode:
            self.gateway_mode = None

    @callback
    async def shutdown(self, event: Event) -> None:
        """Shutdown the hub."""
        if self.api:
            await self.api.stop()
        if self.connection and self.available:
            await self.connection.close()
        if self.gateway_mode:
            self.gateway_mode = None
    
    async def async_initialize_serial(self) -> None:
        """Initialize the serial connection."""
        try:
            if self.gateway_mode is None:
                await self.determine_gateway_mode()

            self.hass.config_entries.async_update_entry(
                entry=self.entry,
                data={**self.entry.data, "gateway_mode": self.gateway_mode},
            )
            self.api = BestinController(
                self.hass,
                self.entry,
                self.entity_groups,
                self.hub_id,
                self.connection,
                self.async_add_device_callback,
            )
            await self.api.start()
        except Exception as ex:
            self.api = None
            raise RuntimeError(
                f"Failed to initialize Bestin hub. Host: {self.hub_id}, Mode: {self.gateway_mode}. "
                f"Error: {str(ex)}"
            )

    async def async_initialize_center(self) -> None:
        """Initialize the center connection."""
        try:
            self.api = BestinCenterAPI(
                self.hass,
                self.entry,
                self.entity_groups,
                self.hub_id,
                self.cntr_version,
                self.async_add_device_callback,
            )
            await self.api.start()
        except Exception as ex:
            self.api = None
            raise RuntimeError(
                f"Failed to initialize Bestin hub. Host: {self.hub_id}, Version: {self.cntr_version}. "
                f"Error: {str(ex)}"
            )
