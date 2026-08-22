"""Rewrite a .kicad_pcb into canonical form so rebuilds are reproducible.

pcbnew mints a fresh random KIID for every item it constructs, and KiCad's
s-expression writer sorts board items with comparators whose key chain ends
in that KIID — footprints sort by it outright, tracks and vias use it to
break position ties. Nothing else about the board is random, so an
unchanged design still serialises to a file with a different item order and
~2000 different uuid strings on every single run (issue #234): regenerating
the board produced a ~20k-line diff against an identical board.

The Python API exposes no setter for m_Uuid, so the fix is applied to the
saved file instead: every uuid is replaced by one derived from the item's
own content, and items are re-sorted on that same content. Ordering then
follows from the uuids being stable, which is why fixing the uuids is
enough to fix both — and why the zone fill stabilises too, KiCad's filler
being deterministic given identical input.

Only uuid strings and the order of top-level items change; every other byte
KiCad wrote is preserved, so the result is still a file KiCad would have
written. Uuids are not cross-referenced anywhere in a .kicad_pcb (nets are
matched by name in KiCad 10), so renaming them is safe.

The content order this leaves behind is an implementation detail, and not
what a board built by this repo is stored in: it exists so that the ordinal
in a uuid's seed is a function of the design rather than of where pcbnew
happened to put the item. kicad_build.py re-sorts into KiCad's own order
afterwards (resort_to_kicad_order), because that is the order the GUI writes
and storing the file in anything else means every save is a whole-file diff.
So do not read the sort here as "the canonical order of the board" - the
canonical thing this module provides is the uuids.

Usage: python3 canonicalize.py board.kicad_pcb [...]
"""
import re
import sys
import uuid

# Fixed namespace, so the uuid for a given item is the same on every
# machine and every run, forever.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL,
                       "https://github.com/BenSeverson/bisque#kicad-canonical")

_UUID_VALUE = re.compile(r'(\(uuid\s+")[^"]*(")')
_HEAD = re.compile(r'\(\s*([^\s()"]+)')


def top_level_spans(text):
    """(start, end) for every direct child of the root s-expression."""
    spans = []
    depth = start = 0
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2:
                spans.append((start, i + 1))
            depth -= 1
            if depth == 0:
                break
    return spans


def node_kind(node):
    m = _HEAD.match(node)
    return m.group(1) if m else ""


def identity(node):
    """The item stripped of its uuids — everything that describes the
    design, and nothing that a rerun is free to change."""
    return _UUID_VALUE.sub(lambda m: m.group(1) + m.group(2), node)


def _fill_uuids(ident, ordinal):
    """Put content-derived uuids back into a blanked item."""
    counter = [0]

    def sub(m):
        seed = "%s\x00%d\x00%d" % (ident, ordinal, counter[0])
        counter[0] += 1
        return m.group(1) + str(uuid.uuid5(NAMESPACE, seed)) + m.group(2)

    return _UUID_VALUE.sub(sub, ident)


def canonicalize_text(text):
    spans = top_level_spans(text)
    if not spans:
        return text
    nodes = [text[s:e] for s, e in spans]
    gaps = [text[spans[i][1]:spans[i + 1][0]] for i in range(len(spans) - 1)]

    # Sort each kind of item among the slots that kind already occupies, so
    # the file keeps the layout KiCad gave it (header, footprints, graphics,
    # tracks, vias, zones) and only the order *within* a kind is fixed.
    slots = {}
    for i, node in enumerate(nodes):
        slots.setdefault(node_kind(node), []).append(i)
    ordered = [None] * len(nodes)
    for kind, idxs in slots.items():
        for slot, ident in zip(idxs, sorted(identity(nodes[i]) for i in idxs)):
            ordered[slot] = ident

    # Items identical but for their uuids are interchangeable, so number
    # them off in output order rather than by where they used to sit.
    seen = {}
    out = []
    for ident in ordered:
        ordinal = seen[ident] = seen.get(ident, -1) + 1
        out.append(_fill_uuids(ident, ordinal))

    body = out[0]
    for gap, node in zip(gaps, out[1:]):
        body += gap + node
    return text[:spans[0][0]] + body + text[spans[-1][1]:]


def canonicalize_file(path):
    """Canonicalise in place. True if the file changed."""
    with open(path) as fh:
        text = fh.read()
    canon = canonicalize_text(text)
    if canon == text:
        return False
    with open(path, "w") as fh:
        fh.write(canon)
    return True


def main(argv):
    if not argv:
        sys.exit(__doc__.strip().splitlines()[-1])
    for path in argv:
        print("canonicalized %s" % path if canonicalize_file(path)
              else "already canonical %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
