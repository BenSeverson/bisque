#!/usr/bin/env python3
"""Assert the committed netlist was exported from the schematic on disk.

bisque-controller.net is the interface between the schematic and the board,
and it is committed so CI can read connectivity without kicad-cli. A stale
copy would let a schematic edit pass every portable checker while the board
sync, the BOM and the pin-map check all read the previous design. The stamp
written beside it by netlist.export() is a SHA256 over every sheet file; this
re-hashes them and fails on a mismatch.

Portable: standard library plus sexp.py.
Usage: python3 check_netlist_fresh.py <root.kicad_sch> <netlist.net>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netlist


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: check_netlist_fresh.py <root.kicad_sch> <netlist.net>")
    sch, net = argv
    sp = netlist.stamp_path(net)
    if not os.path.isfile(net) or not os.path.isfile(sp):
        sys.exit("NETLIST FRESH: FAIL - %s or %s missing; run: make pcb-netlist"
                 % (os.path.basename(net), os.path.basename(sp)))
    have = open(sp).read().strip()
    want = netlist.stamp(sch)
    if have != want:
        sys.exit("NETLIST FRESH: FAIL - %s was exported from a different "
                 "schematic (stamp %s.., schematic hashes to %s..); run: "
                 "make pcb-netlist" % (os.path.basename(net), have[:12], want[:12]))
    print("NETLIST FRESH: PASS (%d sheet file(s))" % len(netlist.sheet_files(sch)))


if __name__ == "__main__":
    main(sys.argv[1:])
