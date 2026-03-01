    def _scan(self, timeout=5):
        """Scan for BLE devices directly via firmware."""
        from base64 import b64decode
        
        # Pause any ongoing operation
        if self.bridge.scanning:
            self.bridge._send_cmd([0x11, 0])
            self.bridge.scanning = False
        time.sleep(0.1)
        
        # Set advertising channel 37 with advertising AA (like Sniffle initiator)
        self.bridge._send_cmd([0x10, 37] + list(struct.pack("<L", 0x8E89BED6)) + [0] + list(struct.pack("<L", 0x555555)))
        time.sleep(0.05)
        
        # Pause after done (like Sniffle)
        self.bridge._send_cmd([0x11, 1])
        time.sleep(0.05)
        
        # Set MAC filter for target
        # self.bridge._send_cmd([0x13] + list(addr) + [1 if addr_type else 0])
        time.sleep(0.05)
        
        # Set our own random static address
        our_addr = [randrange(256) for _ in range(6)]
        our_addr[5] |= 0xC0
        self.bridge._send_cmd([0x1B, 1] + our_addr)
        time.sleep(0.05)
        
        # Start scan mode
        self.bridge._send_cmd([0x22])
        self.bridge.scanning = True
        
        devices = {}
        rx_buf = b""
        start = time.time()
        
        while time.time() - start < timeout:
            if self.bridge.ser.in_waiting > 0:
                rx_buf += self.bridge.ser.read(self.bridge.ser.in_waiting)
            
            while b"\r\n" in rx_buf:
                pos = rx_buf.find(b"\r\n")
                line = rx_buf[:pos]
                rx_buf = rx_buf[pos+2:]
                
                if len(line) >= 4 and len(line) % 4 == 0:
                    try:
                        data = b64decode(line)
                        if len(data) >= 2 and data[1] == 0x10:
                            mb = data[2:]
                            if len(mb) >= 10:
                                body = mb[10:]
                                pkt_len = (mb[4] | (mb[5] << 8)) & 0x7FFF
                                chan = mb[9] & 0x3F
                                if chan >= 37 and len(body) == pkt_len:
                                    pdu_type = body[0] & 0x0F
                                    if pdu_type in (0, 1):
                                        addr = body[2:8][::-1].hex()
                                        addr_fmt = ":".join([addr[i:i+2] for i in range(0, 12, 2)])
                                        rssi = mb[8] if mb[8] < 128 else mb[8] - 256
                                        tx_type = (body[0] >> 6) & 0x01
                                        if addr_fmt not in devices or devices[addr_fmt]["rssi"] < rssi:
                                            devices[addr_fmt] = {"rssi": rssi, "addr_type": tx_type}
