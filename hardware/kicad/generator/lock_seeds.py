#!/usr/bin/env python3
"""One-shot: lock the copper the in-house router could only draw from hand
seeds, so no router and no sync can take it. USB pair whole; the J1, ADE7953
I2C and U12 escape seeds; the manual and stitch vias.
Usage: <kicad-python> lock_seeds.py board.kicad_pcb
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
import gen_pcb as G
from kicad_build import resort_to_kicad_order

TOL = 0.011


def on_polyline(p, pts):
    x, y = p
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        if abs(x - (ax + t * dx)) < TOL and abs(y - (ay + t * dy)) < TOL:
            return True
    return False


def main(path):
    b = pcbnew.LoadBoard(path)
    seeds = [(n, pts) for (n, _l, pts, _w) in G.USB_SEEDS + G.ADE_I2C_SEEDS + G.MUX_SEEDS]
    via_at = [(n, x, y) for (n, x, y) in G.MANUAL_VIAS + G.STITCH_VIAS]
    nt = nv = 0
    for t in b.GetTracks():
        net = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T:
            x, y = pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y)
            if net in G.USB_DIFF_PAIR or any(n == net and abs(x - vx) < TOL and abs(y - vy) < TOL for n, vx, vy in via_at):
                t.SetLocked(True); nv += 1
            continue
        a = (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y))
        c = (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y))
        if net in G.USB_DIFF_PAIR or any(n == net and on_polyline(a, pts) and on_polyline(c, pts) for n, pts in seeds):
            t.SetLocked(True); nt += 1
    pcbnew.SaveBoard(path, b, True)
    resort_to_kicad_order(path)
    print("locked %d track(s) and %d via(s)" % (nt, nv))


if __name__ == "__main__":
    main(sys.argv[1])
