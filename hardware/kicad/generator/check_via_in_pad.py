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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_pcb import EP_VIA_GRID, is_ep_pad


def main(board_path, min_gap=0.0):
    board = pcbnew.LoadBoard(board_path)
    pads = []
    for fp in board.Footprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                pads.append((fp.GetReference(), str(pad.GetNumber()), pad))
    vias = [t for t in board.Tracks() if t.Type() == pcbnew.PCB_VIA_T]

    # The declared exposed pad of each footprint that has one. Looked up by
    # FOOTPRINT rather than by the pad the via happens to hit, because these
    # footprints carry the answer to A6 already: ESP32-S3-WROOM-1U and
    # QFN-28-1EP each ship NINE unnumbered, netless 0.83-0.9 mm sub-pads
    # inside the exposed pad - the library's own thermal-via pattern, with no
    # vias ever drilled through it. A via placed in the EP lands on one of
    # those too, and keying the exemption on the hit pad's number therefore
    # matched nothing at all: the sub-pads report number "" and net "", so
    # every EP via read as a NET CLASH against an unnamed pad.
    ep_pads = {}
    for fp in board.Footprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            key = (ref, str(pad.GetNumber()))
            if key in EP_VIA_GRID and is_ep_pad(
                    str(pad.GetNumber()), key[1],
                    pcbnew.ToMM(pad.GetSizeX()), pcbnew.ToMM(pad.GetSizeY())):
                ep_pads[ref] = pad

    bad = []
    for via in vias:
        pos = via.GetPosition()
        # via copper radius plus the gap we insist on keeping
        reach = via.GetWidth() // 2 + pcbnew.FromMM(min_gap)
        for (ref, pin, pad) in pads:
            if not pad.HitTest(pos, reach):
                continue
            # Exposed/thermal pads are the one place via-in-pad is correct
            # rather than a defect - it is how the pad reaches its plane at
            # all (review A6). The exemption is BY NAME, from the same table
            # that places them, and it still insists on the net matching:
            # a via of a foreign net inside a thermal pad is a short, not a
            # thermal via, and nothing about the pad being large makes that
            # acceptable.
            ep = ep_pads.get(ref)
            if (ep is not None and ep.HitTest(pos, 0)
                    and ep.GetNetname() == via.GetNetname()):
                continue
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
