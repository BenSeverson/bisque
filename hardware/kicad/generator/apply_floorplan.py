#!/usr/bin/env python3
"""Patch design.py's `at=(x, y, rot)` tuples from floorplan.json.

floorplan.py holds the layout intent and emits the legalized coordinates;
design.py is the single source of truth the generators read. This is the one
step between them, kept separate so a placement iteration never has to be
retyped by hand into 141 dict entries.

Two rules keep that from corrupting the file, and both were learned the hard
way - the previous version violated each and silently mis-placed 24 of 144
parts, including dropping two board-edge screw terminals 26 mm inboard and
landing Q5 on top of U5:

1. A ref is patched inside ITS OWN entry. The old pattern was
   `("REF":\\s*dict\\(.*?)at=\\(...\\)` under re.S, whose non-greedy `.*?`
   happily runs across entry boundaries when the ref's own `at=` does not
   match - so the write lands on some later part's coordinates.

2. Only NUMERIC placements are rewritten. Twenty-odd entries are
   parameterized off shared anchors - `at=(97.0, TC2_Y, TC2_ROT)`,
   `at=(90.0, TC1_Y - 2.8 * TC1_DY, 0)` - because the two thermocouple
   front-ends and the two SSR chains are meant to stay symmetric by
   construction. Those are hand-anchored on purpose and flattening them to
   literals would quietly destroy the symmetry. They are reported, not
   patched.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = re.compile(r'"(\w+)":\s*dict\(')
NUMERIC_AT = re.compile(r'at=\((-?[\d.]+),\s*(-?[\d.]+),\s*(-?\d+)\)')


def fmt(v):
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return s if "." in s else s + ".0"


def entry_spans(src):
    """ref -> (start, end) of each `"REF": dict(...)` entry, non-overlapping."""
    marks = [(m.group(1), m.start()) for m in ENTRY.finditer(src)]
    spans = {}
    for i, (ref, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(src)
        spans.setdefault(ref, (start, end))
    return spans


def main():
    place = json.load(open(os.path.join(HERE, "floorplan.json")))
    path = os.path.join(HERE, "design.py")
    src = open(path).read()
    spans = entry_spans(src)

    missing = sorted(set(place) - set(spans))
    if missing:
        sys.exit("no design.py entry for: %s" % ", ".join(missing))

    edits, skipped = [], []
    for ref, (x, y, rot) in place.items():
        start, end = spans[ref]
        m = NUMERIC_AT.search(src, start, end)
        if not m:
            skipped.append(ref)          # parameterized anchor - leave alone
            continue
        edits.append((m.start(), m.end(),
                      "at=(%s, %s, %d)" % (fmt(x), fmt(y), rot)))

    for start, end, text in sorted(edits, reverse=True):
        src = src[:start] + text + src[end:]
    open(path, "w").write(src)

    print("applied %d placements to design.py" % len(edits))
    if skipped:
        print("  left %d parameterized anchor(s) untouched: %s"
              % (len(skipped), ", ".join(sorted(skipped))))


if __name__ == "__main__":
    main()
