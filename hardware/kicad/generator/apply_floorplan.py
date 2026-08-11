#!/usr/bin/env python3
"""Patch design.py's `at=(x, y, rot)` tuples from floorplan.json.

floorplan.py holds the layout intent and emits the legalized coordinates;
design.py is the single source of truth the generators read. This is the one
step between them, kept separate so a placement iteration never has to be
retyped by hand into 141 dict entries.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def fmt(v):
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return s if "." in s else s + ".0"


def main():
    place = json.load(open(os.path.join(HERE, "floorplan.json")))
    path = os.path.join(HERE, "design.py")
    src = open(path).read()
    for ref, (x, y, rot) in place.items():
        pat = r'("%s":\s*dict\(.*?)at=\((-?[\d.]+),\s*(-?[\d.]+),\s*(-?\d+)\)' \
            % re.escape(ref)
        m = re.search(pat, src, re.S)
        if not m:
            sys.exit("no at=() for %s in design.py" % ref)
        src = src[:m.start()] + "%sat=(%s, %s, %d)" % (
            m.group(1), fmt(x), fmt(y), rot) + src[m.end():]
    open(path, "w").write(src)
    print("applied %d placements to design.py" % len(place))


if __name__ == "__main__":
    main()
