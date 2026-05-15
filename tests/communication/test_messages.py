"""Communication-layer tests: frame presence, DLC, cycle time."""

from __future__ import annotations

import pytest

from test_framework.can_bus import CanTestBus


@pytest.mark.smoke
def test_engine_data_appears(can_bus: CanTestBus, config) -> None:
    """EngineData (0x100) should appear within 1 second of bus open."""
    arb_id = config["ecu"]["messages"]["EngineData"]["arbitration_id"]
    msg = can_bus.wait_for_message(arb_id, timeout_s=1.0)
    assert msg is not None, f"No EngineData (0x{arb_id:X}) received within 1s"


@pytest.mark.smoke
@pytest.mark.parametrize(
    "message_name", ["EngineData", "VehicleStatus", "DiagnosticInfo"]
)
def test_periodic_message_present(can_bus: CanTestBus, config, message_name) -> None:
    """All three periodic messages should be observable."""
    arb_id = config["ecu"]["messages"][message_name]["arbitration_id"]
    msg = can_bus.wait_for_message(arb_id, timeout_s=2.0)
    assert msg is not None, f"{message_name} (0x{arb_id:X}) not received within 2s"


@pytest.mark.parametrize(
    "message_name", ["EngineData", "VehicleStatus", "DiagnosticInfo"]
)
def test_message_dlc(can_bus: CanTestBus, config, message_name) -> None:
    """Each frame must carry the expected number of bytes."""
    msg_cfg = config["ecu"]["messages"][message_name]
    arb_id = msg_cfg["arbitration_id"]
    expected_dlc = msg_cfg["dlc"]

    msg = can_bus.wait_for_message(arb_id, timeout_s=2.0)
    assert msg is not None, f"{message_name} not received"
    assert (
        len(msg.data) == expected_dlc
    ), f"{message_name}: expected DLC={expected_dlc}, got {len(msg.data)}"


@pytest.mark.regression
@pytest.mark.parametrize(
    "message_name", ["EngineData", "VehicleStatus", "DiagnosticInfo"]
)
def test_cycle_time(can_bus: CanTestBus, config, message_name) -> None:
    """Mean cycle time must be within tolerance of expected period."""
    msg_cfg = config["ecu"]["messages"][message_name]
    arb_id = msg_cfg["arbitration_id"]
    expected = msg_cfg["expected_cycle_s"]
    tolerance = msg_cfg["cycle_tolerance"]

    # Sample for enough time to gather solid statistics
    sample_duration = max(2.0, expected * 20)
    stats = can_bus.get_cycle_stats(arb_id, duration_s=sample_duration)

    lower = expected * (1 - tolerance)
    upper = expected * (1 + tolerance)

    assert lower <= stats.mean_s <= upper, (
        f"{message_name} cycle out of tolerance:\n"
        f"  Expected: {expected*1000:.1f} ms (±{tolerance*100:.0f}%)\n"
        f"  Allowed range: [{lower*1000:.1f}, {upper*1000:.1f}] ms\n"
        f"  Measured: {stats}"
    )
