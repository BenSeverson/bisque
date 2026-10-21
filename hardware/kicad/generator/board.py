#!/usr/bin/env python3
"""Read a .kicad_pcb with the standard library: footprints, copper, outline.

The board file owns placement and copper, so everything that used to read a
position or a pad's net out of design.py reads it from here instead - the
BOM/CPL generator, the placement and JLC checkers, the silk-legend tables.
Portable on purpose: no pcbnew, so the CI checkers can use it.

Read-only. Nothing here writes a board; that is pcbnew's job (sync_board.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, find_all, num


class Board:
    """fps:    {ref: {"fpid", "fpname", "x", "y", "rot", "layer", "value",
                     "locked", "dnp", "pads": {num: net|None}, "uuid"}}
    edge:   (x0, y0, x1, y1) of everything on Edge.Cuts, mm
    tracks: [{"net", "layer", "x1", "y1", "x2", "y2", "w", "locked", "uuid"}]
    vias:   [{"net", "x", "y", "locked", "uuid"}]
    texts:  [{"text", "x", "y", "layer", "locked", "uuid"}]  (board-level gr_text)
    nets:   set of every net name a pad, track or via carries
    """

    def __init__(self):
        self.fps = {}
        self.edge = None
        self.tracks = []
        self.vias = []
        self.texts = []
        self.nets = set()


def _is_locked(node):
    """`(locked yes)` is KiCad 10's form; a bare `locked` atom is the older one."""
    lk = find(node, "locked")
    if lk is not None:
        return len(lk) < 2 or str(lk[1]) == "yes"
    return any(isinstance(a, str) and not isinstance(a, list) and str(a) == "locked"
               for a in node[1:])


def _net_name(node):
    n = find(node, "net")
    if n is None or len(n) < 2:
        return None
    name = str(n[-1])            # (net "GND") in KiCad 10, (net 3 "GND") before
    return name or None


def _prop(node, name):
    for p in find_all(node, "property"):
        if len(p) > 2 and str(p[1]) == name:
            return str(p[2])
    return ""


def _layer(node):
    l = find(node, "layer")
    return str(l[1]) if l and len(l) > 1 else ""


def _uuid(node):
    u = find(node, "uuid")
    return str(u[1]) if u and len(u) > 1 else ""


def load(path):
    doc = parse(open(path).read())[0]
    bd = Board()
    ex, ey = [], []
    for item in doc[1:]:
        if not isinstance(item, list) or not item:
            continue
        kind = str(item[0])
        if kind == "footprint":
            at = find(item, "at")
            attr = find(item, "attr")
            attrs = [str(a) for a in attr[1:]] if attr else []
            fpname = str(item[1])
            # The file carries the bare footprint name; the library nickname
            # is only on the schematic symbol's Footprint field. Callers that
            # need a lib:name take it from the netlist.
            fp = {"fpid": fpname, "fpname": fpname,
                  "x": num(at[1]), "y": num(at[2]),
                  "rot": num(at[3]) if len(at) > 3 else 0.0,
                  "layer": _layer(item), "value": _prop(item, "Value"),
                  "locked": _is_locked(item), "dnp": "dnp" in attrs,
                  "attrs": attrs, "pads": {}, "uuid": _uuid(item)}
            for pad in find_all(item, "pad"):
                n = _net_name(pad)
                fp["pads"].setdefault(str(pad[1]), n)
                if n:
                    bd.nets.add(n)
            bd.fps[_prop(item, "Reference")] = fp
        elif kind in ("gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly") \
                and _layer(item) == "Edge.Cuts":
            for key in ("start", "end", "mid", "center"):
                p = find(item, key)
                if p:
                    ex.append(num(p[1]))
                    ey.append(num(p[2]))
            pts = find(item, "pts")
            for xy in (find_all(pts, "xy") if pts else []):
                ex.append(num(xy[1]))
                ey.append(num(xy[2]))
        elif kind in ("segment", "arc"):
            s, e, w = find(item, "start"), find(item, "end"), find(item, "width")
            n = _net_name(item)
            bd.tracks.append({"net": n, "layer": _layer(item),
                              "x1": num(s[1]), "y1": num(s[2]),
                              "x2": num(e[1]), "y2": num(e[2]),
                              "w": num(w[1]), "locked": _is_locked(item),
                              "uuid": _uuid(item)})
            if n:
                bd.nets.add(n)
        elif kind == "via":
            at = find(item, "at")
            n = _net_name(item)
            bd.vias.append({"net": n, "x": num(at[1]), "y": num(at[2]),
                            "locked": _is_locked(item), "uuid": _uuid(item)})
            if n:
                bd.nets.add(n)
        elif kind == "gr_text":
            at = find(item, "at")
            bd.texts.append({"text": str(item[1]), "x": num(at[1]),
                             "y": num(at[2]), "layer": _layer(item),
                             "locked": _is_locked(item), "uuid": _uuid(item)})
    if ex:
        bd.edge = (min(ex), min(ey), max(ex), max(ey))
    return bd


if __name__ == "__main__":
    bd = load(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
    print("%d footprints (%d locked), %d tracks, %d vias, %d texts, edge %s"
          % (len(bd.fps), sum(1 for f in bd.fps.values() if f["locked"]),
             len(bd.tracks), len(bd.vias), len(bd.texts), bd.edge))
