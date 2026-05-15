#!/usr/bin/env bash
# Setup virtual CAN interface for local testing and CI

set -e

INTERFACE=${1:-vcan0}

echo "Setting up virtual CAN interface: $INTERFACE"

sudo modprobe vcan

if ip link show "$INTERFACE" &>/dev/null; then
    echo "Interface $INTERFACE already exists, bringing down first"
    sudo ip link set "$INTERFACE" down
    sudo ip link delete "$INTERFACE"
fi

sudo ip link add dev "$INTERFACE" type vcan
sudo ip link set up "$INTERFACE"

echo "Done. Verify with: ip link show $INTERFACE"

