#!/usr/bin/env python3
"""Assert the schematic's MPN/LCSC properties still agree with gen_jlc.LCSC.

Sourcing lives in exactly one place - `gen_jlc.LCSC`, `ref -> (LCSC part,
description, fee_free, verified)` - and `gen_sch.py` copies the part number
onto every assembled symbol as hidden `MPN` and `LCSC` properties so the
schematic carries its own sourcing identity instead of being silent about it.
Two files now hold the same number, which is exactly the shape of drift this
repo has been bitten by before (the Kconfig/design.py pin map, which
check_pinmap.py exists to guard). This is that guard for sourcing.

It is deliberately symmetric, because both directions have failed elsewhere:

  * a table entry with no property on the symbol means the schematic was
    generated before the part was sourced, and the BOM would ship a part the
    schematic does not mention;
  * a property with no table entry means the part was DE-sourced (moved to
    NOT_ASSEMBLED, or dropped outright) and a stale number is still sitting on
    the symbol - the failure mode that left `USBLC6-2SC6` in
    datasheets/manifest.json long after U4 became an SRV05-4.

Portable: standard library plus this directory. No pcbnew, no kicad-cli, no
footprint libraries - so it belongs in `make pcb-check-portable` and runs in
CI, which is the point. A firmware-only PR cannot edit these tables, but a
hardware PR that re-sources a part and forgets to regenerate can, and that is
the case CI should catch rather than a fab house.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find_all
from gen_jlc import LCSC

# Properties gen_sch.py writes, both carrying the LCSC part number. MPN holds
# it because the C-number is this board's orderable identity and 49 of the 121
# lines have no manufacturer part number to hold instead; see the comment at
# the emission site in gen_sch.py.
SOURCING_PROPS = ("MPN", "LCSC")


def symbol_props(path):
    """ref -> {property name: value} for every placed symbol in the sheet."""
    doc = parse(open(path, encoding="utf-8").read())
    root = doc[0] if len(doc) == 1 and isinstance(doc[0], list) else doc
    out = {}
    for sym in find_all(root, "symbol"):
        props = {}
        for p in find_all(sym, "property"):
            if len(p) > 2 and isinstance(p[1], str):
                props[p[1]] = p[2]
        ref = props.get("Reference")
        # Power symbols and the sheet's own lib_symbols entries have no
        # Reference, or a #PWR-style one that is never sourced.
        if ref and not ref.startswith("#"):
            out[ref] = props
    return out


def main(argv):
    path = argv[1] if len(argv) > 1 else "bisque-controller.kicad_sch"
    if not os.path.exists(path):
        print("FAIL: %s not found" % path)
        return 1

    placed = symbol_props(path)
    errors = []

    # every sourced ref carries the table's number, on both properties
    for ref, entry in sorted(LCSC.items()):
        want = entry[0]
        props = placed.get(ref)
        if props is None:
            errors.append("%s is in gen_jlc.LCSC (%s) but is not placed in %s"
                          % (ref, want, os.path.basename(path)))
            continue
        for pname in SOURCING_PROPS:
            got = props.get(pname)
            if got is None:
                errors.append("%s has no %s property - regenerate the schematic "
                              "(make pcb-build)" % (ref, pname))
            elif got != want:
                errors.append("%s %s is %r, gen_jlc.LCSC says %r"
                              % (ref, pname, got, want))

    # nothing carries a sourcing property it is no longer entitled to
    for ref, props in sorted(placed.items()):
        if ref in LCSC:
            continue
        stale = [p for p in SOURCING_PROPS if props.get(p)]
        if stale:
            errors.append("%s carries %s but has no gen_jlc.LCSC entry - it was "
                          "de-sourced and the schematic is stale"
                          % (ref, "/".join(stale)))

    if errors:
        for e in errors:
            print("FAIL: %s" % e)
        return 1
    print("check_mpn: %d sourced parts carry matching MPN/LCSC properties "
          "(%d placed symbols, %d unsourced)"
          % (len(LCSC), len(placed), len(placed) - len(LCSC)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
