"""Pure-Python ISO-TP test - no kernel isotp module needed."""

import time

import can
import isotp


def query(
    stack: isotp.CanStack, payload: bytes, label: str, timeout: float = 2.0
) -> bytes | None:
    print(f"\n→ {label}")
    print(f"  TX: {payload.hex()}")
    stack.send(payload)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stack.process()
        if stack.available():
            resp = stack.recv()
            print(f"  RX: {resp.hex()}")
            return resp
        time.sleep(0.01)

    print(f"  ✗ TIMEOUT")
    return None


def main() -> None:
    bus = can.Bus(interface="socketcan", channel="vcan0", bitrate=500_000)
    addr = isotp.Address(isotp.AddressingMode.Normal_11bits, txid=0x7E0, rxid=0x7E8)
    stack = isotp.CanStack(bus, address=addr)

    try:
        resp = query(stack, bytes([0x22, 0xF1, 0x90]), "Read VIN")
        if resp:
            print(f"  VIN: {resp[3:].decode('ascii')}")

        resp = query(stack, bytes([0x10, 0x03]), "Extended session")
        if resp:
            print(f"  Session changed: SID=0x{resp[0]:02X}")

        resp = query(stack, bytes([0x22, 0xFF, 0xFF]), "Unknown DID")
        if resp and resp[0] == 0x7F:
            print(f"  NRC: 0x{resp[2]:02X} (correct negative response)")
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
