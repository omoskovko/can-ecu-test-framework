"""UDS diagnostic tests via udsoncan."""

from __future__ import annotations

import pytest
from udsoncan.exceptions import NegativeResponseException

from test_framework.uds_client import UdsTestClient


@pytest.mark.diagnostic
@pytest.mark.smoke
def test_read_vin(uds_client: UdsTestClient, config) -> None:
    """ReadDataByIdentifier(0xF190) returns expected VIN string."""
    vin_did = config["dids"]["vin"]
    vin = uds_client.read_did(vin_did)
    expected = config["expected"]["vin"]
    assert vin == expected, f"VIN mismatch: got '{vin}', expected '{expected}'"


@pytest.mark.diagnostic
def test_vin_has_correct_length(uds_client: UdsTestClient, config) -> None:
    """VIN must be exactly 17 ASCII characters (ISO 3779)."""
    vin = uds_client.read_did(config["dids"]["vin"])
    assert (
        len(vin) == config["expected"]["vin_length"]
    ), f"VIN length is {len(vin)}, must be 17"


@pytest.mark.diagnostic
def test_read_software_version(uds_client: UdsTestClient, config) -> None:
    """ReadDataByIdentifier(0xF195) returns expected SW version."""
    sw = uds_client.read_did(config["dids"]["software_version"])
    expected = config["expected"]["software_version"]
    assert sw == expected, f"SW version mismatch: got '{sw}', expected '{expected}'"


@pytest.mark.diagnostic
def test_unknown_did_returns_request_out_of_range(uds_client: UdsTestClient) -> None:
    """Reading a non-existent DID must return NRC 0x31."""
    with pytest.raises(NegativeResponseException) as exc_info:
        uds_client.read_did(0xFFFF)
    assert exc_info.value.response.code == 0x31, (
        f"Expected NRC 0x31 (requestOutOfRange), "
        f"got 0x{exc_info.value.response.code:02X}"
    )


@pytest.mark.diagnostic
def test_change_to_extended_session(uds_client: UdsTestClient) -> None:
    """DiagnosticSessionControl: switch to extended session succeeds."""
    response = uds_client.change_to_extended_session()
    assert response.positive, "Session change returned negative response"


@pytest.mark.diagnostic
def test_tester_present_succeeds(uds_client: UdsTestClient) -> None:
    """TesterPresent must return positive response."""
    # No exception means positive response (config sets exception_on_negative=True)
    uds_client.tester_present()
