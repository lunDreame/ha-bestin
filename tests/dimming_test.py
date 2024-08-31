import socket
import logging

logging.basicConfig(level=logging.ERROR)

class SocketClient:
    def __init__(self, server_address, port):
        self.server_address = server_address
        self.port = port
        self.sock = None
        self.constant_packet_length = 10
    
    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.server_address, self.port))
            print(f"Connected to {self.server_address} on port {self.port}")
        except socket.error as e:
            logging.error(f"Connection error: {e}")
            self.sock = None

    def _receive_socket(self):
        def recv_exactly(n):
            data = b''
            while len(data) < n:
                chunk = self.sock.recv(n - len(data))
                if not chunk:
                    raise socket.error("Connection closed")
                data += chunk
            return data

        packet = b''
        try:
            while True:
                while True:
                    initial_data = self.sock.recv(1)
                    if not initial_data:
                        return b''
                    packet += initial_data
                    if 0x02 in packet:
                        start_index = packet.index(0x02)
                        packet = packet[start_index:]
                        break
                
                if len(packet) < 3:
                    packet += recv_exactly(3 - len(packet))

                if (
                    packet[1] not in [0x31, 0x32, 0x33, 0x34]
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

    def reconnect(self):
        if self.sock:
            self.sock.close()
        self.connect()

    def checksum(self, data):
        checksum = 3
        for byte in data[:-1]:
            checksum ^= byte
            checksum = (checksum + 1) & 0xFF
        return checksum == data[-1]
    
    def receive_data(self):
        try:
            while True:
                data = self._receive_socket()
                try:
                    if not self.checksum(data):
                        continue
                    
                    if data[1] == 0x33 and data[3] == 0x91:
                        self.parse_data(data)
                        pass
                    
                    if data[1] == 0x34 and data[3] == 0x91:
                        pass
                        #print(' '.join(f'{byte:02X}' for byte in data))
                        #print(f"[34]  LIGHT:: \n 1. IS_ON: {data[18] == 0x01}, DIMMING_LEVEL: {data[19]}, COLOR_TEMPERATURE: {data[20]}")
                        #print(f"[34]  OUTLET:: \n 1. IS_ON: {data[44] == 0x21}, CURRENT_POWER: {int.from_bytes(data[52:54], byteorder="big")/10} \n 2. IS_ON: {data[58] == 0x21}, CURRENT_POWER: {int.from_bytes(data[66:68], byteorder="big")/10}")
                    if data[1] == 0x33 and data[3] == 0x91:
                        pass
                        #print(' '.join(f'{byte:02X}' for byte in data))
                        #print(f"[33]  LIGHT:: \n 1. IS_ON: {data[18] == 0x01}, DIMMING_LEVEL: {data[19]}, COLOR_TEMPERATURE: {data[20]}")
                        #print(f"[33]  OUTLET:: \n 1. IS_ON: {data[31] == 0x21}, CURRENT_POWER: {int.from_bytes(data[39:41], byteorder="big")/10} \n 2. IS_ON: {data[45] == 0x21}, CURRENT_POWER: {int.from_bytes(data[53:55], byteorder="big")/10}")
                    if data[1] == 0x31 and data[3] == 0x91:
                        pass
                        #print(' '.join(f'{byte:02X}' for byte in data))
                except IndexError:
                    continue
        except KeyboardInterrupt:
            logging.warning("Interrupted by user.")
        #finally:
        #    if self.sock:
        #        self.sock.close()

    def parse_data(self, data):
        print(' '.join(f'{byte:02X}' for byte in data))
        rid = data[1] & 0x0F

        if rid % 2 == 0:
            lcnt, ocnt = data[10] & 0x0F, data[11]
            base_cnt = ocnt
        else:
            lcnt, ocnt = data[10], data[11]
            base_cnt = lcnt
        #print(f"[2]  LIGHT COUNT: {lcnt}, OUTLET_COUNT: {ocnt}")
        
        lsi = 18
        osi = lsi + (base_cnt * 13)
        #print(f"[2]  LIGHT_START_INDEX: {lsi}, OUTLET_START_INDEX: {osi}")
        
        for i in range(lcnt):
            is_on = data[lsi] == 0x01
            dimming_level = data[lsi + 1]
            color_temperature = data[lsi + 2]
            print(f"LIGHT:: \n {rid}/{i}. IS_ON: {is_on}, DIMMING_LEVEL: {dimming_level}, COLOR_TEMPERATURE: {color_temperature}")
            lsi += 13
        
        for i in range(ocnt):
            is_on = data[osi] == 0x21
            idx = osi + 8
            idx2 = osi + 10
            current_power = int.from_bytes(data[idx:idx2], byteorder="big") / 10
            print(f"OUTLET:: \n {rid}/{i}. IS_ON: {is_on}, CURRENT_POWER: {current_power}")
            osi += 14

if __name__ == "__main__":
    client = SocketClient('192.168.0.27', 8899)
    client.connect()
    client.receive_data()
