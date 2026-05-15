"""Raw ISO-TP socket test - lowest level UDS check."""

import isotp


def send_and_print(sock: isotp.socket, payload: bytes, label: str) -> None:
    print(f"\n→ {label}")
    print(f"  TX: {payload.hex()}")
    sock.send(payload)
    try:
        resp = sock.recv()
        print(f"  RX: {resp.hex()}")
        return resp
    except TimeoutError:
        print(f"  ✗ TIMEOUT")
        return None


def main() -> None:
    s = isotp.socket(timeout=2.0)
    # rxid тестера = txid сервера (0x7E8); txid тестера = rxid сервера (0x7E0)
    s.bind("vcan0", isotp.Address(rxid=0x7E8, txid=0x7E0))

    # 1) Read VIN
    resp = send_and_print(s, bytes([0x22, 0xF1, 0x90]), "ReadDataByIdentifier VIN")
    if resp:
        print(f"  VIN: {resp[3:].decode('ascii')}")

    # 2) Read Software Version
    resp = send_and_print(
        s, bytes([0x22, 0xF1, 0x95]), "ReadDataByIdentifier SW version"
    )
    if resp:
        print(f"  SW:  {resp[3:].decode('ascii')}")

    # 3) Extended session
    resp = send_and_print(s, bytes([0x10, 0x03]), "DiagnosticSessionControl: extended")
    if resp and resp[0] == 0x50:
        print(f"  Session 0x{resp[1]:02X} active")

    # 4) Unknown DID - should return NRC
    resp = send_and_print(
        s, bytes([0x22, 0xFF, 0xFF]), "ReadDataByIdentifier 0xFFFF (unknown)"
    )
    if resp and resp[0] == 0x7F:
        print(f"  NRC 0x{resp[2]:02X} (expected 0x31 = requestOutOfRange)")

    # 5) Tester present
    resp = send_and_print(s, bytes([0x3E, 0x00]), "TesterPresent")
    if resp:
        print(f"  Positive response: 0x{resp[0]:02X}")

    # 6) Read DTC
    resp = send_and_print(s, bytes([0x19, 0x02, 0xFF]), "ReadDTC by status mask")
    if resp:
        # response: [0x59, 0x02, mask, then 4 bytes per DTC]
        dtc_data = resp[3:]
        if not dtc_data:
            print(f"  No DTCs present")
        else:
            for i in range(0, len(dtc_data), 4):
                dtc_id = (dtc_data[i] << 16) | (dtc_data[i + 1] << 8) | dtc_data[i + 2]
                status = dtc_data[i + 3]
                print(f"  DTC 0x{dtc_id:06X} status=0x{status:02X}")

    s.close()


if __name__ == "__main__":
    main()
