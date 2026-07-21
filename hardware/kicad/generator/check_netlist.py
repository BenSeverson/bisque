"""Round-trip netlist check: KiCad parses the schematic and exports its
netlist; we diff it against design.py's intended connectivity.
KiCad's synthetic single-pin 'unconnected-(...)' nets (explicit no-connects)
are ignored. Usage: python3 check_netlist.py <schematic.kicad_sch>
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all
import design


def main(sch):
    with tempfile.NamedTemporaryFile(suffix=".net", delete=False) as tf:
        netfile = tf.name
    subprocess.run(["kicad-cli", "sch", "export", "netlist",
                    "--format", "kicadsexpr", "-o", netfile, sch], check=True)
    doc = parse(open(netfile).read())[0]
    got = {}
    for n in find_all(find(doc, "nets"), "net"):
        name = str(find(n, "name")[1]).split("/")[-1]
        if name.startswith("unconnected-"):
            continue
        pins = set()
        for node in find_all(n, "node"):
            ref = str(find(node, "ref")[1])
            if ref.startswith("#"):
                continue
            pins.add((ref, str(find(node, "pin")[1])))
        if pins:
            got.setdefault(name, set()).update(pins)
    want = {net: set(p) for net, p in design.netlist().items()}
    bad = 0
    for net in sorted(set(want) | set(got)):
        w, g = want.get(net, set()), got.get(net, set())
        if w != g:
            bad += 1
            print("MISMATCH %s: missing %s extra %s" % (net, sorted(w - g), sorted(g - w)))
    os.unlink(netfile)
    print("%d nets compared, %d mismatches" % (len(want), bad))
    if bad:
        sys.exit("NETLIST ROUND-TRIP: FAIL")
    print("NETLIST ROUND-TRIP: PASS")


if __name__ == "__main__":
    main(sys.argv[1])
