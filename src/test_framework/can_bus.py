"""High-level CAN bus wrapper for tests.

Provides convenience methods on top of python-can for collecting frames,
waiting for specific messages, and computing timing statistics.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import can

from utils.logger import get_logger


@dataclass
class CycleStats:
    """Statistics about message cycle timing."""

    arbitration_id: int
    sample_count: int
    mean_s: float
    min_s: float
    max_s: float
    jitter_s: float  # max - min

    def __str__(self) -> str:
        return (
            f"ID=0x{self.arbitration_id:X} samples={self.sample_count} "
            f"mean={self.mean_s*1000:.1f}ms "
            f"min={self.min_s*1000:.1f}ms max={self.max_s*1000:.1f}ms "
            f"jitter={self.jitter_s*1000:.1f}ms"
        )


class CanTestBus:
    """Test-oriented wrapper around python-can Bus."""

    def __init__(
        self, channel: str, bitrate: int, interface: str = "socketcan"
    ) -> None:
        self.log = get_logger("test.bus")
        self._bus = can.Bus(interface=interface, channel=channel, bitrate=bitrate)
        self.log.info("Bus opened: %s @ %d", channel, bitrate)

    def shutdown(self) -> None:
        self._bus.shutdown()
        self.log.info("Bus closed")

    @property
    def raw_bus(self) -> can.BusABC:
        """Access underlying python-can bus (for advanced usage)."""
        return self._bus

    def wait_for_message(
        self, arbitration_id: int, timeout_s: float = 1.0
    ) -> Optional[can.Message]:
        """Wait until a frame with given ID arrives. Returns None on timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            msg = self._bus.recv(timeout=remaining)
            if msg is not None and msg.arbitration_id == arbitration_id:
                return msg
        return None

    def collect_messages(
        self, duration_s: float, filter_ids: Optional[set[int]] = None
    ) -> list[can.Message]:
        """Collect all frames over a window. Optionally filter by IDs."""
        messages: list[can.Message] = []
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            msg = self._bus.recv(timeout=min(remaining, 0.1))
            if msg is None:
                continue
            if filter_ids is None or msg.arbitration_id in filter_ids:
                messages.append(msg)
        return messages

    def get_cycle_stats(
        self, arbitration_id: int, duration_s: float = 2.0, min_samples: int = 5
    ) -> CycleStats:
        """Measure cycle time for a periodic message."""
        msgs = self.collect_messages(duration_s, filter_ids={arbitration_id})
        if len(msgs) < min_samples + 1:
            raise RuntimeError(
                f"Not enough samples for 0x{arbitration_id:X}: "
                f"got {len(msgs)}, need at least {min_samples + 1}"
            )

        deltas = [
            msgs[i + 1].timestamp - msgs[i].timestamp for i in range(len(msgs) - 1)
        ]
        return CycleStats(
            arbitration_id=arbitration_id,
            sample_count=len(deltas),
            mean_s=sum(deltas) / len(deltas),
            min_s=min(deltas),
            max_s=max(deltas),
            jitter_s=max(deltas) - min(deltas),
        )

    def send(
        self, arbitration_id: int, data: bytes, is_extended_id: bool = False
    ) -> None:
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=is_extended_id,
        )
        self._bus.send(msg)

    def __enter__(self) -> "CanTestBus":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown()
