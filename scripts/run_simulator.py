"""Entry point for running the ECU simulator standalone."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

# Allow running from project root without install
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ecu_simulator.engine_ecu import EngineECU
from utils.logger import get_logger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="vcan0")
    parser.add_argument("--bitrate", type=int, default=500_000)
    parser.add_argument(
        "--dbc",
        default=str(Path(__file__).resolve().parents[1] / "dbc" / "engine_ecu.dbc"),
    )
    args = parser.parse_args()

    log = get_logger("main")
    ecu = EngineECU(dbc_path=Path(args.dbc), channel=args.channel, bitrate=args.bitrate)

    def shutdown(signum, frame):
        log.info("Received signal %s, shutting down", signum)
        ecu.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    ecu.start()
    log.info("Simulator running. Press Ctrl+C to stop.")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
