import re
import time
import asyncio
import traceback

import serial_asyncio # type: ignore
import socket

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PORT,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.entity_registry import (
    async_entries_for_config_entry,
    async_get
)

from .const import (
    DOMAIN,
    NAME,
    VERSION,
    LOGGER,
    NEW_CLIMATE,
    NEW_FAN,
    NEW_LIGHT,
    NEW_SENSOR,
    NEW_SWITCH,
)
from .api import BestinAPI
from .controller import BestinController


class SerialSocketCommunicator:
    def __init__(self, conn_str):
        self.conn_str = conn_str
        self.is_serial = False
        self.is_socket = False
        self.reader = None
        self.writer = None
        self.reconnect_attempts = 0
        self.last_reconnect_attempt = None
        self.next_attempt_time = None

        self.chunk_size = 64  # Serial standard
        self.constant_packet_length = 10
        self._parse_conn_str()

    def _parse_conn_str(self):
        if re.match(r"COM\d+|/dev/tty\w+", self.conn_str):
            self.is_serial = True
        elif re.match(r"\d+\.\d+\.\d+\.\d+:\d+", self.conn_str):
            self.is_socket = True
        else:
            raise ValueError("Invalid connection string")

    async def connect(self):
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

    async def _connect_serial(self):
        self.reader, self.writer = await serial_asyncio.open_serial_connection(url=self.conn_str, baudrate=9600)
        LOGGER.info(f"Serial connection established on {self.conn_str}")

    async def _connect_socket(self):
        host, port = self.conn_str.split(":")
        self.reader, self.writer = await asyncio.open_connection(host, int(port))
        LOGGER.info(f"Socket connection established to {host}:{port}")

    def is_connected(self):
        try:
            if self.is_serial:
                return self.writer is not None and not self.writer.transport.is_closing()
            elif self.is_socket:
                return self.writer is not None
        except Exception:
            return False

    async def reconnect(self):
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

    async def send(self, packet):
        try:
            self.writer.write(packet)
            await self.writer.drain()
            await asyncio.sleep(0.1)
        except Exception as e:
            LOGGER.error(f"Failed to send packet data: {e}")
            await self.reconnect()

    async def receive(self, size=64):
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

    async def _receive_socket(self):
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
                    and packet[1] & 0xF0 != 0x50  # all-in-one(AIO) 0x51-0x55
                ):
                    return b''

                if (
                    (packet[1] == 0x31 and packet[2] in [0x00, 0x02, 0x80, 0x82])
                    or packet[1] == 0x61
                    or packet[1] == 0x17  # all-in-one(AIO) 0x17
                ):
                    packet_length = self.constant_packet_length
                else:
                    packet_length = packet[2]
                
                if packet_length <= 0:
                    LOGGER.error(f"Invalid packet length in packet. {packet.hex()}")
                    return b''

                packet += await recv_exactly(packet_length - len(packet))
                
                if len(packet) >= packet_length:
                    return packet[:packet_length]

        except socket.error as e:
            LOGGER.error(f"Socket error: {e}")
            await self.reconnect()
        
        return b''
    
    async def close(self):
        if self.writer:
            LOGGER.info("Connection closed.")
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None


@callback
def load_gateway_from_entry(hass, config_entry):
    """Return gateway with a matching entry_id."""
    return hass.data[DOMAIN][config_entry.entry_id]

