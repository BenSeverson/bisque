#!/usr/bin/env python3
"""Assert the SSR opto-isolation barrier is not bridged.

The board pours GND on both layers. An opto buys nothing if the pour runs
underneath it, so kicad_build.py carves a keepout across the opto row and the
isolated nets must touch nothing but their opto and their terminal.

Runs on design.py connectivity alone - no KiCad required.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import netlist

# isolated net -> exactly the (ref, pin) endpoints it may have.
#
# SJ3.2 / SJ4.2 are the one deliberate exception. Each is pad 2 of an OPEN
# solder jumper whose pad 1 is +5V (spec 5.1: "a per-channel solder jumper
# ties the opto collector to board +5V for anyone who wants rev A's
# convenience; default open = isolated"). As shipped there is no copper
# between the two pads - only a 0.3 mm gap the user must deliberately fill -
# so the barrier is intact on every board that leaves the fab, and the
# jumper is placed so pad 2 sits inside the ISO_BARRIER band and pad 1
# outside it (see design.py SJ3). It is listed as an exact endpoint, not
# waived: this stays a set-equality test, so any OTHER connection appearing
# on an isolated net is still a failure.
ISOLATED = {
    "SSR1_A": {("U8", "4"), ("J4", "1"), ("SJ3", "2")},
    "SSR1_B": {("U8", "3"), ("J4", "2")},
    "SSR2_A": {("U9", "4"), ("J9", "1"), ("SJ4", "2")},
    "SSR2_B": {("U9", "3"), ("J9", "2")},
}

# The only (ref, pin) -> net pairs allowed to put a FORBIDDEN rail on a part
# that also touches an isolated net. Exactly the far pad of each open solder
# jumper, and exactly on +5V - naming the net as well as the pin means a
# jumper accidentally rewired to GND still fails.
BRIDGE_PINS = {("SJ3", "1"): "+5V", ("SJ4", "1"): "+5V"}

# Nets that must never appear on the isolated side.
FORBIDDEN = {"GND", "+3V3", "+5V", "VBUS", "VIN", "VLED", "AUX_VP"}


def main():
    nets = netlist()
    errors = []
    for net, allowed in ISOLATED.items():
        got = set(nets.get(net, []))
        if not got:
            errors.append("isolated net %s does not exist" % net)
        elif got != allowed:
            errors.append("isolated net %s connects to %s; expected exactly %s"
                          % (net, sorted(got), sorted(allowed)))
    isolated_refs = {ref for allowed in ISOLATED.values() for ref, _ in allowed}
    isolated_pins = {e for a in ISOLATED.values() for e in a}
    for bad in FORBIDDEN:
        for ref, pin in nets.get(bad, []):
            if ref not in isolated_refs or (ref, pin) in isolated_pins:
                continue
            if BRIDGE_PINS.get((ref, pin)) == bad:
                continue  # the open solder jumper's far pad, by design
            errors.append("%s.%s is on %s but %s straddles the barrier"
                          % (ref, pin, bad, ref))
    for (ref, pin), net in BRIDGE_PINS.items():
        if (ref, pin) not in set(nets.get(net, [])):
            errors.append("bridge exemption %s.%s is not on %s - the "
                          "exemption is stale" % (ref, pin, net))
    if errors:
        for e in errors:
            print("FAIL: %s" % e)
        return 1
    print("check_isolation: %d isolated nets, barrier intact" % len(ISOLATED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
