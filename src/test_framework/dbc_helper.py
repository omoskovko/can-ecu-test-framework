"""Convenience wrapper around cantools for tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cantools
import can

from utils.logger import get_logger


class DbcHelper:
    """Wraps cantools database with friendlier API for tests."""

    def __init__(self, dbc_path: Path) -> None:
        self.log = get_logger("test.dbc")
        self._db = cantools.database.load_file(str(dbc_path))
        self.log.info(
            "DBC loaded: %s (%d messages)", dbc_path.name, len(self._db.messages)
        )

    def decode(self, msg: can.Message) -> dict[str, Any]:
        """Decode a CAN message into a dict of signal name -> value."""
        return self._db.decode_message(msg.arbitration_id, msg.data)

    def decode_signal(self, msg: can.Message, signal_name: str) -> Any:
        """Decode and return a single signal value."""
        decoded = self.decode(msg)
        if signal_name not in decoded:
            raise KeyError(
                f"Signal '{signal_name}' not in message 0x{msg.arbitration_id:X}. "
                f"Available: {list(decoded.keys())}"
            )
        return decoded[signal_name]

    def encode(self, message_name: str, signals: dict[str, Any]) -> bytes:
        """Encode signal dict into raw bytes for a named message."""
        return self._db.get_message_by_name(message_name).encode(signals)

    def get_message_id(self, message_name: str) -> int:
        return self._db.get_message_by_name(message_name).frame_id

    def get_signal_names(self, message_id: int) -> list[str]:
        msg = self._db.get_message_by_frame_id(message_id)
        return [sig.name for sig in msg.signals]
