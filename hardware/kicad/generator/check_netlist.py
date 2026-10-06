"""Schematic-vs-board drift check: the schematic's connectivity must be on
the board. KiCad exports the netlist fresh from the schematic (so this does
not trust the committed .net), and every ref, footprint and pad net on the
board is compared against it. A schematic edit that has not been synced -
or a board edit that re-netted a pad by hand - fails here.

Usage: python3 check_netlist.py <schematic.kicad_sch> [board.kicad_pcb]
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import board as B
import netlist as NL


def main(sch, pcb=None):
    pcb = pcb or os.path.splitext(sch)[0] + ".kicad_pcb"
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tf:
        netfile = tf.name
    subprocess.run(["kicad-cli", "sch", "export", "netlist",
                    "--format", "kicadsexpr", "-o", netfile, sch], check=True,
                   capture_output=True)
    nl = NL.load(netfile)
    os.unlink(netfile)
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
        for num, net in f["pads"].items():
            if not num:
                continue
            pads += 1
            want = c["pins"].get(num)
            if (net or None) != want:
                bad.append("%s pad %s: net %s on the board, %s in the schematic"
                           % (ref, num, net or "<none>", want or "<none>"))
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
