"""Minimal UDS server using pure-Python ISO-TP (isotp.CanStack).

No dependency on the can-isotp kernel module — works on any system
with python-can and the isotp pip package.
"""

from __future__ import annotations

import threading
import time
from enum import IntEnum
from typing import Optional

import can
import isotp

from utils.logger import get_logger


class UDSService(IntEnum):
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    READ_DATA_BY_IDENTIFIER = 0x22
    CLEAR_DTC = 0x14
    READ_DTC = 0x19
    TESTER_PRESENT = 0x3E


class NRC(IntEnum):
    SERVICE_NOT_SUPPORTED = 0x11
    SUBFUNCTION_NOT_SUPPORTED = 0x12
    INCORRECT_MESSAGE_LENGTH = 0x13
    CONDITIONS_NOT_CORRECT = 0x22
    REQUEST_OUT_OF_RANGE = 0x31


class DiagnosticSession(IntEnum):
    DEFAULT = 0x01
    PROGRAMMING = 0x02
    EXTENDED = 0x03


class UDSServer:
    """Minimal UDS server over pure-Python ISO-TP."""

    SESSION_TIMEOUT_S = 5.0

    def __init__(
        self,
        channel: str = "vcan0",
        bitrate: int = 500_000,
        rx_id: int = 0x7E0,
        tx_id: int = 0x7E8,
    ) -> None:
        self.log = get_logger("uds.server")
        self.channel = channel
        self.bitrate = bitrate
        self.rx_id = rx_id
        self.tx_id = tx_id

        self._bus: Optional[can.BusABC] = None
        self._stack: Optional[isotp.CanStack] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._session = DiagnosticSession.DEFAULT
        self._last_request_time = time.monotonic()
        self._state_lock = threading.Lock()

        self._data_by_did: dict[int, bytes] = {
            0xF190: b"WBA12345678901234",
            0xF195: b"SW_v1.2.3",
            0xF18C: b"ECU-SN-001",
        }
        self._dtcs: dict[int, int] = {}

    def start(self) -> None:
        self.log.info(
            "Starting UDS server: rx=0x%X tx=0x%X on %s",
            self.rx_id,
            self.tx_id,
            self.channel,
        )
        try:
            self._bus = can.Bus(
                interface="socketcan", channel=self.channel, bitrate=self.bitrate
            )
            addr = isotp.Address(
                isotp.AddressingMode.Normal_11bits, txid=self.tx_id, rxid=self.rx_id
            )
            self._stack = isotp.CanStack(self._bus, address=addr)
        except Exception:
            self.log.exception("Failed to initialize UDS ISO-TP stack")
            raise

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve, daemon=True, name="uds-server"
        )
        self._thread.start()
        self.log.info("UDS server started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._bus is not None:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None
        self._stack = None
        self.log.info("UDS server stopped")

    def trigger_dtc(self, dtc_id: int, status: int = 0x09) -> None:
        with self._state_lock:
            self._dtcs[dtc_id] = status
        self.log.info("DTC 0x%06X triggered (status=0x%02X)", dtc_id, status)

    def _serve(self) -> None:
        assert self._stack is not None
        self.log.info("UDS server loop started")
        while not self._stop.is_set():
            self._stack.process()

            if self._stack.available():
                data = self._stack.recv()
                self._last_request_time = time.monotonic()
                self.log.info("UDS RX: %s", data.hex())

                try:
                    response = self._handle_request(data)
                except Exception:
                    self.log.exception("Handler crashed")
                    response = self._nrc(
                        data[0] if data else 0, NRC.CONDITIONS_NOT_CORRECT
                    )

                if response is not None:
                    self.log.info("UDS TX: %s", response.hex())
                    try:
                        self._stack.send(response)
                    except Exception:
                        self.log.exception("Failed to send UDS response")
            else:
                self._check_session_timeout()
                time.sleep(0.01)

    def _check_session_timeout(self) -> None:
        with self._state_lock:
            if self._session != DiagnosticSession.DEFAULT:
                if time.monotonic() - self._last_request_time > self.SESSION_TIMEOUT_S:
                    self.log.info("S3 timeout: back to default session")
                    self._session = DiagnosticSession.DEFAULT

    def _handle_request(self, data: bytes) -> Optional[bytes]:
        if not data:
            return None
        sid = data[0]
        if sid == UDSService.DIAGNOSTIC_SESSION_CONTROL:
            return self._handle_session_control(data)
        if sid == UDSService.READ_DATA_BY_IDENTIFIER:
            return self._handle_read_did(data)
        if sid == UDSService.CLEAR_DTC:
            return self._handle_clear_dtc(data)
        if sid == UDSService.READ_DTC:
            return self._handle_read_dtc(data)
        if sid == UDSService.TESTER_PRESENT:
            return self._handle_tester_present(data)
        return self._nrc(sid, NRC.SERVICE_NOT_SUPPORTED)

    def _handle_session_control(self, data: bytes) -> bytes:
        if len(data) < 2:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        subfunc = data[1] & 0x7F
        try:
            new_session = DiagnosticSession(subfunc)
        except ValueError:
            return self._nrc(data[0], NRC.SUBFUNCTION_NOT_SUPPORTED)
        with self._state_lock:
            self._session = new_session
        self.log.info("Session: %s", new_session.name)
        return bytes([0x50, subfunc, 0x00, 0x32, 0x01, 0xF4])

    def _handle_read_did(self, data: bytes) -> bytes:
        if len(data) < 3:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        did = (data[1] << 8) | data[2]
        with self._state_lock:
            value = self._data_by_did.get(did)
        if value is None:
            return self._nrc(data[0], NRC.REQUEST_OUT_OF_RANGE)
        return bytes([0x62, data[1], data[2]]) + value

    def _handle_clear_dtc(self, data: bytes) -> bytes:
        if len(data) < 4:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        with self._state_lock:
            self._dtcs.clear()
        return bytes([0x54])

    def _handle_read_dtc(self, data: bytes) -> bytes:
        if len(data) < 3:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        if data[1] != 0x02:
            return self._nrc(data[0], NRC.SUBFUNCTION_NOT_SUPPORTED)
        with self._state_lock:
            dtcs = list(self._dtcs.items())
        response = bytearray([0x59, 0x02, 0xFF])
        for dtc_id, status in dtcs:
            response.append((dtc_id >> 16) & 0xFF)
            response.append((dtc_id >> 8) & 0xFF)
            response.append(dtc_id & 0xFF)
            response.append(status)
        return bytes(response)

    def _handle_tester_present(self, data: bytes) -> Optional[bytes]:
        if len(data) < 2:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        if (data[1] & 0x80) != 0:
            return None
        return bytes([0x7E, data[1] & 0x7F])

    @staticmethod
    def _nrc(sid: int, code: NRC) -> bytes:
        return bytes([0x7F, sid, int(code)])
