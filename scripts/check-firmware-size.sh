#!/usr/bin/env bash
set -euo pipefail

BINARY="${1:-build/bisque.bin}"

if [ ! -f "$BINARY" ]; then
    echo "::error::Firmware binary not found: $BINARY"
    exit 1
fi

# From partitions.csv: OTA partitions are 0x180000 = 1572864 bytes
PARTITION_SIZE=1572864
WARN_THRESHOLD=$(( PARTITION_SIZE * 90 / 100 ))
FAIL_THRESHOLD=$(( PARTITION_SIZE * 99 / 100 ))

ACTUAL_SIZE=$(stat -f%z "$BINARY" 2>/dev/null || stat -c%s "$BINARY")
PERCENT=$(( ACTUAL_SIZE * 100 / PARTITION_SIZE ))

echo "Firmware size: ${ACTUAL_SIZE} / ${PARTITION_SIZE} bytes (${PERCENT}%)"

if [ "$ACTUAL_SIZE" -gt "$FAIL_THRESHOLD" ]; then
    echo "::error::Firmware binary at ${PERCENT}% of OTA partition — exceeds 99% limit"
    exit 1
elif [ "$ACTUAL_SIZE" -gt "$WARN_THRESHOLD" ]; then
    echo "::warning::Firmware binary at ${PERCENT}% of OTA partition — approaching limit"
fi

echo "Firmware size check passed"
