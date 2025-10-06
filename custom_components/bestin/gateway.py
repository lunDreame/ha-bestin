from __future__ import annotations

import re
import time
import asyncio
import serial_asyncio

from typing import cast, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    VERSION,
    LOGGER,
    NEW_CLIMATE,
    NEW_FAN,
    NEW_LIGHT,
    NEW_SENSOR,
    NEW_SWITCH,
)
from .controller import BestinController


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

    async def send(self, packet: bytearray) -> None:
        """Send a packet."""
        try:
            self.writer.write(packet)
            await self.writer.drain()
        except Exception as e:
            LOGGER.error(f"Failed to send packet data: {e}")
            await self.reconnect()

    async def receive(self, size: int = 256) -> bytes | None:
        """Receive data."""
        try:
            return await self.reader.read(size)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            LOGGER.error(f"Failed to receive packet data: {e}")
            await self.reconnect()
            return None

    async def close(self) -> None:
        """Close the connection."""
        if self.writer:
            LOGGER.info("Connection closed.")
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None


class BestinGateway:

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the BestinGateway."""
        self.hass = hass
        self.entry = entry
        self.api: BestinController = None
        self.connection: ConnectionManager = None
        self.entity_groups: dict[str, set[str]] = {}
        self.entity_to_id: dict[str, str] = {}

    @staticmethod
    def get_gateway(hass: HomeAssistant, entry: ConfigEntry) -> BestinController:
        """Get the gateway instance."""
        return hass.data[DOMAIN][entry.entry_id]

    @property
    def host(self) -> str:
        """Get the host."""
        return cast(str, self.entry.data.get(CONF_HOST))

    @property
    def port(self) -> int:
        """Get the port."""
        return cast(int, self.entry.data.get(CONF_PORT))
    
    @property
    def available(self) -> bool:
        """Check if the gateway is available."""
        if self.connection:
            return self.connection.is_connected()
        return True
    
    @property
    def sw_version(self) -> str:
        """Get the software version of the gateway."""
        return VERSION

    def conn_str(self, host: Optional[str], port: Optional[int]) -> str:
        """Generate the connection string."""
        host = getattr(self, "host", host)
        if not re.match(r"/dev/tty(USB|AMA)\d+", host):
            return f"{host}:{str(getattr(self, "port", port))}"
        return host

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
        return f"{new_device[device_type]}_{self.host}"

    @callback
    def async_add_device_callback(
        self, device_type: str, device=None, force: bool = False
    ) -> None:
        """Add a new device callback."""
        platform = device.platform
        unique_id = device.key.unique_id
        
        if (unique_id in self.entity_groups.get(platform, set()) or
            unique_id in self.entity_to_id):
            return
        
        args = []
        if device is not None and not isinstance(device, list):
            args.append([device])

        async_dispatcher_send(
            self.hass,
            self.async_signal_new_device(device_type),
            *args,
        )
    
    async def connect(self, host: Optional[str], port: Optional[int]) -> bool:
        """Connect to the gateway."""
        if not self.connection or not self.available:
            self.connection = ConnectionManager(self.conn_str(host, port))
        else:
            await self.connection.close()

        await self.connection.connect()
        return self.available

    async def async_close(self) -> None:
        """Close the gateway connection."""
        if self.api:
            await self.api.stop()
        if self.connection and self.available:
            await self.connection.close()

    @callback
    async def shutdown(self, event: Event) -> None:
        """Shutdown the gateway."""
        if self.api:
            await self.api.stop()
        if self.connection and self.available:
            await self.connection.close()

    async def async_start(self) -> None:
        """Start the gateway with the controller."""
        self.api = BestinController(
            self.hass,
            self.entry,
            self.entity_groups,
            self.host,
            self.connection,
            self.async_add_device_callback,
        )
        await self.api.start()
