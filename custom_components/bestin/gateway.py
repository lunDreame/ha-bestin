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
        """Establish a connection with timeout."""
        try:
            if self.is_serial:
                self.reader, self.writer = await asyncio.wait_for(
                    serial_asyncio.open_serial_connection(
                        url=self.conn_str, baudrate=9600
                    ),
                    timeout=timeout
                )
                LOGGER.info("Serial connection established on %s", self.conn_str)
            elif self.is_socket:
                host, port = self.conn_str.split(":")
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)),
                    timeout=timeout
                )
                LOGGER.info("Socket connection established to %s:%s", host, port)
            self.reconnect_attempts = 0
        except asyncio.TimeoutError:
            LOGGER.error("Connection timeout after %ds", timeout)
            await self.reconnect()
        except Exception as e:
            LOGGER.error("Connection failed: %s", e)
            await self.reconnect()

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
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

        current_time = time.time()
        if self.next_attempt_time and current_time < self.next_attempt_time:
            return False
        
        self.reconnect_attempts += 1
        delay = min(2 ** self.reconnect_attempts, 60) if self.last_reconnect_attempt else 1
        self.last_reconnect_attempt = current_time
        self.next_attempt_time = current_time + delay
        LOGGER.info("Reconnection attempt %d after %ds delay...", self.reconnect_attempts, delay)

        await asyncio.sleep(delay)
        await self.connect()
        if self.is_connected():
            LOGGER.info("Reconnected on attempt %d", self.reconnect_attempts)
            self.reconnect_attempts = 0
            self.next_attempt_time = None

    async def send(self, packet: bytearray, timeout: float = 2.0) -> None:
        """Send a packet with timeout."""
        try:
            self.writer.write(packet)
            await asyncio.wait_for(self.writer.drain(), timeout=timeout)
        except asyncio.TimeoutError:
            LOGGER.error("Send timeout after %.1fs", timeout)
            await self.reconnect()
        except Exception as e:
            LOGGER.error("Failed to send: %s", e)
            await self.reconnect()

    async def receive(self, size: int = 256, timeout: float = 1.0) -> bytes | None:
        """Receive data with timeout."""
        try:
            return await asyncio.wait_for(self.reader.read(size), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            LOGGER.error("Failed to receive: %s", e)
            await self.reconnect()
            return None

    async def close(self) -> None:
        """Close the connection."""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
            LOGGER.info("Connection closed")


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
    def get_gateway(hass: HomeAssistant, entry: ConfigEntry) -> BestinGateway:
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
    def async_add_device_callback(self, device_type: str, device=None) -> None:
        """Add device callback (compatibility placeholder)."""
        pass
    
    async def connect(self, host: Optional[str], port: Optional[int]) -> bool:
        """Connect to the gateway."""
        if not self.connection or not self.available:
            self.connection = ConnectionManager(self.conn_str(host, port))
        elif self.available:
            await self.connection.close()

        await self.connection.connect()
        return self.available

    async def async_close(self) -> None:
        """Close the gateway connection."""
        if self.api:
            await self.api.stop()
        if self.connection:
            await self.connection.close()

    @callback
    async def shutdown(self, event: Event) -> None:
        """Shutdown the gateway."""
        await self.async_close()

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
