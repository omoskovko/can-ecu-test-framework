"""Engine ECU simulator with realistic-ish dynamic signals."""

from __future__ import annotations

import math
import random
import threading
import time
from pathlib import Path
from typing import Optional

import can
import cantools

from ecu_simulator.base_ecu import BaseECU
from ecu_simulator.uds_server import UDSServer


class EngineECU(BaseECU):
    """Simulates an Engine Control Unit.

    Sends:
        - EngineData (0x100) every 100 ms with RPM/temp/load/oil pressure.
        - VehicleStatus (0x200) every 200 ms with speed/gear/handbrake.
        - DiagnosticInfo (0x300) every 500 ms with multiplexed fuel/battery data.
    """

    ENGINE_DATA_ID = 0x100
    VEHICLE_STATUS_ID = 0x200
    DIAGNOSTIC_INFO_ID = 0x300

    def __init__(
        self, dbc_path: Path, channel: str = "vcan0", bitrate: int = 500_000
    ) -> None:
        super().__init__(name="EngineECU", channel=channel, bitrate=bitrate)
        self._db = cantools.database.load_file(str(dbc_path))

        # Internal state
        self._rpm = 800.0  # idle
        self._coolant_temp = 20.0
        self._engine_load = 5.0
        self._oil_pressure = 250.0
        self._speed = 0.0
        self._gear = 0  # neutral
        self._handbrake = True
        self._fuel_level = 75.0
        self._fuel_consumption = 0.0
        self._battery_voltage = 12.6
        self._ambient_temp = 22.0
        self._mux_toggle = 0

        self._state_lock = threading.Lock()
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_stop = threading.Event()

        self.register_periodic(self.ENGINE_DATA_ID, period_s=0.1)
        self.register_periodic(self.VEHICLE_STATUS_ID, period_s=0.2)
        self.register_periodic(self.DIAGNOSTIC_INFO_ID, period_s=0.5)

        self._uds = UDSServer(channel=channel, rx_id=0x7E0, tx_id=0x7E8)

    def start(self) -> None:
        super().start()
        self._uds.start()
        self._sim_stop.clear()
        self._sim_thread = threading.Thread(target=self._simulate, daemon=True)
        self._sim_thread.start()

    def stop(self) -> None:
        self._sim_stop.set()
        if self._sim_thread is not None:
            self._sim_thread.join(timeout=2.0)
            self._sim_thread = None
        self._uds.stop()
        super().stop()

    # Public API for tests to drive state
    def trigger_dtc(self, dtc_id: int, status: int = 0x09) -> None:
        self._uds.trigger_dtc(dtc_id, status)

    def set_rpm(self, value: float) -> None:
        with self._state_lock:
            self._rpm = max(0.0, min(8000.0, value))
        self.refresh_payload(self.ENGINE_DATA_ID)

    def set_speed(self, value: float) -> None:
        with self._state_lock:
            self._speed = max(0.0, min(300.0, value))
        self.refresh_payload(self.VEHICLE_STATUS_ID)

    def set_gear(self, gear: int) -> None:
        with self._state_lock:
            self._gear = max(0, min(15, gear))
        self.refresh_payload(self.VEHICLE_STATUS_ID)

    # Simulation

    def _simulate(self) -> None:
        """Slowly evolve state to make signals 'breathe' over time."""
        t0 = time.monotonic()
        while not self._sim_stop.wait(0.1):
            t = time.monotonic() - t0
            with self._state_lock:
                self._rpm = 800 + 200 * math.sin(t * 0.5) + random.uniform(-30, 30)
                self._coolant_temp = min(90.0, self._coolant_temp + 0.02)
                self._engine_load = 10 + 5 * math.sin(t * 0.3)
                self._oil_pressure = 300 + 50 * math.sin(t * 0.7)
                self._battery_voltage = 12.6 + 0.4 * math.sin(t * 0.1)
                self._fuel_level = max(0.0, self._fuel_level - 0.001)

            self.refresh_payload(self.ENGINE_DATA_ID)
            self.refresh_payload(self.DIAGNOSTIC_INFO_ID)

    # Payload building via DBC

    def _build_payload(self, arbitration_id: int) -> bytes:
        with self._state_lock:
            if arbitration_id == self.ENGINE_DATA_ID:
                signals = {
                    "EngineRPM": self._rpm,
                    "CoolantTemp": self._coolant_temp,
                    "EngineLoad": self._engine_load,
                    "OilPressure": self._oil_pressure,
                }
            elif arbitration_id == self.VEHICLE_STATUS_ID:
                signals = {
                    "VehicleSpeed": self._speed,
                    "GearPosition": self._gear,
                    "HandbrakeOn": 1 if self._handbrake else 0,
                }
            elif arbitration_id == self.DIAGNOSTIC_INFO_ID:
                # Alternate multiplexed payload each cycle
                self._mux_toggle = 1 - self._mux_toggle
                if self._mux_toggle == 0:
                    signals = {
                        "MuxId": 0,
                        "FuelLevel": self._fuel_level,
                        "FuelConsumption": self._fuel_consumption,
                    }
                else:
                    signals = {
                        "MuxId": 1,
                        "BatteryVoltage": self._battery_voltage,
                        "AmbientTemp": self._ambient_temp,
                    }
            else:
                return bytes(8)

        message = self._db.get_message_by_frame_id(arbitration_id)
        return message.encode(signals)
