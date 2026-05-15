"""Base class for ECU simulators."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import can

from utils.logger import get_logger


@dataclass
class PeriodicMessage:
    """Configuration for a periodic CAN message."""

    arbitration_id: int
    period_s: float
    is_extended_id: bool = False
    task: Optional[can.broadcastmanager.CyclicSendTaskABC] = field(
        default=None, repr=False
    )


class BaseECU(ABC):
    """Abstract base for ECU simulators.

    Subclasses define which periodic messages to send and how to react to incoming
    frames by overriding `_build_payload` and `_on_message_received`.
    """

    def __init__(
        self, name: str, channel: str = "vcan0", bitrate: int = 500_000
    ) -> None:
        self.name = name
        self.channel = channel
        self.bitrate = bitrate
        self.log = get_logger(f"ecu.{name}")
        self._bus: Optional[can.BusABC] = None
        self._notifier: Optional[can.Notifier] = None
        self._periodic: dict[int, PeriodicMessage] = {}
        self._running = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Open the bus, schedule periodic messages, start listener."""
        if self._running.is_set():
            self.log.warning("ECU already running, ignoring start()")
            return

        self.log.info(
            "Starting ECU on channel=%s bitrate=%d", self.channel, self.bitrate
        )
        self._bus = can.Bus(
            interface="socketcan", channel=self.channel, bitrate=self.bitrate
        )
        self._notifier = can.Notifier(self._bus, [self._dispatch_message])

        for pm in self._periodic.values():
            self._schedule(pm)

        self._running.set()
        self.log.info("ECU started with %d periodic message(s)", len(self._periodic))

    def stop(self) -> None:
        """Stop notifier, cancel periodic tasks, close bus."""
        if not self._running.is_set():
            return

        self.log.info("Stopping ECU")
        for pm in self._periodic.values():
            if pm.task is not None:
                pm.task.stop()
                pm.task = None

        if self._notifier is not None:
            self._notifier.stop()
            self._notifier = None

        if self._bus is not None:
            self._bus.shutdown()
            self._bus = None

        self._running.clear()
        self.log.info("ECU stopped")

    def __enter__(self) -> "BaseECU":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def register_periodic(
        self, arbitration_id: int, period_s: float, is_extended_id: bool = False
    ) -> None:
        """Register a periodic message to be sent once ECU is started."""
        self._periodic[arbitration_id] = PeriodicMessage(
            arbitration_id=arbitration_id,
            period_s=period_s,
            is_extended_id=is_extended_id,
        )

    def _schedule(self, pm: PeriodicMessage) -> None:
        """Internal: create cyclic send task with current payload."""
        if self._bus is None:
            raise RuntimeError("Bus not initialized")

        msg = can.Message(
            arbitration_id=pm.arbitration_id,
            data=self._build_payload(pm.arbitration_id),
            is_extended_id=pm.is_extended_id,
        )
        pm.task = can.BusABC._send_periodic_internal(self._bus, msg, period=pm.period_s)
        self.log.debug("Scheduled 0x%X every %.3fs", pm.arbitration_id, pm.period_s)

    def refresh_payload(self, arbitration_id: int) -> None:
        """Rebuild the payload of a periodic message and apply to running task."""
        with self._lock:
            pm = self._periodic.get(arbitration_id)
            if pm is None or pm.task is None:
                return
            new_data = self._build_payload(arbitration_id)
            new_msg = can.Message(
                arbitration_id=arbitration_id,
                data=new_data,
                is_extended_id=pm.is_extended_id,
            )
            pm.task.modify_data(new_msg)

    def _dispatch_message(self, msg: can.Message) -> None:
        """Notifier callback — forwards incoming frames to subclass handler."""
        try:
            self._on_message_received(msg)
        except Exception as exc:
            self.log.exception(
                "Error handling message 0x%X: %s", msg.arbitration_id, exc
            )

    @abstractmethod
    def _build_payload(self, arbitration_id: int) -> bytes:
        """Return current payload for given periodic message ID."""
        ...

    def _on_message_received(self, msg: can.Message) -> None:
        """Override to handle incoming frames. Default: ignore."""
        return None

    def send_frame(
        self, arbitration_id: int, data: bytes, is_extended_id: bool = False
    ) -> None:
        """Send a one-shot frame (e.g., diagnostic response)."""
        if self._bus is None:
            raise RuntimeError("ECU not started")
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=is_extended_id,
        )
        self._bus.send(msg)
