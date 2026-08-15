"""Placement gate: courtyard/pad overlaps and off-board parts.

KiCad's own DRC reports courtyard overlaps, but only after a 15-minute route
and fill; this answers the same question from design.py in a second, which is
what makes iterating on floorplan.py practical. Exit code is 0 only when
there are zero overlaps and zero off-board parts; nonzero (1) otherwise, so
`make pcb-check` actually fails on a placement regression instead of always
"passing". Needs KiCad's python for the footprint courtyards.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import wx; _a = wx.App(False)
except ImportError: pass
import pcbnew
from design import COMPONENTS, BX0, BY0, BX1, BY1
import kicad_build as KB

def boxes():
    out = {}
    for ref, c in COMPONENTS.items():
        lib, name = c["fp"].split(":", 1)
        fp = KB.load_footprint(lib, name)
        assert fp, c["fp"]
        fp.SetPosition(KB.V(*c["at"][:2]))
        fp.SetOrientationDegrees(c["at"][2])
        xs, ys = [], []
        for it in list(fp.GraphicalItems()):
            if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
                b = it.GetBoundingBox()
                xs += [b.GetLeft(), b.GetRight()]
                ys += [b.GetTop(), b.GetBottom()]
        for pad in fp.Pads():
            b = pad.GetBoundingBox()
            xs += [b.GetLeft(), b.GetRight()]
            ys += [b.GetTop(), b.GetBottom()]
        class _B: pass
        bb = _B()
        bb.GetLeft = lambda: min(xs); bb.GetRight = lambda: max(xs)
        bb.GetTop = lambda: min(ys); bb.GetBottom = lambda: max(ys)
        out[ref] = (pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
                    pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
    return out

if __name__ == "__main__":
    b = boxes()
    for ref in sorted(b):
        x0,y0,x1,y1 = b[ref]
        print("%-6s %7.2f %7.2f %7.2f %7.2f   w=%5.2f h=%5.2f" % (ref,x0,y0,x1,y1,x1-x0,y1-y0))
    print("--- outside board ---")
    n_out = 0
    for ref,(x0,y0,x1,y1) in sorted(b.items()):
        if x0 < BX0 or y0 < BY0 or x1 > BX1 or y1 > BY1:
            print("OUT %-6s %.2f %.2f %.2f %.2f" % (ref,x0,y0,x1,y1))
            n_out += 1
    print("--- overlaps ---")
    refs = sorted(b)
    n=0
    for i in range(len(refs)):
        for j in range(i+1, len(refs)):
            a,c = b[refs[i]], b[refs[j]]
            ox = min(a[2],c[2]) - max(a[0],c[0])
            oy = min(a[3],c[3]) - max(a[1],c[1])
            if ox > 0.01 and oy > 0.01:
                n+=1
                print("OVL %-6s %-6s  %.2f x %.2f" % (refs[i],refs[j],ox,oy))
    print("total overlaps:", n)
    print("total outside board:", n_out)
    sys.exit(0 if (n == 0 and n_out == 0) else 1)
