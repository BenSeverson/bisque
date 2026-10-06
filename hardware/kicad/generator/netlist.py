#!/usr/bin/env python3
"""The schematic's exported netlist, parsed. Standard library + sexp.py only.

This is the interface between the schematic and the board. The schematic
owns connectivity, values, footprints and sourcing fields; `kicad-cli sch
export netlist` turns that into one file, and everything on the board side
- the sync, the BOM, the checkers - reads this and never the schematic.

The export is COMMITTED (bisque-controller.net) so the portable checkers can
read connectivity in CI without kicad-cli, and it is stamped against the
schematic files (bisque-controller.net.stamp) so a stale copy fails
`check_netlist_fresh.py` rather than passing with old connectivity. Same
arrangement as the web tests' fixture manifest.

Usage: python3 netlist.py <root.kicad_sch> <out.net>
"""
import hashlib
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, find_all

# Pin names are the SYMBOL's, exactly as exported: the footprint's pads carry
# the same names (J1's shield is "SH" on both), so the sync matches them
# verbatim. No aliasing here - an alias would have to be undone by every
# consumer that touches a pad.


class Netlist:
    """comps: {ref: {"value", "footprint", "fields", "dnp", "pins": {num: net}}}
    nets:  {net: {(ref, pin), ...}}   (no '#' refs, no 'unconnected-*' nets)
    """

    def __init__(self):
        self.comps = {}
        self.nets = {}


def _prop_value(p):
    v = find(p, "value")
    return str(v[1]) if v and len(v) > 1 else ""


def load(path):
    doc = parse(open(path).read())[0]
    nl = Netlist()
    for c in find_all(find(doc, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        if ref.startswith("#"):
            continue
        fields = {}
        fs = find(c, "fields")
        for fld in (find_all(fs, "field") if fs else []):
            # (field (name "MPN") "C515890") - the value is the trailing atom
            fields[str(find(fld, "name")[1])] = str(fld[-1]) if len(fld) > 2 else ""
        dnp = False
        for p in find_all(c, "property"):
            name = str(find(p, "name")[1])
            if name == "dnp":
                dnp = True
            fields.setdefault(name, _prop_value(p))
        fpn = find(c, "footprint")
        val = find(c, "value")
        nl.comps[ref] = {
            "value": str(val[1]) if val and len(val) > 1 else "",
            "footprint": str(fpn[1]) if fpn and len(fpn) > 1 else "",
            "fields": fields,
            "dnp": dnp,
            "pins": {},
        }
    for n in find_all(find(doc, "nets"), "net"):
        name = str(find(n, "name")[1]).split("/")[-1]
        if name.startswith("unconnected-"):
            continue
        for node in find_all(n, "node"):
            ref = str(find(node, "ref")[1])
            if ref not in nl.comps:
                continue
            pin = str(find(node, "pin")[1])
            nl.nets.setdefault(name, set()).add((ref, pin))
            nl.comps[ref]["pins"][pin] = name
    nl.nets = {k: v for k, v in nl.nets.items() if v}
    return nl


def sheet_files(root):
    """Every schematic file reachable from `root`, root first, absolute paths.

    Followed through each sheet symbol's `Sheetfile` property rather than a
    glob of the directory, so a sheet renamed by hand is still hashed and a
    stray file beside the project is not.
    """
    seen, todo = [], [os.path.abspath(root)]
    while todo:
        p = todo.pop(0)
        if p in seen:
            continue
        seen.append(p)
        doc = parse(open(p).read())[0]
        for sh in find_all(doc, "sheet"):
            for prop in find_all(sh, "property"):
                if str(prop[1]) == "Sheetfile":
                    todo.append(os.path.normpath(
                        os.path.join(os.path.dirname(p), str(prop[2]))))
    return seen


def stamp(root):
    """SHA256 over every sheet file's name and bytes."""
    h = hashlib.sha256()
    for p in sheet_files(root):
        h.update(os.path.basename(p).encode())
        h.update(b"\0")
        with open(p, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def stamp_path(net_path):
    return net_path + ".stamp"


_VOLATILE = re.compile(r'^\t\t\((date|source) "[^"]*"\)\n', re.M)


def export(sch, out):
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format",
                    "kicadsexpr", "-o", out, sch], check=True,
                   capture_output=True)
    # The export's `design` block records the wall-clock time and the
    # absolute path of the schematic. Neither is connectivity, and both would
    # make an unchanged schematic re-export as a diff, so they are dropped:
    # the committed file is a function of the schematic alone.
    with open(out) as fh:
        text = fh.read()
    with open(out, "w") as fh:
        fh.write(_VOLATILE.sub("", text))
    with open(stamp_path(out), "w") as fh:
        fh.write(stamp(sch) + "\n")


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: netlist.py <root.kicad_sch> <out.net>")
    sch, out = argv
    export(sch, out)
    nl = load(out)
    print("%s: %d components, %d nets, stamped over %d sheet file(s)"
          % (out, len(nl.comps), len(nl.nets), len(sheet_files(sch))))


if __name__ == "__main__":
    main(sys.argv[1:])
