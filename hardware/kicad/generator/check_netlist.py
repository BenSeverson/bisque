"""Schematic-vs-board drift check: the schematic's connectivity must be on
the board. Reads the committed netlist (bisque-controller.net - its
freshness against the schematic is check_netlist_fresh.py's job, so this
stays portable and runs in CI) and compares every ref, footprint, value,
DNP flag and pad net on the board against it. A schematic edit that has
not been synced - or a board edit that re-netted a pad by hand - fails
here. A netlist pin the board's footprint has no pad for fails too: that
connection would otherwise never reach copper.

Usage: python3 check_netlist.py <netlist.net> [board.kicad_pcb]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import board as B
import netlist as NL


def main(net, pcb=None):
    pcb = pcb or os.path.splitext(net)[0] + ".kicad_pcb"
    nl = NL.load(net)
    bd = B.load(pcb)
    bad = []
    for ref in sorted(set(nl.comps) - set(bd.fps)):
        bad.append("%s: in the schematic, not on the board" % ref)
    for ref in sorted(set(bd.fps) - set(nl.comps)):
        bad.append("%s: on the board, not in the schematic" % ref)
    pads = 0
    for ref in sorted(set(nl.comps) & set(bd.fps)):
        c, f = nl.comps[ref], bd.fps[ref]
        want_fp = c["footprint"].split(":", 1)[-1]
        if f["fpname"] != want_fp:
            bad.append("%s: footprint %s on the board, %s in the schematic"
                       % (ref, f["fpname"], want_fp))
        if f["value"] != c["value"]:
            bad.append("%s: value %r on the board, %r in the schematic"
                       % (ref, f["value"], c["value"]))
        if f["dnp"] != c["dnp"]:
            bad.append("%s: DNP %s on the board, %s in the schematic"
                       % (ref, f["dnp"], c["dnp"]))
        for num, netname in f["pads"].items():
            if not num:
                continue
            pads += 1
            want = c["pins"].get(num)
            if (netname or None) != want:
                bad.append("%s pad %s: net %s on the board, %s in the schematic"
                           % (ref, num, netname or "<none>", want or "<none>"))
        for num in sorted(set(c["pins"]) - {k for k in f["pads"] if k}):
            bad.append("%s pin %s (net %s) in the schematic has no pad on the "
                       "board's footprint" % (ref, num, c["pins"][num]))
    for line in bad[:40]:
        print("MISMATCH " + line)
    if len(bad) > 40:
        print("... and %d more" % (len(bad) - 40))
    print("%d components, %d pads compared, %d mismatches"
          % (len(nl.comps), pads, len(bad)))
    if bad:
        sys.exit("SCHEMATIC/BOARD: FAIL - run `make pcb-sync`")
    print("SCHEMATIC/BOARD: PASS")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
