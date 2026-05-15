"""High-level UDS test via udsoncan - this is how Day 2 tests will look."""

import can
import isotp
from udsoncan.client import Client
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.exceptions import NegativeResponseException
from udsoncan.services import DiagnosticSessionControl


def main() -> None:
    bus = can.Bus(interface="socketcan", channel="vcan0", bitrate=500_000)
    addr = isotp.Address(isotp.AddressingMode.Normal_11bits, txid=0x7E0, rxid=0x7E8)
    stack = isotp.CanStack(bus, address=addr)
    conn = PythonIsoTpConnection(stack)

    # udsoncan очікує описи DID, щоб знати як їх кодувати/декодувати
    from udsoncan import DidCodec

    class AsciiCodec(DidCodec):
        def __init__(self, length: int):
            self.length = length

        def encode(self, val: str) -> bytes:
            return val.encode("ascii").ljust(self.length, b"\x00")

        def decode(self, payload: bytes) -> str:
            return payload.decode("ascii").rstrip("\x00")

        def __len__(self) -> int:
            return self.length

    config = {
        "data_identifiers": {
            0xF190: AsciiCodec(17),  # VIN
            0xF195: AsciiCodec(9),  # SW version "SW_v1.2.3"
            0xF18C: AsciiCodec(10),  # Serial number
        },
        "exception_on_negative_response": True,
        "exception_on_invalid_response": True,
    }

    with Client(conn, request_timeout=2, config=config) as client:
        print("=" * 60)
        print("Test 1: Read VIN (positive case)")
        print("=" * 60)
        response = client.read_data_by_identifier(0xF190)
        vin = response.service_data.values[0xF190]
        print(f"  VIN: {vin}")
        assert len(vin) == 17, f"VIN must be 17 chars, got {len(vin)}"
        print("  ✓ Length check passed")

        print()
        print("=" * 60)
        print("Test 2: Change to extended session")
        print("=" * 60)
        response = client.change_session(
            DiagnosticSessionControl.Session.extendedDiagnosticSession
        )
        print(
            f"  Session response received, P2 server max: {response.service_data.p2_server_max}"
        )
        print("  ✓ Session changed")

        print()
        print("=" * 60)
        print("Test 3: Read unknown DID (should raise NegativeResponse)")
        print("=" * 60)
        # тимчасово додамо DID, щоб udsoncan дозволив запит
        client.config["data_identifiers"][0xFFFF] = AsciiCodec(1)
        try:
            client.read_data_by_identifier(0xFFFF)
            print("  ✗ Expected NegativeResponseException but got success")
        except NegativeResponseException as e:
            print(
                f"  ✓ Got expected negative response: code=0x{e.response.code:02X} "
                f"({e.response.code_name})"
            )

        print()
        print("=" * 60)
        print("Test 4: TesterPresent")
        print("=" * 60)
        client.tester_present()
        print("  ✓ TesterPresent succeeded")

    bus.shutdown()
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
