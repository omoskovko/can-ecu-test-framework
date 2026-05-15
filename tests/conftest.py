"""Shared fixtures for all test modules."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from test_framework.can_bus import CanTestBus
from test_framework.dbc_helper import DbcHelper
from test_framework.uds_client import UdsTestClient

# --------------------------------------------------------------------------- #
#  CLI options
# --------------------------------------------------------------------------- #


def pytest_addoption(parser: pytest.Parser) -> None:
    """Custom CLI flags — allow overriding config path."""
    parser.addoption(
        "--test-config",
        action="store",
        default="config/test_config.yaml",
        help="Path to test configuration YAML",
    )


# --------------------------------------------------------------------------- #
#  Session-scoped fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def config(pytestconfig: pytest.Config) -> dict[str, Any]:
    """Load test configuration once per session."""
    config_path = Path(pytestconfig.getoption("--test-config"))
    if not config_path.is_absolute():
        # Resolve relative to project root (cwd when pytest runs)
        config_path = Path.cwd() / config_path
    with config_path.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def dbc(config: dict[str, Any]) -> DbcHelper:
    """Load DBC database once per session."""
    dbc_path = Path(config["dbc"]["path"])
    if not dbc_path.is_absolute():
        dbc_path = Path.cwd() / dbc_path
    return DbcHelper(dbc_path)


# --------------------------------------------------------------------------- #
#  Function-scoped fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def can_bus(config: dict[str, Any]) -> CanTestBus:
    """Fresh CAN bus connection per test (auto-shutdown)."""
    bus = CanTestBus(
        channel=config["bus"]["channel"],
        bitrate=config["bus"]["bitrate"],
        interface=config["bus"]["interface"],
    )
    yield bus
    bus.shutdown()


@pytest.fixture
def uds_client(config: dict[str, Any]) -> UdsTestClient:
    """Fresh UDS client per test (auto-close)."""
    client = UdsTestClient(
        channel=config["bus"]["channel"],
        bitrate=config["bus"]["bitrate"],
        request_id=config["uds"]["request_id"],
        response_id=config["uds"]["response_id"],
        request_timeout=config["uds"]["request_timeout_s"],
    )
    yield client
    client.close()


@pytest.fixture
def simulator_warmup(can_bus: CanTestBus, config: dict[str, Any]) -> None:
    """
    Ensures simulator is actively sending frames before tests run.

    Useful for tests that depend on a stable signal stream — waits up to 2s
    for at least one EngineData frame to confirm simulator is alive.
    """
    engine_data_id = config["ecu"]["messages"]["EngineData"]["arbitration_id"]
    msg = can_bus.wait_for_message(engine_data_id, timeout_s=2.0)
    if msg is None:
        pytest.fail(
            "Simulator is not sending EngineData frames. "
            "Is the ecu-simulator container running?"
        )
