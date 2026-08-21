"""Rev B floorplan: region assignment, seed placement, overlap legalizer.

This is where the board's *layout intent* lives - which subsystem occupies
which rectangle, which parts are pinned (board-edge connectors, the module),
and roughly where each remaining part wants to sit. The legalizer then pushes overlapping courtyards
apart within each part's region until nothing collides.

design.py records the RESULT as `at=(x, y, rot)`; this file records the
reasoning. Re-derive a placement with:

    KPY=/Applications/KiCad/.../bin/python3
    "$KPY" generator/floorplan.py            # writes floorplan.json
    python3 generator/apply_floorplan.py     # patches design.py's at= tuples

and check it with `generator/check_placement.py`. Needs KiCad's python for
the footprint courtyards.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import wx
    _a = wx.App(False)
except ImportError:
    pass
import pcbnew
from design import COMPONENTS, BX0, BY0, BX1, BY1
import kicad_build as KB

GAP = 0.45          # required courtyard-to-courtyard gap
EDGE = 0.7          # keep-in from the board outline

# ---------------------------------------------------------------- floorplan
# region -> (x0, y0, x1, y1) clamp box for the part's bounding box
REGIONS = {
    "TOPA": (32.0, 21.0, 60.0, 30.0),
    # y >= 33.4 keeps the USB-C escape fan (stubs end at y 31.2..32.0) clear
    "TOPB": (32.0, 32.6, 60.0, 43.3),
    # x <= 44.5 keeps y 43.6..48 open as the module's west-column south corridor
    "TOPC": (32.0, 43.6, 44.5, 48.6),
    "TOPR": (86.0, 21.0, 112.0, 31.0),
    # Bus test points live in the open band the buses actually cross, south of
    # the module's bottom pad row. Parking them in the top-right instead sent
    # SPI on a 40 mm detour around the module and starved the escape fan.
    "MID": (62.0, 55.0, 86.0, 63.5),
    # The WS2812 status LED and its support (R3 series, D3 Schottky, C10
    # bypass). 98e386f lifted the four of them out of J7's per-pin legend band
    # - a 5 x 5 mm LED sat on the labels for pins 5-7 and printed the row as
    # "3V3 GND TX RX . . . GND" - into this window, which design.py declares as
    # x 66..82, y 85..95. BOT1 starts at y 94 and cannot hold them.
    "LEDC": (66.0, 85.0, 82.0, 95.0),
    # The buzzer's driver chain moves out of the switching region into the open
    # band east of it. SWI is only 27.5 mm wide once J10/J4/J9 have taken
    # x 20..32.5, and it is also where every long net from the
    # module terminates; four parts moved out is four parts' worth of channel
    # back for the SSR driver chains.
    "SWI2": (61.5, 64.0, 70.0, 84.0),
    "SWI":  (32.5, 48.0, 62.0, 96.0),
    # The two MAX31856s are TSSOP-14: 0.4 mm pads on a 0.65 mm pitch escape
    # only straight out of their own row, so x 93.5..100.5 is reserved as
    # their escape column and every passive goes east or west of it.
    "ANA1W": (86.5, 31.5, 93.5, 44.5),
    "ANA1E": (100.5, 31.5, 107.6, 44.5),
    "ANA2W": (86.5, 45.5, 93.5, 57.0),
    "ANA2E": (100.5, 45.5, 107.6, 57.0),
    # ADE7953: QFN-28 escapes radially, so x 88.5..101.5 / y 61..73.5 is its
    # fan-out annulus and holds nothing else.
    "ANA3T": (86.0, 57.2, 107.6, 63.4),
    "ANA3U": (86.0, 63.5, 107.6, 68.0),
    "ANA3W": (86.0, 68.5, 90.4, 77.0),
    "ANA3E": (102.0, 68.3, 107.6, 77.0),
    "ANA3S": (86.0, 77.5, 107.6, 95.0),
    "BOT1": (41.0, 94.0, 107.6, 100.3),
    "BOT2": (32.0, 108.0, 59.0, 119.0),
}

FIXED = {
    # mechanical
    "H1": (25.5, 25.0, 0), "H2": (114.5, 25.0, 0),
    "H3": (25.5, 115.0, 0), "H4": (114.5, 115.0, 0),
    # module
    "U1": (70.0, 34.0, 0),
    # top edge: USB-C (opening = local +Y, so rot 180 faces the top edge)
    "J1": (48.0, 24.4, 180),
    # left edge screw terminals (rot 270 -> wire entry faces west)
    "J2": (26.0, 39.0, 270),
    "J10": (26.0, 52.0, 270),
    "J4": (26.0, 75.5, 270),
    "J9": (26.0, 88.0, 270),
    # SSR low-side drivers, each just east of its own terminal
    "Q5": (38.5, 78.0, 0),
    "Q6": (38.5, 90.0, 0),
    # right edge screw terminals (rot 90 -> wire entry faces east)
    "J3": (114.0, 41.0, 90),
    "J8": (114.0, 53.0, 90),
    "J12": (114.0, 92.0, 90),
    # bottom: pin headers, then the input terminal on the edge
    "J5": (24.0, 104.0, 0),
    "J6": (62.0, 104.0, 0),
    "J7": (80.0, 104.0, 0),
    "J11": (64.0, 114.0, 0),
    # J14 is a SIDE-ENTRY connector (JST SM04B-SRSS-TB: tails out the north
    # wall, cavity and both mounting ears on the south wall), so its opening
    # has to look off-board like every other connector's. Seeded into the
    # BOT1 passive row instead, it landed at (81, 96.8) with the cavity
    # aimed at J7's housing 0.5 mm away - legal to every checker here
    # (courtyards do not overlap) and impossible to plug a Qwiic cable into.
    # Nothing checks mating direction, so it stays pinned: rot 0 already
    # faces +Y, and the bottom edge is free between J11 and H4.
    "J14": (88.0, 115.8, 0),
    # Fiducials. FIXED rather than seeded: the placer aligns the panel optically
    # from these three marks, so their coordinates ARE the specification - a
    # legalizer nudging one to resolve a courtyard overlap would silently move
    # the board's own reference frame. Asymmetric by design so the panel cannot
    # be loaded rotated.
    "FID1": (28.6, 33.0, 0),
    "FID2": (107.8, 28.2, 0),
    "FID3": (103.4, 111.6, 0),
    # TSSOP/QFN anchors: their escape corridors are designed around these.
    # U3 is rot 270 and U5 rot 90 so both SPI rows face the 6 mm channel
    # between them (y 41..46.6) and both analog rows face away from it,
    # toward their own screw terminal.
    "U3": (97.0, 37.8, 270),
    "U5": (97.0, 49.8, 90),
    "U7": (95.0, 72.0, 0),
}

SEED = {
    # --- TOPL: regulator, USB support, EN/BOOT, bulk + module decoupling ---
    "SW1": (91.0, 25.0, 0, "TOPR"),  # noqa
    "LED2": (55.5, 22.3, 0, "TOPA"), "R9": (55.5, 25.0, 0, "TOPA"),
    "TP1": (33.2, 28.6, 0, "TOPA"), "TP2": (36.5, 28.6, 0, "TOPA"),
    "TP3": (39.8, 28.6, 0, "TOPA"),
    "C6": (58.65, 28.0, 90, "TOPA"), "C7": (58.65, 23.8, 90, "TOPA"),
    "R5": (42.0, 33.6, 0, "TOPB"), "U4": (48.0, 34.8, 0, "TOPB"),
    "R4": (53.0, 33.6, 0, "TOPB"), "D2": (56.25, 36.75, 0, "TOPB"),
    "U2": (38.1, 39.5, 0, "TOPB"), "C1": (45.2, 39.5, 0, "TOPB"),
    "C3": (50.2, 39.5, 0, "TOPB"), "C4": (54.3, 39.9, 0, "TOPB"),
    "C5": (52.0, 42.3, 0, "TOPB"), "R1": (56.0, 42.3, 0, "TOPB"),
    "D1": (36.6, 45.6, 0, "TOPC"), "C2": (42.4, 45.6, 0, "TOPC"),
    # --- TOPR: BOOT strap and the bus test points -------------------------
    "SW2": (100.0, 25.0, 0, "TOPR"), "R2": (106.0, 22.5, 0, "TOPR"),
    "TP4": (63.0, 57.0, 0, "MID"), "TP5": (68.0, 57.0, 0, "MID"),
    "TP6": (73.0, 57.0, 0, "MID"), "TP7": (78.0, 57.0, 0, "MID"),
    "TP8": (83.0, 61.5, 0, "MID"),
    # --- SWI: ULN bank, watchdog, buzzer, both SSR driver chains ----------
    "U6": (39.0, 55.0, 180, "SWI"),
    "R23": (46.0, 61.2, 0, "SWI"), "R24": (46.0, 58.0, 0, "SWI"),
    "R25": (46.0, 54.5, 0, "SWI"), "SJ1": (46.0, 49.5, 0, "SWI"),
    # U10 (the retriggerable one-shot) took the pump's slot; C38 is rotated so
    # its two timing pads sit perpendicular to U10's pin row - pins 6 and 7 are
    # 0.5 mm apart on one edge, and lying the cap flat forces one timing net to
    # cross the other's pad.
    # U10 at rot 270 is the only orientation that puts each signal on the side
    # its target is on: pin 2 (WDT_KICK) faces NORTH to the module, and pins
    # 5/6/7 (Q, CT_N, CT_P) face SOUTH to Q3 and the timing cap. The south row
    # reads west-to-east as OK, CT_N, CT_P, +3V3, so WDT_OK gets a straight run
    # down to Q3's gate while the timing pair angles south-east past it and the
    # three never cross. At rot 0 the kick pin faced west with both its
    # terminals east, which is what left it unroutable.
    # U10 at rot 0 with C38 turned 90 deg beside it - the arrangement that
    # routed CT_P, CT_N and WDT_OK cleanly (build 7, zero unconnected). Two
    # other rotations were tried and each fails a different way, so the
    # reasoning is worth keeping: rot 270 aims the timing pair down C38's pad
    # AXIS, and a two-pad part always screens its far pad from a net arriving
    # that way; rot 180 puts C38 and Q3 on the west row, where their pads sit
    # under the escapes and short three nets together. Broadside routes.
    #
    # x = 53.5, not 52.0. WDT_KICK leaves pin 2 westward and its track runs
    # ~2.6 mm; with the part at 52.0 that lands 0.05 mm short of SJ1's AUX_VP
    # pad edge and DRC calls it a short. 53.5 clears it by 1.45 mm. The margin
    # got thinner, not wider, when the package grew from VSSOP-8 to TSSOP-8.
    "U10": (53.5, 49.5, 0, "SWI"), "C38": (58.0, 50.3, 90, "SWI"),
    "C39": (53.5, 53.5, 0, "SWI"), "R46": (58.0, 54.1, 0, "SWI"),
    "Q3": (52.0, 57.5, 0, "SWI"), "SJ2": (57.0, 57.5, 0, "SWI"),
    "TP12": (59.5, 57.0, 0, "SWI"),
    # R48 sits on the west escape, close enough that WDT_KICK turns south to it
    # instead of running on toward SJ1 - which is what shorted AUX_VP.
    "R48": (48.5, 53.0, 0, "SWI"),
    "BZ1": (41.0, 68.95, 0, "SWI"),
    "D4": (65.0, 66.0, 0, "SWI2"), "Q2": (65.0, 70.0, 0, "SWI2"),
    "R11": (65.0, 74.0, 0, "SWI2"), "R8": (65.0, 78.0, 0, "SWI2"),
    "R10": (52.0, 78.0, 0, "SWI"), "LED3": (57.0, 78.0, 0, "SWI"),
    "R6": (49.0, 80.5, 180, "SWI"),
    "R7": (54.0, 80.5, 0, "SWI"), "TP9": (61.0, 78.0, 0, "SWI"),
    # Q4/R47: the watchdog's high-side switch and its fail-safe gate pull-up,
    # in the band the isolation barrier used to reserve, midway between the
    # two terminals SSR_EN feeds.
    "Q4": (40.8, 84.0, 0, "SWI"), "R47": (45.5, 84.0, 0, "SWI"),
    "R21": (52.0, 86.0, 0, "SWI"), "LED4": (57.0, 86.0, 0, "SWI"),
    "R19": (52.0, 92.5, 180, "SWI"),
    "R20": (57.0, 92.5, 0, "SWI"), "TP10": (61.0, 86.0, 0, "SWI"),
    # --- ANA1 / ANA2: the two thermocouple front-ends ---------------------
    # The thermocouple filter network (100R series, 100nF differential, 10nF
    # common-mode) all sits EAST of its MAX31856, between the chip's analog pad
    # row and the screw terminal; only the +3V3 decoupling goes west. Splitting
    # the filter across the chip, as the initial placement did, forced TC1_P_F
    # and TC1_N_F to cross the chip's own fanout to reach their 10 nF caps.
    "C13": (90.0, 35.0, 0, "ANA1W"), "C14": (90.0, 40.5, 0, "ANA1W"),
    # U3 is rot 270, so its analog pad row escapes NORTH; the whole filter
    # sits in one row at that height rather than wrapped around the chip.
    "R14": (102.2, 34.0, 180, "ANA1E"), "R15": (105.9, 34.0, 180, "ANA1E"),
    "C15": (102.2, 38.0, 0, "ANA1E"), "C16": (105.9, 38.0, 0, "ANA1E"),
    "C17": (103.0, 42.0, 0, "ANA1E"),
    "C18": (90.0, 52.6, 0, "ANA2W"), "C19": (90.0, 47.1, 0, "ANA2W"),
    # U5 is rot 90, so its analog row escapes SOUTH; same single-row idea.
    "R16": (102.2, 55.2, 180, "ANA2E"), "R17": (105.9, 55.2, 180, "ANA2E"),
    "C20": (102.2, 50.4, 0, "ANA2E"), "C21": (105.9, 50.4, 0, "ANA2E"),
    "C22": (103.0, 45.6, 0, "ANA2E"),
    # --- ANA3: ADE7953, crystal, straps, decoupling, CT front-end ---------
    "Y1": (103.2, 66.8, 0, "ANA3U"),
    # The crystal sits east of U7, beside the CLKIN/CLKOUT pins it drives,
    # instead of north of it: at 20.3 mm the HC49-SD hand-solder land pattern
    # is a wall, and north of the QFN is where its four north-side pins have to
    # fan out to. x 92..100 in ANA3U stays empty for that fan.
    "C25": (102.1, 64.0, 0, "ANA3U"),
    "R30": (94.3, 60.0, 0, "ANA3T"), "C37": (98.15, 60.0, 0, "ANA3T"),
    "R37": (102.05, 60.0, 0, "ANA3T"), "R38": (105.9, 60.0, 0, "ANA3T"),
    "C29": (88.2, 70.0, 0, "ANA3W"), "C30": (88.2, 73.5, 0, "ANA3W"),
    "C27": (104.8, 69.6, 0, "ANA3E"), "C28": (104.8, 72.5, 0, "ANA3E"),
    "C35": (104.8, 75.4, 0, "ANA3E"), "C36": (98.1, 65.5, 0, "ANA3U"),
    "C33": (89.0, 79.0, 0, "ANA3S"), "C34": (93.0, 79.0, 0, "ANA3S"),
    "J13": (98.5, 79.3, 0, "ANA3S"),
    "R32": (89.0, 83.5, 180, "ANA3S"), "R31": (93.5, 83.5, 0, "ANA3S"),
    "R33": (98.0, 84.85, 0, "ANA3S"), "C31": (103.5, 79.0, 0, "ANA3S"),
    "R35": (89.0, 87.0, 180, "ANA3S"), "R34": (93.5, 87.0, 0, "ANA3S"),
    "R36": (98.0, 87.15, 0, "ANA3S"), "C32": (102.5, 87.1, 0, "ANA3S"),
    "D6": (103.0, 83.5, 0, "ANA3S"), "TP11": (106.5, 84.4, 0, "ANA3S"),
    # --- BOT1: touch damping, I2C tap, status LED -------------------------
    "C11": (42.7, 96.75, 0, "BOT1"),
    "R39": (46.6, 96.6, 0, "BOT1"), "R40": (50.45, 96.5, 0, "BOT1"),
    "R41": (54.3, 96.5, 0, "BOT1"), "R42": (58.2, 96.5, 0, "BOT1"),
    "R43": (62.05, 96.5, 0, "BOT1"),
    "R44": (73.8, 96.5, 0, "BOT1"), "R45": (77.7, 96.5, 0, "BOT1"),
    "R3": (68.0, 88.0, 0, "LEDC"),
    "LED1": (74.0, 88.0, 0, "LEDC"), "D3": (74.0, 93.0, 0, "LEDC"),
    "C10": (80.0, 88.0, 0, "LEDC"),
    # --- BOT2: the three protected dry-contact input filters + TVS --------
    "R12": (35.0, 111.0, 180, "BOT2"), "R13": (40.0, 111.0, 0, "BOT2"),
    "C12": (45.0, 111.0, 0, "BOT2"), "R26": (50.0, 111.0, 180, "BOT2"),
    "R27": (55.0, 111.0, 0, "BOT2"), "C23": (35.0, 115.0, 0, "BOT2"),
    "R28": (40.0, 115.0, 180, "BOT2"), "R29": (45.0, 115.0, 0, "BOT2"),
    "C24": (50.0, 115.0, 0, "BOT2"), "D5": (56.0, 115.0, 0, "BOT2"),
}


def rel_bbox(ref, rot):
    """(dx0, dy0, dx1, dy1) of courtyard+pads relative to the footprint origin."""
    c = COMPONENTS[ref]
    lib, name = c["fp"].split(":", 1)
    fp = KB.load_footprint(lib, name)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    fp.SetOrientationDegrees(rot)
    xs, ys = [], []
    for it in fp.GraphicalItems():
        if it.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
            b = it.GetBoundingBox()
            xs += [b.GetLeft(), b.GetRight()]
            ys += [b.GetTop(), b.GetBottom()]
    for pad in fp.Pads():
        b = pad.GetBoundingBox()
        xs += [b.GetLeft(), b.GetRight()]
        ys += [b.GetTop(), b.GetBottom()]
    return (pcbnew.ToMM(min(xs)), pcbnew.ToMM(min(ys)),
            pcbnew.ToMM(max(xs)), pcbnew.ToMM(max(ys)))


def legalize():
    pos, rot, rel, region = {}, {}, {}, {}
    for ref, (x, y, r) in FIXED.items():
        pos[ref] = [x, y]
        rot[ref] = r
    for ref, (x, y, r, reg) in SEED.items():
        pos[ref] = [x, y]
        rot[ref] = r
        region[ref] = reg
    assert set(pos) == set(COMPONENTS), \
        "unplaced: %s / unknown: %s" % (sorted(set(COMPONENTS) - set(pos)),
                                        sorted(set(pos) - set(COMPONENTS)))
    for ref in pos:
        rel[ref] = rel_bbox(ref, rot[ref])

    refs = sorted(pos)

    def bbox(ref):
        dx0, dy0, dx1, dy1 = rel[ref]
        x, y = pos[ref]
        return (x + dx0, y + dy0, x + dx1, y + dy1)

    def clamp(ref):
        if ref in FIXED:
            return
        rx0, ry0, rx1, ry1 = REGIONS[region[ref]]
        rx0 = max(rx0, BX0 + EDGE)
        ry0 = max(ry0, BY0 + EDGE)
        rx1 = min(rx1, BX1 - EDGE)
        ry1 = min(ry1, BY1 - EDGE)
        dx0, dy0, dx1, dy1 = rel[ref]
        x, y = pos[ref]
        w, h = dx1 - dx0, dy1 - dy0
        if w <= rx1 - rx0:
            x = min(max(x, rx0 - dx0), rx1 - dx1)
        if h <= ry1 - ry0:
            y = min(max(y, ry0 - dy0), ry1 - dy1)
        pos[ref] = [x, y]

    for ref in refs:
        clamp(ref)

    for it in range(4000):
        boxes = {r: bbox(r) for r in refs}
        moved = 0
        for i in range(len(refs)):
            for j in range(i + 1, len(refs)):
                a, b = refs[i], refs[j]
                if a in FIXED and b in FIXED:
                    continue
                A, B = boxes[a], boxes[b]
                ox = min(A[2], B[2]) - max(A[0], B[0]) + GAP
                oy = min(A[3], B[3]) - max(A[1], B[1]) + GAP
                if ox <= 0 or oy <= 0:
                    continue
                moved += 1
                acx, acy = (A[0] + A[2]) / 2, (A[1] + A[3]) / 2
                bcx, bcy = (B[0] + B[2]) / 2, (B[1] + B[3]) / 2
                if ox < oy:
                    d = ox * 0.55 * (1 if acx <= bcx else -1)
                    da, db = (-d, d)
                    ax = 0
                else:
                    d = oy * 0.55 * (1 if acy <= bcy else -1)
                    da, db = (-d, d)
                    ax = 1
                if a in FIXED:
                    db *= 2
                    da = 0
                if b in FIXED:
                    da *= 2
                    db = 0
                pos[a][ax] += da
                pos[b][ax] += db
                clamp(a)
                clamp(b)
                boxes[a], boxes[b] = bbox(a), bbox(b)
        if not moved:
            print("legalized after %d iterations" % it)
            break
    else:
        print("!! still %d overlapping pairs after %d iterations" % (moved, it))

    for ref in refs:
        pos[ref] = [round(v * 20) / 20.0 for v in pos[ref]]
    return pos, rot


def report(pos, rot):
    rel = {r: rel_bbox(r, rot[r]) for r in pos}

    def bbox(ref):
        dx0, dy0, dx1, dy1 = rel[ref]
        x, y = pos[ref]
        return (x + dx0, y + dy0, x + dx1, y + dy1)
    bad = 0
    refs = sorted(pos)
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            A, B = bbox(refs[i]), bbox(refs[j])
            ox = min(A[2], B[2]) - max(A[0], B[0])
            oy = min(A[3], B[3]) - max(A[1], B[1])
            if ox > -0.15 and oy > -0.15:
                bad += 1
                print("  TIGHT %-5s %-5s  %.2f x %.2f" % (refs[i], refs[j], ox, oy))
    for ref in refs:
        A = bbox(ref)
        if A[0] < BX0 + 0.4 or A[1] < BY0 + 0.4 or A[2] > BX1 - 0.4 or A[3] > BY1 - 0.4:
            print("  EDGE  %-5s %.2f %.2f %.2f %.2f" % ((ref,) + A))
    print("tight/overlapping pairs: %d" % bad)


if __name__ == "__main__":
    pos, rot = legalize()
    report(pos, rot)
    out = {r: (pos[r][0], pos[r][1], rot[r]) for r in pos}
    import json
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "floorplan.json"), "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("wrote _place.json")
