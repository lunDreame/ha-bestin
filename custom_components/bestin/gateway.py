from __future__ import annotations

import re
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
    """Connection manager for serial/socket communication."""
    
    def __init__(self, conn_str: str) -> None:
        """Initialize the ConnectionManager."""
        self.conn_str = conn_str
        self.is_serial = False
        self.is_socket = False
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_attempts: int = 0
        self._reconnect_lock = asyncio.Lock()

        self._parse_conn_str()

    def _parse_conn_str(self) -> bool:
        """Parse the connection string to determine connection type."""
        if re.match(r"COM\d+|/dev/tty\w+", self.conn_str):
            self.is_serial = True
        elif re.match(r"\d+\.\d+\.\d+\.\d+:\d+", self.conn_str):
            self.is_socket = True
        else:
            raise ValueError("Invalid connection string")

    async def connect(self, timeout: int = 5) -> bool:
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
            
            self._reconnect_attempts = 0
            return True
            
        except Exception as e:
            LOGGER.error("Connection failed: %s", e)
            self.reader = None
            self.writer = None
            return False

    def is_connected(self) -> bool:
        """Check if the connection is active."""
        try:
            if not self.writer or not self.reader:
                return False
            
            if self.is_serial:
                return not self.writer.transport.is_closing()
            else:
                try:
                    return not self.writer.is_closing()
                except AttributeError:
                    return self.writer is not None
        except Exception:
            return False

    def _schedule_reconnect(self) -> None:
        """Schedule background reconnection if not already running."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Background reconnection with exponential backoff."""
        async with self._reconnect_lock:
            while not self.is_connected():
                await self._close_connection()
                
                delay = min(2 ** self._reconnect_attempts, 60)
                self._reconnect_attempts += 1
                
                LOGGER.info(
                    "Reconnecting in %ds (attempt %d)...", 
                    delay, self._reconnect_attempts
                )
                await asyncio.sleep(delay)
                
                if await self.connect():
                    LOGGER.info("Reconnected after %d attempts", self._reconnect_attempts)
                    return
    
    async def _close_connection(self) -> None:
        """Close existing connection safely."""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            finally:
                self.writer = None
                self.reader = None

    async def send(self, packet: bytearray, timeout: float = 2.0) -> bool:
        """Send a packet."""
        if not self.is_connected():
            LOGGER.warning("Send aborted: not connected")
            return False
            
        try:
            self.writer.write(packet)
            await asyncio.wait_for(self.writer.drain(), timeout=timeout)
            LOGGER.debug("TX: %s", packet.hex(" "))
            return True
            
        except Exception as e:
            LOGGER.error("Send failed: %s", e)
            self._schedule_reconnect()
            return False

    async def receive(self, size: int = 256, timeout: float = 1.0) -> bytes | None:
        """Receive data with timeout."""
        if not self.is_connected():
            return None
            
        try:
            data = await asyncio.wait_for(self.reader.read(size), timeout=timeout)
            
            if data:
                LOGGER.debug("RX: %s", data.hex(" "))
                return data
            elif data == b'':
                LOGGER.warning("Connection closed by remote")
                self._schedule_reconnect()
                return None
            return data
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            LOGGER.error("Receive failed: %s", e)
            self._schedule_reconnect()
            return None

    async def close(self) -> None:
        """Close the connection and cancel reconnection."""
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        
        await self._close_connection()
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
