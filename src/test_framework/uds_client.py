"""UDS test client built on udsoncan + pure-Python ISO-TP."""

from __future__ import annotations

from typing import Optional

import can
import isotp
from udsoncan import DidCodec
from udsoncan.client import Client
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.services import DiagnosticSessionControl

from utils.logger import get_logger


class AsciiCodec(DidCodec):
    """DID codec for ASCII string identifiers (e.g., VIN, SW version)."""

    def __init__(self, length: int) -> None:
        self.length = length

    def encode(self, val: str) -> bytes:
        return val.encode("ascii").ljust(self.length, b"\x00")

    def decode(self, payload: bytes) -> str:
        return payload.decode("ascii").rstrip("\x00")

    def __len__(self) -> int:
        return self.length


class UdsTestClient:
    """Convenience wrapper around udsoncan.Client for tests."""

    DEFAULT_DIDS = {
        0xF190: AsciiCodec(17),  # VIN
        0xF195: AsciiCodec(9),  # SW version
        0xF18C: AsciiCodec(10),  # Serial number
        0xFFFF: AsciiCodec(1),  # Used in negative tests
    }

    def __init__(
        self,
        channel: str,
        bitrate: int,
        request_id: int,
        response_id: int,
        request_timeout: float = 2.0,
    ) -> None:
        self.log = get_logger("test.uds")
        self._bus = can.Bus(interface="socketcan", channel=channel, bitrate=bitrate)
        addr = isotp.Address(
            isotp.AddressingMode.Normal_11bits, txid=request_id, rxid=response_id
        )
        stack = isotp.CanStack(self._bus, address=addr)
        connection = PythonIsoTpConnection(stack)
        self._client = Client(
            connection,
            request_timeout=request_timeout,
            config={
                "data_identifiers": dict(self.DEFAULT_DIDS),
                "exception_on_negative_response": True,
                "exception_on_invalid_response": True,
            },
        )
        self._client.open()
        self.log.info("UDS client opened: req=0x%X resp=0x%X", request_id, response_id)

    def close(self) -> None:
        try:
            self._client.close()
        finally:
            self._bus.shutdown()
        self.log.info("UDS client closed")

    @property
    def client(self) -> Client:
        """Access underlying udsoncan.Client (for advanced use)."""
        return self._client

    def read_did(self, did: int) -> bytes:
        response = self._client.read_data_by_identifier(did)
        return response.service_data.values[did]

    def change_to_extended_session(self):
        return self._client.change_session(
            DiagnosticSessionControl.Session.extendedDiagnosticSession
        )

    def change_to_default_session(self):
        return self._client.change_session(
            DiagnosticSessionControl.Session.defaultSession
        )

    def tester_present(self) -> None:
        self._client.tester_present()

    def __enter__(self) -> "UdsTestClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
