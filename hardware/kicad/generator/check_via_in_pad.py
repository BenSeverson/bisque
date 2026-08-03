"""Report vias that sit in (or too close to) an SMD pad.

An untented via inside an SMD pad wicks solder out of the joint during
reflow. KiCad's DRC does not flag it when the via and the pad share a net --
which is exactly the case router.py used to produce, since clearance rules
skip same-net copper -- so this check exists separately.

Pad hit-testing goes through pcbnew rather than parsing the board text: pad
shape, rotation and roundrect corners all matter here, and re-deriving them
from the s-expression is how you get confidently wrong answers. Needs
KiCad's bundled Python, same as kicad_build.py.

Usage: <kicad-python> check_via_in_pad.py <board.kicad_pcb> [min_gap_mm]
Exit 0 when every via clears every SMD pad by min_gap_mm (default 0.0,
i.e. "no copper overlap"), 1 otherwise.
"""
import os
import sys

try:
    import wx
    _wx_app = wx.App(False)
    if hasattr(wx, "DisableAsserts"):
        wx.DisableAsserts()
except ImportError:
    pass
import pcbnew


def main(board_path, min_gap=0.0):
    board = pcbnew.LoadBoard(board_path)
    pads = []
    for fp in board.Footprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                pads.append((fp.GetReference(), str(pad.GetNumber()), pad))
    vias = [t for t in board.Tracks() if t.Type() == pcbnew.PCB_VIA_T]

    bad = []
    for via in vias:
        pos = via.GetPosition()
        # via copper radius plus the gap we insist on keeping
        reach = via.GetWidth() // 2 + pcbnew.FromMM(min_gap)
        for (ref, pin, pad) in pads:
            if pad.HitTest(pos, reach):
                bad.append((ref, pin, pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y),
                            pad.GetNetname(), via.GetNetname()))

    print("%d vias vs %d SMD pads, required gap %.2f mm"
          % (len(vias), len(pads), min_gap))
    if bad:
        for (ref, pin, vx, vy, pnet, vnet) in sorted(bad):
            same = "same net" if pnet == vnet else "NET CLASH %s/%s" % (pnet, vnet)
            print("  VIA-IN-PAD %-6s pin %-3s via @ (%7.2f, %7.2f)  [%s]"
                  % (ref, pin, vx, vy, same))
        print("FAIL: %d via/pad conflict(s)" % len(bad))
        return 1
    print("PASS: no via encroaches on an SMD pad")
    return 0


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1]),
                  float(sys.argv[2]) if len(sys.argv) > 2 else 0.0))
