"""Signal-level tests: decoding via DBC, value ranges, multiplexing."""

from __future__ import annotations

import pytest

from test_framework.can_bus import CanTestBus
from test_framework.dbc_helper import DbcHelper


def test_engine_rpm_in_realistic_range(
    can_bus: CanTestBus, dbc: DbcHelper, config, simulator_warmup
) -> None:
    """RPM must be a non-negative, reasonable engine speed."""
    arb_id = config["ecu"]["messages"]["EngineData"]["arbitration_id"]
    msg = can_bus.wait_for_message(arb_id, timeout_s=2.0)
    assert msg is not None
    rpm = dbc.decode_signal(msg, "EngineRPM")
    assert 0 <= rpm <= 8000, f"RPM {rpm} out of plausible range [0, 8000]"


def test_coolant_temp_in_range(
    can_bus: CanTestBus, dbc: DbcHelper, config, simulator_warmup
) -> None:
    """Coolant temperature must be in physical plausible range."""
    arb_id = config["ecu"]["messages"]["EngineData"]["arbitration_id"]
    msg = can_bus.wait_for_message(arb_id, timeout_s=2.0)
    assert msg is not None
    temp = dbc.decode_signal(msg, "CoolantTemp")
    assert -40 <= temp <= 150, f"Coolant temp {temp}°C out of range"


@pytest.mark.parametrize(
    "signal_name,min_val,max_val",
    [
        ("EngineRPM", 0, 8000),
        ("CoolantTemp", -40, 150),
        ("EngineLoad", 0, 100),
        ("OilPressure", 0, 1000),
    ],
)
def test_engine_signals_within_bounds(
    can_bus: CanTestBus,
    dbc: DbcHelper,
    config,
    signal_name,
    min_val,
    max_val,
    simulator_warmup,
) -> None:
    """All key engine signals must decode within their physical bounds."""
    arb_id = config["ecu"]["messages"]["EngineData"]["arbitration_id"]
    msg = can_bus.wait_for_message(arb_id, timeout_s=2.0)
    assert msg is not None
    value = dbc.decode_signal(msg, signal_name)
    assert (
        min_val <= value <= max_val
    ), f"{signal_name}={value} out of [{min_val}, {max_val}]"


def test_multiplexed_signals_decode(
    can_bus: CanTestBus, dbc: DbcHelper, config, simulator_warmup
) -> None:
    """Both multiplexer values (0 and 1) should be observed over time."""
    arb_id = config["ecu"]["messages"]["DiagnosticInfo"]["arbitration_id"]
    # Collect for 3 seconds — covers at least 6 cycles of 500ms
    msgs = can_bus.collect_messages(duration_s=3.0, filter_ids={arb_id})
    assert len(msgs) >= 3, f"Only {len(msgs)} DiagnosticInfo frames in 3s"

    mux_values_seen = set()
    for msg in msgs:
        decoded = dbc.decode(msg)
        mux_values_seen.add(decoded["MuxId"])

    assert mux_values_seen == {
        0,
        1,
    }, f"Expected to see both mux values 0 and 1, saw {mux_values_seen}"
