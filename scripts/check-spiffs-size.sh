#!/usr/bin/env bash
set -euo pipefail

SPIFFS_DIR="${1:-spiffs_data/www}"
# From partitions.csv: storage partition is 0x7E0000 = 8257536 bytes
PARTITION_SIZE=8257536
# Warn at 80%, fail at 95%
WARN_THRESHOLD=$(( PARTITION_SIZE * 80 / 100 ))
FAIL_THRESHOLD=$(( PARTITION_SIZE * 95 / 100 ))

ACTUAL_SIZE=$(du -sb "$SPIFFS_DIR" 2>/dev/null || du -sk "$SPIFFS_DIR" | awk '{print $1 * 1024}')
ACTUAL_SIZE=$(echo "$ACTUAL_SIZE" | cut -f1)
PERCENT=$(( ACTUAL_SIZE * 100 / PARTITION_SIZE ))

echo "SPIFFS usage: ${ACTUAL_SIZE} / ${PARTITION_SIZE} bytes (${PERCENT}%)"

if [ "$ACTUAL_SIZE" -gt "$FAIL_THRESHOLD" ]; then
    echo "::error::SPIFFS partition usage at ${PERCENT}% — exceeds 95% limit"
    exit 1
elif [ "$ACTUAL_SIZE" -gt "$WARN_THRESHOLD" ]; then
    echo "::warning::SPIFFS partition usage at ${PERCENT}% — approaching limit"
fi

echo "SPIFFS size check passed"
