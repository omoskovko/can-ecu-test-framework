import isotp

# Create ISO-TP socket on the "tester" side
# rxid=0x7E8 — listen for ECU responses, txid=0x7E0 — send requests
s = isotp.socket()
s.bind("vcan0", isotp.Address(rxid=0x7E8, txid=0x7E0))

# 1) Read VIN
s.send(bytes([0x22, 0xF1, 0x90]))
print(s.recv())
# Expected: b'\x62\xf1\x90WBA12345678901234'

# 2) Read SW version
s.send(bytes([0x22, 0xF1, 0x95]))
print(s.recv())
# Expected: b'\x62\xf1\x95SW_v1.2.3'

# 3) Transition to extended session
s.send(bytes([0x10, 0x03]))
print(s.recv())
# Expected: b'\x50\x03\x00\x32\x01\xf4'

# 4) Negative response — unknown DID
s.send(bytes([0x22, 0xFF, 0xFF]))
print(s.recv())
# Expected: b'\x7f\x22\x31'  (NRC 0x31 = requestOutOfRange)

# 5) Tester present
s.send(bytes([0x3E, 0x00]))
print(s.recv())
# Expected: b'\x7e\x00'

s.close()