def check_ip_or_serial(id):
    """Verify that the string is an IP address or serial device path."""
    ip_pattern = re.compile(r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$")
    serial_pattern = re.compile(r"/dev/tty(USB|AMA)\d+")

    if ip_pattern.match(id) or serial_pattern.match(id):
        return True
    else:
        return False


class BestinGateway:
    """Bestin Gateway Class."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry
    ) -> None:
        """Gateway initialization."""
        self.hass = hass
        self.config_entry = config_entry
        self.api: BestinAPI | BestinController = None
        self.communicator: SerialSocketCommunicator = None
        self.gateway_mode: tuple = None
        self.entities: dict = {}
        self.listeners: list = []

    @property
    def gatewayid(self) -> str:
        """Return the gateway's unique identifier."""
        return self.config_entry.unique_id

    @property
    def ip_address(self) -> str:
        """Return the IP address config entry."""
        return self.config_entry.data.get(CONF_IP_ADDRESS)

    @property
    def port(self) -> str:
        """Return the port config entry."""
        return self.config_entry.data.get(CONF_PORT)

    @property
    def identifier(self) -> str:
        """Return the identifier config entry."""
        return self.config_entry.data.get("identifier")

    @property
    def center_version(self) -> str:
        """Return the version config entry."""
        return self.config_entry.data.get("version")

    @property
    def available(self) -> bool:
        """Return the communication connection status."""
        if self.communicator:
            return self.communicator.is_connected()
        return True

    @property
    def model(self) -> str:
        """Return the domain configuration."""
        return DOMAIN

    @property
    def name(self) -> str:
        """Return the name configuration."""
        return NAME

    @property
    def version(self) -> str:
        """Return the version configuration."""
        return VERSION
    
    @property
    def is_polling(self) -> bool:
        """Return whether to poll according to device characteristics."""
        if check_ip_or_serial(self.gatewayid):
            return False
        else:
            return True

    @property
    def wp_ver(self) -> str:
        """Returns the version of the gateway."""
        if check_ip_or_serial(self.gatewayid):
            return f"{self.gateway_mode[0]}-generation"
        else:
            return f"Center-{self.center_version}"

    @property
    def conn_str(self) -> str:
        """Generate the connection string based on the host and port."""
        if not re.match(r"/dev/tty(USB|AMA)\d+", self.gatewayid):
            conn_str = f"{self.gatewayid}:{self.port}"
        else:
            conn_str = self.gatewayid
        return conn_str
    
    async def determine_gateway_mode(self) -> None:
        """The gateway mode is determined by the received data."""
        chunk_storage = []
        aio_data = {}
        try:
            while len(b''.join(chunk_storage)) < 1024:
                received_data = await self.communicator._receive_socket()
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
                if ((chunk_length == 20 or chunk_length == 22)
                    and command_byte in [0x91, 0xB2]
                ):
                    aio_data[room_byte] = command_byte

            if aio_data:
                self.gateway_mode = ("AIO", aio_data)
                LOGGER.debug(f"AIO mode set with data: {aio_data}")
            else:
                self.gateway_mode = ("General", None)
                LOGGER.debug("General mode set")
        except Exception as e:
            problematic_packet = locals().get("received_data", None)
            raise RuntimeError(
                f"Error during gateway mode determination: {e}. "
                f"Problematic packet: {problematic_packet.hex() if problematic_packet else 'None'}"
            )
        
    async def async_load_entity_registry(self):
        """Load entities from the registry and organize them by domain."""
        entity_registry = async_get(self.hass)
        get_entities = async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        for entity in get_entities:
            domain = entity.entity_id.split(".")[0]
            if domain not in self.entities:
                self.entities[domain] = set()
            if entity.unique_id not in self.entities[domain]:
                self.entities[domain].add(entity.unique_id)
            LOGGER.debug(
                "Added entity '%s' with unique_id '%s' to domain '%s'",
                entity.entity_id, entity.unique_id, domain
            )

    async def async_update_device_registry(self):
        """Create or update device entry in Home Assistant registry."""
        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            connections={(DOMAIN, self.gatewayid)},
            identifiers={(DOMAIN, self.gatewayid)},
            manufacturer="HDC Labs Co., Ltd.",
            name=self.name,
            model=self.wp_ver,
            sw_version=self.version,
            via_device=(DOMAIN, self.gatewayid),
        )

    @callback
    def async_signal_new_device(self, device_type: str) -> str:
        """Return unique signal name for a new device."""
        new_device = {
            NEW_LIGHT: "bestin_new_light",
            NEW_SWITCH: "bestin_new_switch",
            NEW_SENSOR: "bestin_new_sensor",
            NEW_CLIMATE: "bestin_new_climate",
            NEW_FAN: "bestin_new_fan",
        }
        return f"{new_device[device_type]}_{self.gatewayid}"

    @callback
    def async_add_device_callback(
        self, device_type, device=None, force: bool = False
    ) -> None:
        """Add device callback if not already registered."""
        domain = device.platform
        unique_id = device.unique_id

        if (
            unique_id in self.entities.get(domain, set()) or
            unique_id in self.hass.data[DOMAIN]
        ):
            return
        args = []
        if device is not None and not isinstance(device, list):
            args.append([device])

        dispatcher_send(
            self.hass,
            self.async_signal_new_device(device_type),
            *args,
        )
    
    async def connect(self) -> bool:
        """Establish a connection to the serial socket communicator."""
        if self.communicator is None or not self.available:
            self.communicator = SerialSocketCommunicator(self.conn_str)
        else:
            await self.communicator.close()
        await self.communicator.connect()
        return self.available
    
    @callback
    async def shutdown(self) -> None:
        """Shut down the connection and clear entities."""
        LOGGER.debug(
            "A shutdown call detects the current entity: %s and listener: %s and removes them.",
            self.entities, self.listeners
        )
        self.listeners.clear()
        for platform, entities in self.entities.items():
            for unique_id in list(entities):
                self.hass.data[DOMAIN].pop(unique_id, None)
        await self.api.stop()
        if self.communicator and self.available:
            await self.communicator.close()

    async def async_initialize_gateway(self) -> None:
        """
        Initialize the Bestin gateway.

        This method sets up the Bestin gateway by ensuring the gateway mode is set,
        updating the configuration entry, and starting the BestinController API.
        """
        try:
            if self.gateway_mode is None:
                await self.determine_gateway_mode()

            self.hass.config_entries.async_update_entry(
                entry=self.config_entry,
                title=self.gatewayid,
                data={**self.config_entry.data, "gateway_mode": self.gateway_mode},
            )
            self.api = BestinController(
                self.hass,
                self.config_entry,
                self.entities,
                self.gatewayid,
                self.communicator,
                self.async_add_device_callback,
            )
            await asyncio.sleep(1)
            await self.api.start()
        except Exception as ex:
            self.api = None
            LOGGER.error(
                f"Failed to initialize Bestin gateway. Host: {self.gatewayid}, Gateway Mode: {self.gateway_mode}. "
                f"Error: {str(ex)}. Traceback: {traceback.format_exc()}"
            )

    async def initialize_control_statuses(self) -> None:
        """
        Initialize the initial control statuses for lights, outlets, and thermostats.
        """
        try:
            self.api = BestinAPI(
                self.hass,
                self.config_entry,
                self.entities,
                self.gatewayid,
                self.center_version,
                self.identifier,
                self.async_add_device_callback,
            )
            await self.api.start()

            if self.center_version == "version2.0" and self.ip_address:
                if re.match(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$", self.ip_address):
                    await self.api._setup_elevator_entities()
                else:
                    LOGGER.warning(
                        f"Wallpad IP address exists, but it doesn't fit the format pattern. {self.ip_address} "
                        f"Please report it to the developer."
                    )
        except Exception as ex:
            self.api = None
            LOGGER.error(
                f"Failed to initialize Bestin API. Host: {self.gatewayid}, Version: {self.center_version}. "
                f"Error: {str(ex)}. Traceback: {traceback.format_exc()}"
            )
