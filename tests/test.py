import re
import socket
import time
import logging
import serial # type: ignore

logging.basicConfig(
    filename=None,
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class SerialSocketCommunicator:
    def __init__(self, conn_str):
        self.conn_str = conn_str
        self.is_serial = False
        self.is_socket = False
        self.connection = None
        self.reconnect_attempts = 0
        self.last_reconnect_attempt = None
        self.next_attempt_time = None

        self.chunk_size = 64  
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

    def send(self, packet):
        try:
            if self.is_serial:
                self.connection.write(packet)
            elif self.is_socket:
                self.connection.send(packet)
        except Exception as e:
            logging.error(f"Failed to send packet data: {e}")
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
            logging.error(f"Failed to receive packet data: {e}")
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
                    and packet[1] & 0xF0 != 0x50 
                ):
                    return b''  

                if (
                    (packet[1] == 0x31 and packet[2] in [0x00, 0x02, 0x80, 0x82])
                    or packet[1] == 0x61
                    or packet[1] == 0x17 
                ):
                    packet_length = self.constant_packet_length
                else:
                    packet_length = packet[2]
                
                if packet_length <= 0:
                    logging.error("Invalid packet length in packet.")
                    return b''

                packet += recv_exactly(packet_length - len(packet))
                
                if len(packet) >= packet_length:
                    return packet[:packet_length]

        except socket.error as e:
            logging.error(f"Socket error: {e}")
            self.reconnect()
        
        return b''
    
    def close(self):
        if self.connection:
            logging.info("Connection closed.")
            self.connection.close()
            self.connection = None


if __name__ == "__main__":
    comm = SerialSocketCommunicator("192.168.0.26:8899")
    comm.connect()
    comm2 = SerialSocketCommunicator("192.168.0.27:8899")
    comm2.connect()
    
    while True:
        receive = comm.receive()
        print(receive.hex())

    """
    chunk_storage = []
    while len(b''.join(chunk_storage)) < 1024:
        receive = comm._receive_socket()
        if not receive:  
            break
        chunk_storage.append(receive)
    
    print(chunk_storage)
    hex_result = ','.join([chunk.hex() for chunk in chunk_storage])
    print(hex_result)
    """
