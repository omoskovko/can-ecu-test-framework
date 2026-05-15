# CAN ECU Test Framework

[![tests](https://github.com/omoskovko/can-ecu-test-framework/actions/workflows/tests.yml/badge.svg)](https://github.com/omoskovko/can-ecu-test-framework/actions/workflows/tests.yml)

Python-based test framework for automotive ECU validation over CAN bus.
Includes a simulated Engine Control Unit with UDS diagnostic support and
a pytest suite covering communication, signal-level, and diagnostic test
categories.

Designed to run in Docker on Linux (with `vcan` kernel module), making
the entire setup reproducible locally and in CI without physical hardware.

## Why this project

Demonstrates the end-to-end workflow of an automotive test engineer:
- Reading and writing CAN frames with proper DBC-driven decoding
- Implementing and testing ISO 14229 (UDS) diagnostic services over ISO-TP
- Designing a maintainable test framework with fixtures, parametrization,
  and clear separation between system-under-test (simulator) and tester
- Running the whole thing in Docker with CI on every push

## Architecture

```
┌────────────────────────────┐         ┌────────────────────────────┐
│  ECU Simulator             │         │  Test Runner               │
│  (Docker container)        │         │  (Docker container)        │
│                            │         │                            │
│  • EngineECU               │         │  • pytest                  │
│    - Periodic CAN frames   │         │  • CanTestBus              │
│    - DBC-encoded signals   │         │  • DbcHelper               │
│  • UDSServer               │         │  • UdsTestClient           │
│    - ISO-TP transport      │         │  • Fixtures + config       │
│    - 5 UDS services        │         │                            │
└─────────────┬──────────────┘         └─────────────┬──────────────┘
              │                                      │
              │            vcan0 (host)              │
              └──────────────────┬───────────────────┘
                                 │
                       ┌─────────▼─────────┐
                       │  SocketCAN kernel │
                       └───────────────────┘
```

Both containers share the host network namespace (`network_mode: host`)
so they use the `vcan0` virtual CAN interface created on the host.

## Test categories

| Category       | Count | Examples                                        |
|----------------|-------|-------------------------------------------------|
| Communication  | 10    | Frame presence, DLC, cycle time with jitter     |
| Signals        | 9     | RPM/temp ranges, multiplexed signal decoding    |
| Diagnostic     | 6     | UDS read DID, NRC, session control, T.Present   |

23 tests total. Full suite runs in ~22 seconds.

## ECU simulator

| Message ID | Name           | Cycle | Signals                                          |
|------------|----------------|-------|--------------------------------------------------|
| `0x100`    | EngineData     | 100ms | EngineRPM, CoolantTemp, EngineLoad, OilPressure  |
| `0x200`    | VehicleStatus  | 200ms | VehicleSpeed, GearPosition, HandbrakeOn          |
| `0x300`    | DiagnosticInfo | 500ms | Multiplexed: FuelLevel/Consumption or Battery/Tᴀ |

Signals evolve over time (sine waves with random jitter) to mimic
real sensor data.

## UDS server

- Diagnostic request ID: `0x7E0`, response ID: `0x7E8`
- Implementation: ISO-TP via pure-Python stack (`isotp.CanStack`)

Supported services:

| SID  | Service                          | Notes                                   |
|------|----------------------------------|-----------------------------------------|
| 0x10 | DiagnosticSessionControl         | Default, programming, extended sessions |
| 0x22 | ReadDataByIdentifier             | VIN (0xF190), SW ver (0xF195), S/N      |
| 0x14 | ClearDiagnosticInformation       |                                         |
| 0x19 | ReadDTCInformation               | Subfunction 0x02 only                   |
| 0x3E | TesterPresent                    | Suppress-positive-response supported    |

S3 session timeout (5s) returns to default session on inactivity.

## Quick start

### Prerequisites

- Linux host (or WSL2 with custom kernel) with CAN modules
- Docker and Docker Compose

### Setup vcan on host

```bash
sudo modprobe vcan
sudo modprobe can-isotp
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

### Run

```bash
# Build images
docker compose build

# Start simulator
docker compose up -d ecu-simulator

# Verify traffic from host
candump vcan0

# Run full test suite
docker compose --profile test run --rm tests

# Stop everything
docker compose down
```

HTML report appears in `reports/report.html`.

### Run locally (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python scripts/run_simulator.py --channel vcan0 &
pytest tests/ -v
```

### Run only specific test groups

```bash
pytest tests/ -m smoke         # ~7 fastest tests
pytest tests/diagnostic/       # UDS tests only
pytest tests/communication/ -k cycle_time   # specific test
```

## Project layout

```
.
├── dbc/                      # CAN database (.dbc)
│   └── engine_ecu.dbc
├── src/
│   ├── ecu_simulator/        # System under test
│   │   ├── base_ecu.py       # Abstract base for ECUs
│   │   ├── engine_ecu.py     # Engine ECU implementation
│   │   └── uds_server.py     # UDS over ISO-TP
│   ├── test_framework/       # Test helpers
│   │   ├── can_bus.py        # python-can wrapper + cycle stats
│   │   ├── dbc_helper.py     # cantools wrapper
│   │   └── uds_client.py     # udsoncan wrapper
│   └── utils/
├── tests/
│   ├── communication/
│   ├── signals/
│   ├── diagnostic/
│   └── conftest.py
├── config/
│   └── test_config.yaml
├── scripts/
│   └── run_simulator.py
├── .github/workflows/
│   └── tests.yml
├── Dockerfile
└── docker-compose.yml
```

## Key design decisions

**Pure-Python ISO-TP on both sides.** Kernel ISO-TP socket
(`isotp.socket`) is faster but the simulator and the tester cannot share
the same `rxid/txid` pair on the same vcan from different sockets — they
collide. Using `isotp.CanStack` on top of `python-can` avoids this and
removes the dependency on the `can-isotp` kernel module.

**Configuration in YAML, not in code.** `config/test_config.yaml`
centralizes channel, IDs, expected cycles, and tolerances. Tests resolve
values through the `config` fixture instead of hardcoding magic numbers.

**Cycle tolerance set to 20%.** This is wider than a typical production
spec (5-10%) because Python timers + Docker virtualization introduce
significant jitter. Documented explicitly to highlight that we test
realistic conditions, not idealized ones.

**Separate simulator and test runner containers.** Mirrors how real
ECU test setups work — the device under test runs continuously, the
tester is invoked on demand. Also makes CI cleaner: simulator is started
once, tests run against it, both tear down together.

## CI

GitHub Actions workflow (`.github/workflows/tests.yml`) on every push:

1. Loads `vcan` and `can-isotp` kernel modules on the runner
2. Creates `vcan0` interface
3. Builds Docker images with GHA cache
4. Starts simulator, waits for healthcheck
5. Runs full pytest suite in tests container
6. Uploads HTML report as artifact

## Roadmap

- [x] ECU simulator with periodic frames
- [x] UDS server (sessions, DID, DTC)
- [x] DBC-based encoding with multiplexed signals
- [x] Docker Compose orchestration
- [x] pytest framework with 23 tests
- [x] GitHub Actions CI
- [ ] DTC injection and clearing tests
- [ ] SecurityAccess (0x27) simulation with seed/key
- [ ] Network Management (NM) simulation
- [ ] Coverage reporting (pytest-cov)
- [ ] Allure reporting integration
- [ ] Real hardware support (CANable, PEAK)

## Technologies

- Python 3.11+
- [python-can](https://github.com/hardbyte/python-can) — CAN bus library
- [cantools](https://github.com/cantools/cantools) — DBC parsing and encoding
- [can-isotp](https://github.com/pylessard/python-can-isotp) — ISO-TP transport
- [udsoncan](https://github.com/pylessard/python-udsoncan) — UDS protocol
- [pytest](https://pytest.org) — test framework
- Docker & Docker Compose

