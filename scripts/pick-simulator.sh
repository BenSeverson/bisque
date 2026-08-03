#!/usr/bin/env bash
# Prints the UDID of an available iPhone simulator, newest iOS runtime first.
# A human-readable "name (runtime)" line goes to stderr so build logs still say
# what was chosen without polluting the captured value.
#
# `xcodebuild test` needs a concrete destination — "generic/platform=iOS
# Simulator" is not testable — and a hard-coded device name rots every time
# Xcode retires a model or a CI image bumps Xcode. Ask the machine instead.
#
# A UDID rather than a name because a name is not unique: the same "iPhone 17
# Pro" exists under every installed runtime, so `name=` can resolve against a
# different runtime than the one this script inspected, or match nothing when
# the newest runtime has no iPhone but an older one does. The UDID identifies
# exactly the device that was found available.
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
            name = device["name"]
            label = runtime.rsplit(".", 1)[-1]
            print(f"Simulator: {name} ({label})", file=sys.stderr)
            print(device["udid"])
            sys.exit(0)

sys.exit("no available iPhone simulator — install one via Xcode > Settings > Components")
'
