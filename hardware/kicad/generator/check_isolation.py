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
ISOLATED = {
    "SSR1_A": {("U8", "4"), ("J4", "1")},
    "SSR1_B": {("U8", "3"), ("J4", "2")},
    "SSR2_A": {("U9", "4"), ("J9", "1")},
    "SSR2_B": {("U9", "3"), ("J9", "2")},
}

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
    for bad in FORBIDDEN:
        for ref, pin in nets.get(bad, []):
            if ref in isolated_refs and (ref, pin) not in \
                    {e for a in ISOLATED.values() for e in a}:
                errors.append("%s.%s is on %s but %s straddles the barrier"
                              % (ref, pin, bad, ref))
    if errors:
        for e in errors:
            print("FAIL: %s" % e)
        return 1
    print("check_isolation: %d isolated nets, barrier intact" % len(ISOLATED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
