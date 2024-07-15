import re
import time
import asyncio
import traceback
import serial # type: ignore
import socket

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.entity_registry import async_entries_for_config_entry, async_get

from .const import (
    DOMAIN,
    LOGGER,
    NAME,
    NEW_CLIMATE,
    NEW_FAN,
    NEW_LIGHT,
    NEW_SENSOR,
    NEW_SWITCH,
    VERSION,
)
from .controller import BestinController


class SerialSocketCommunicator:
    def __init__(self, conn_str):
        self.conn_str = conn_str
        self.is_serial = False
        self.is_socket = False
        self.connection = None
        self.reconnect_attempts = 0
        self.last_reconnect_attempt = None
        self.next_attempt_time = None

        self.chunk_size = 64  # Serial standard
        self.constant_packet_length = 10
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
            LOGGER.info("Connection established successfully.")
        except Exception as e:
            LOGGER.error(f"Connection failed: {e}")
            self.reconnect()

    def _connect_serial(self):
        self.connection = serial.Serial(self.conn_str, baudrate=9600, timeout=30)
        LOGGER.info(f"Serial connection established on {self.conn_str}")

    def _connect_socket(self):
        host, port = self.conn_str.split(':')
        self.connection = socket.socket()
        self.connection.settimeout(10)
        self.connection.connect((host, int(port)))
        LOGGER.info(f"Socket connection established to {host}:{port}")

    def is_connected(self):
        try:
            if self.is_serial:
                return self.connection.is_open
            elif self.is_socket:
                return self.connection is not None
        except socket.error:
            return False

    def reconnect(self):
        if self.connection is not None:
            self.connection.close()

        current_time = time.time()
        if self.next_attempt_time and current_time < self.next_attempt_time:
            return
        
        self.reconnect_attempts += 1
        delay = min(2 ** self.reconnect_attempts, 60) if self.last_reconnect_attempt else 1
        self.last_reconnect_attempt = current_time
        self.next_attempt_time = current_time + delay
        LOGGER.info(f"Reconnection attempt {self.reconnect_attempts} after {delay} seconds delay...")

        self.connect()
        if self.is_connected():
            LOGGER.info(f"Successfully reconnected on attempt {self.reconnect_attempts}.")
            self.reconnect_attempts = 0
            self.next_attempt_time = None

    def send(self, packet):
        try:
            if self.is_serial:
                self.connection.write(packet)
            elif self.is_socket:
                self.connection.send(packet)
        except Exception as e:
            LOGGER.error(f"Failed to send packet data: {e}")
            self.reconnect()

    def receive(self, size=64):
        try:
            if self.is_serial:
                return self.connection.read(size)
            elif self.is_socket:
                if self.chunk_size == size:
                    return self._receive_socket()
                else:
                    return self.connection.recv(size)
        except socket.timeout:
            pass
        except Exception as e:
            LOGGER.error(f"Failed to receive packet data: {e}")
            self.reconnect()
            return None

    def _receive_socket(self):
        def recv_exactly(n):
            data = b''
            while len(data) < n:
                chunk = self.connection.recv(n - len(data))
                if not chunk:
                    raise socket.error("Connection closed")
                data += chunk
            return data

        packet = b''
        try:
            while True:
                while True:
                    initial_data = self.connection.recv(1)
                    if not initial_data:
                        return b''  
                    packet += initial_data
                    if 0x02 in packet:
                        start_index = packet.index(0x02)
                        packet = packet[start_index:]
                        break
                
                packet += recv_exactly(3 - len(packet))
                
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
                    LOGGER.error("Invalid packet length in packet.")
                    return b''

                packet += recv_exactly(packet_length - len(packet))
                
                if len(packet) >= packet_length:
                    return packet[:packet_length]

        except socket.error as e:
            LOGGER.error(f"Socket error: {e}")
            self.reconnect()
        
        return b''
    
    def close(self):
        if self.connection:
            LOGGER.info("Connection closed.")
            self.connection.close()
            self.connection = None


@callback
def load_gateway_from_entry(hass, config_entry):
    """Return gateway with a matching entry_id."""
    return hass.data[DOMAIN][config_entry.entry_id]


class BestinGateway:
    """Bestin Gateway Class."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry
    ) -> None:
        """Gateway initialization."""
        self.hass = hass
        self.config_entry = config_entry
        self.api: BestinController = None
        self.connection: SerialSocketCommunicator = None
        self.gateway_mode: tuple = None
        self.entities: dict = {}
        self.listeners: list = []

    @property
    def host(self) -> str:
        """Return the host config entry."""
        return self.config_entry.data[CONF_HOST]

    @property
    def port(self) -> str:
        """Return the port config entry."""
        return self.config_entry.data[CONF_PORT]

    @property
    def available(self) -> bool:
        """Return the communication connection status."""
        return self.connection.is_connected()

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
    def wp_ver(self) -> str:
        """Returns the version of the gateway."""
        return self.gateway_mode[0]
    
    @property
    def conn_str(self) -> str:
        """Generate the connection string based on the host and port."""
        if not re.match(r'COM\d+|/dev/tty\w+', self.host):
            conn_str = f"{self.host}:{self.port}"
        else:
            conn_str = self.host
        return conn_str
    
    async def determine_gateway_mode(self) -> None:
        """The gateway mode is determined by the received data."""
        chunk_storage = []
        aio_data = {}
        try:
            while len(b''.join(chunk_storage)) < 1024:
                received_data = self.connection._receive_socket()
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
            problematic_packet = locals().get('received_data', None)
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
        device_registry = await self.hass.helpers.device_registry.async_get_registry()
        
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            connections={(DOMAIN, self.host)},
            identifiers={(DOMAIN, self.host)},
            manufacturer="HDC Labs Co., Ltd.",
            name=self.name,
            model=self.wp_ver,
            sw_version=self.version,
            via_device=(DOMAIN, self.host),
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
        return f"{new_device[device_type]}_{self.host}"

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
    
    def connect(self) -> bool:
        """Establish a connection to the serial socket communicator."""
        if self.connection is None or not self.available:
            self.connection = SerialSocketCommunicator(self.conn_str)
        else:
            self.connection.close()
        self.connection.connect()
        return self.available
    
    @callback
    def shutdown(self) -> None:
        """Shut down the connection and clear entities."""
        LOGGER.debug(
            "A shutdown call detects the current entity: %s and listener: %s and removes them.",
            self.entities, self.listeners
        )
        self.listeners.clear()
        for platform, entities in self.entities.items():
            for unique_id in list(entities):
                self.hass.data[DOMAIN].pop(unique_id, None)

        self.api.stop_event.set()
        self.api.process_thread.join()
        if self.available:
            self.connection.close()

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
                title=self.host,
                data={**self.config_entry.data, "gateway_mode": self.gateway_mode},
            )
            if not self.available:
                raise Exception("Not connection")
            
            self.api = BestinController(
                self.hass,
                self.config_entry,
                self.entities,
                self.host,
                self.connection,
                self.async_add_device_callback,
            )
            self.api.start()
        except Exception as ex:
            LOGGER.error(
                "Failed to initialize Bestin gateway. Host: %s, Gateway Mode: %s. Error: %s. Traceback: %s",
                self.host,
                self.gateway_mode,
                str(ex),
                traceback.format_exc()
            )
