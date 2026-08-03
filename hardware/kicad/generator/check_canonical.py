#!/usr/bin/env python3
"""Self-check for canonicalize.py — the guard behind reproducible boards.

pcbnew mints a fresh random KIID for every item it creates, and KiCad's
s-expression writer sorts board items with comparators that end in that
KIID (footprints sort by it outright; tracks and vias use it to break
position ties). So an unchanged design serialises to a differently
ordered file carrying ~2000 different uuid strings on every run — #234.

canonicalize.py removes exactly those two degrees of freedom. This script
proves it does, by taking a real board, perturbing it the same two ways
pcbnew does — reshuffling the items and re-minting every uuid — and
asserting the canonical form comes out unchanged.

The splitter here is deliberately independent of canonicalize.py's, so a
bug in that one cannot hide behind a matching bug in the test.

Pure Python: no KiCad, no pcbnew, so it runs anywhere and stays fast.

Usage: python3 check_canonical.py [board.kicad_pcb ...]
"""
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canonicalize as C
import sexp

UUID_VALUE = re.compile(r'(\(uuid\s+")[^"]*(")')


def split_items(text):
    """[(kind, text)] for each top-level item, plus the head and tail.

    Line-based, which is enough for anything KiCad's writer produces: it
    indents every top-level child of (kicad_pcb ...) with exactly one tab
    and closes the multi-line ones with a lone "\\t)".
    """
    lines = text.split("\n")
    head, items, cur, kind = [], [], None, None
    tail = []
    for line in lines:
        if cur is not None:
            cur.append(line)
            if line == "\t)":
                items.append((kind, "\n".join(cur)))
                cur = None
            continue
        m = re.match(r"\t\(([A-Za-z_0-9]+)", line)
        if m and not tail:
            if line.count("(") == line.count(")"):
                items.append((m.group(1), line))
            else:
                cur, kind = [line], m.group(1)
        elif items:
            tail.append(line)
        else:
            head.append(line)
    return head, items, tail


def perturb(text, seed):
    """What pcbnew's save path does to an unchanged design: emit the same
    items in a different order, each carrying a freshly minted uuid."""
    rnd = random.Random(seed)
    head, items, tail = split_items(text)

    # KiCad groups top-level items by kind, so shuffling within each kind
    # is the only reordering its writer can actually produce.
    by_kind = {}
    for i, (kind, _) in enumerate(items):
        by_kind.setdefault(kind, []).append(i)
    out = list(items)
    for idxs in by_kind.values():
        picked = list(idxs)
        rnd.shuffle(picked)
        for dst, src in zip(idxs, picked):
            out[dst] = items[src]

    def remint(m):
        h = "%032x" % rnd.getrandbits(128)
        return "%s%s-%s-%s-%s-%s%s" % (m.group(1), h[:8], h[8:12], h[12:16],
                                       h[16:20], h[20:], m.group(2))

    body = head + [t for _, t in out] + tail
    return UUID_VALUE.sub(remint, "\n".join(body))


def content(text):
    """The design itself, with every uuid blanked — what must survive."""
    blanked = UUID_VALUE.sub(lambda m: m.group(1) + m.group(2), text)
    return sorted(sexp.dump(x) for x in sexp.parse(blanked)[0][1:]
                  if isinstance(x, list))


def check(path):
    text = open(path).read()
    canon = C.canonicalize_text(text)
    fails = []

    def expect(ok, label):
        print("  %-52s %s" % (label, "ok" if ok else "FAIL"))
        if not ok:
            fails.append(label)

    _, items, _ = split_items(text)
    expect(len(items) > 0, "%d top-level items found" % len(items))

    # The property the whole fix exists for: two generator runs differ only
    # by item order and uuids, so canonicalising must collapse them onto
    # the same bytes.
    a = C.canonicalize_text(perturb(text, 1))
    b = C.canonicalize_text(perturb(text, 2))
    expect(a == b, "two perturbations agree")
    expect(a == canon, "perturbation matches unperturbed original")

    expect(C.canonicalize_text(canon) == canon, "idempotent")
    expect(content(canon) == content(text), "design content preserved")
    expect(sexp.parse(canon)[0][0] == "kicad_pcb", "output still parses")

    uu = re.findall(r'\(uuid\s+"([^"]*)"\)', canon)
    expect(len(set(uu)) == len(uu), "uuids unique (%d)" % len(uu))

    print("  -> %s" % ("PASS" if not fails else "FAIL"))
    return not fails


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    paths = argv or [os.path.join(here, os.pardir,
                                  "bisque-controller.kicad_pcb")]
    ok = True
    for p in paths:
        print(os.path.basename(p))
        ok &= check(p)
    print("ALL CHECKS PASS" if ok else "CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
