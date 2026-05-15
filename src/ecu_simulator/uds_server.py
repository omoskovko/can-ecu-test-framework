"""Minimal UDS server using can-isotp."""

from __future__ import annotations

import threading
import time
from enum import IntEnum
from typing import Callable, Optional

import isotp

from utils.logger import get_logger


class UDSService(IntEnum):
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    READ_DATA_BY_IDENTIFIER = 0x22
    CLEAR_DTC = 0x14
    READ_DTC = 0x19
    TESTER_PRESENT = 0x3E


class NRC(IntEnum):
    """Negative Response Codes (subset)."""

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
    """Lightweight UDS server. Designed for testing, not full ISO 14229 conformance."""

    SESSION_TIMEOUT_S = 5.0  # S3 timer

    def __init__(
        self, channel: str = "vcan0", rx_id: int = 0x7E0, tx_id: int = 0x7E8
    ) -> None:
        self.log = get_logger("uds.server")
        self.channel = channel
        self.rx_id = rx_id
        self.tx_id = tx_id

        self._stack: Optional[isotp.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._session = DiagnosticSession.DEFAULT
        self._last_request_time = time.monotonic()
        self._state_lock = threading.Lock()

        # In-memory storage
        self._data_by_did: dict[int, bytes] = {
            0xF190: b"WBA12345678901234",  # VIN (17 chars)
            0xF195: b"SW_v1.2.3",  # SW version
            0xF18C: b"ECU-SN-001",  # Serial number
        }
        self._dtcs: dict[int, int] = {}  # {dtc_id: status_mask}

    def start(self) -> None:
        self.log.info("Starting UDS server: rx=0x%X tx=0x%X", self.rx_id, self.tx_id)
        self._stack = isotp.socket()
        self._stack.set_fc_opts(stmin=0, bs=8)
        self._stack.bind(self.channel, isotp.Address(rxid=self.rx_id, txid=self.tx_id))
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        self.log.info("UDS server stopped")

    def trigger_dtc(self, dtc_id: int, status: int = 0x09) -> None:
        """Inject a DTC (e.g. to simulate a fault)."""
        with self._state_lock:
            self._dtcs[dtc_id] = status
        self.log.info("DTC 0x%06X triggered (status=0x%02X)", dtc_id, status)

    def _serve(self) -> None:
        self._stack.settimeout(0.2)
        while not self._stop.is_set():
            try:
                data = self._stack.recv()
            except TimeoutError:
                self._check_session_timeout()
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self.log.error("isotp recv error: %s", exc)
                break

            if not data:
                continue

            self._last_request_time = time.monotonic()
            self.log.debug("RX: %s", data.hex())

            try:
                response = self._handle_request(data)
            except Exception:
                self.log.exception("Handler crash")
                response = self._nrc(
                    data[0] if data else 0x00, NRC.CONDITIONS_NOT_CORRECT
                )

            if response is not None:
                self.log.debug("TX: %s", response.hex())
                self._stack.send(response)

    def _check_session_timeout(self) -> None:
        with self._state_lock:
            if self._session != DiagnosticSession.DEFAULT:
                if time.monotonic() - self._last_request_time > self.SESSION_TIMEOUT_S:
                    self.log.info("S3 timeout: returning to default session")
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
        self.log.info("Session changed to: %s", new_session.name)
        # Positive response: 0x50 + subfunc + P2 + P2* (timing params)
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
        self.log.info("All DTCs cleared")
        return bytes([0x54])

    def _handle_read_dtc(self, data: bytes) -> bytes:
        if len(data) < 3:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        subfunc = data[1]
        # Only support reportDTCByStatusMask (0x02)
        if subfunc != 0x02:
            return self._nrc(data[0], NRC.SUBFUNCTION_NOT_SUPPORTED)

        with self._state_lock:
            dtcs = list(self._dtcs.items())

        response = bytearray([0x59, 0x02, 0xFF])  # availability mask
        for dtc_id, status in dtcs:
            response.append((dtc_id >> 16) & 0xFF)
            response.append((dtc_id >> 8) & 0xFF)
            response.append(dtc_id & 0xFF)
            response.append(status)
        return bytes(response)

    def _handle_tester_present(self, data: bytes) -> bytes:
        if len(data) < 2:
            return self._nrc(data[0], NRC.INCORRECT_MESSAGE_LENGTH)
        suppress = (data[1] & 0x80) != 0
        if suppress:
            return None  # type: ignore
        return bytes([0x7E, data[1] & 0x7F])

    @staticmethod
    def _nrc(sid: int, code: NRC) -> bytes:
        return bytes([0x7F, sid, int(code)])
