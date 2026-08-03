#!/usr/bin/env bash
# Prints the name of an available iPhone simulator, newest iOS runtime first.
#
# `xcodebuild test` needs a concrete destination — "generic/platform=iOS
# Simulator" is not testable — and a hard-coded device name rots every time
# Xcode retires a model or a CI image bumps Xcode. Ask the machine instead.
set -euo pipefail

xcrun simctl list devices available --json | python3 -c '
import json, re, sys

devices = json.load(sys.stdin)["devices"]


def version(runtime):
    """Sort key from a runtime id like com.apple.…SimRuntime.iOS-26-5."""
    match = re.search(r"iOS-(\d+)-(\d+)", runtime)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


runtimes = sorted((r for r in devices if "iOS" in r), key=version, reverse=True)
for runtime in runtimes:
    for device in devices[runtime]:
        if device.get("isAvailable") and device["name"].startswith("iPhone"):
            print(device["name"])
            sys.exit(0)

sys.exit("no available iPhone simulator — install one via Xcode > Settings > Components")
'
