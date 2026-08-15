"""Generate bisque-controller.kicad_sch (KiCad 9 format).

Netlist-style schematic: symbols are placed in functional groups, and each
connected pin gets a short wire stub. What terminates that stub depends on
what the net is:

  * a rail (GND, +3V3, +5V, VBUS) ends in a real `power:` port symbol, so it
    is recognised by silhouette rather than read;
  * a two-pin net local to one block is not terminated at all - the two parts
    are placed adjacent and joined by an actual wire carrying a plain local
    label;
  * everything else ends in a global label named after its net.

Unused pins get explicit no-connect markers.
"""
import json
import math
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, Sym, num
from design import COMPONENTS, PWR_FLAG_NETS
import check_sch_layout
import inspect_libs


def _find_sym_base():
    cand = [os.environ.get("KICAD_SYMBOL_DIR", "")]
    cand += ["/usr/share/kicad/symbols",
             "/usr/local/share/kicad/symbols",
             "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
             r"C:\Program Files\KiCad\10.0\share\kicad\symbols",
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "sym")]
    for c in cand:
        if c and os.path.isdir(c):
            return c
    sys.exit("KiCad symbol libraries not found - set KICAD_SYMBOL_DIR")


inspect_libs.SYMDIR = _find_sym_base()
from inspect_libs import flatten, pins_of

NS = uuid.UUID("7c9b1f5e-4a4b-4d1a-9c33-bisque00pcb0".replace("bisque00pcb0", "1234567890ab"))
ROOT = str(uuid.uuid5(NS, "root-sheet"))
PROJECT = "bisque-controller"


def uid(*key):
    return str(uuid.uuid5(NS, "/".join(str(k) for k in key)))


def sync_project(sch_path):
    """Point the .kicad_pro's root-sheet entry at the schematic we just wrote.

    KiCad records the root sheet under `schematic.top_level_sheets`, and it
    writes that block itself the first time anything touches the project -
    which means the working tree grows an unexplained diff after a regen that
    nobody asked for. Worse, *what* it writes depends on who wrote it: the GUI
    knows the schematic's real root uuid, while `kicad-cli pcb` fills
    all-zeros because the PCB tooling never loads a schematic and has no uuid
    to record. Two tools, two answers, and the file flips between them.

    So it is derived here instead, from the same ROOT constant the schematic's
    own `(uuid ...)` comes from. Whoever opens the project next finds the
    entry already correct and leaves it alone - verified: kicad-cli only ever
    *adds* the block when it is missing, and preserves a populated one.

    The rewrite is a whole-file json round-trip, which is safe because KiCad's
    own writer emits plain 2-space-indented JSON: reading and re-dumping the
    untouched file reproduces it byte for byte, so this cannot churn
    formatting the way a hand-rolled patch would.
    """
    pro = os.path.splitext(sch_path)[0] + ".kicad_pro"
    if not os.path.exists(pro):
        return None                      # nothing to keep in step with
    with open(pro) as fh:
        doc = json.load(fh)
    want = [{"filename": os.path.basename(sch_path),
             "name": os.path.splitext(os.path.basename(sch_path))[0],
             "uuid": ROOT}]
    if doc.get("schematic", {}).get("top_level_sheets") == want:
        return False
    doc.setdefault("schematic", {})["top_level_sheets"] = want
    with open(pro, "w") as fh:
        fh.write(json.dumps(doc, indent=2) + "\n")
    return True


def snap(v):
    return round(round(v / 1.27) * 1.27, 4)


# PWR_FLAG symbols have no design.py entry - they are synthesised here, one
# per net in PWR_FLAG_NETS - so give them stable refs the layout can group
# and place like any other part.
FLAG_REFS = ["#FLG%02d" % (i + 1) for i in range(len(PWR_FLAG_NETS))]
FLAG_NET = dict(zip(FLAG_REFS, PWR_FLAG_NETS))


# --- functional grouping ----------------------------------------------------
# The schematic is laid out programmatically, not from a hand-tuned coordinate
# table. A hand table has no collision awareness: this one was authored when
# the board had ~52 parts, grew to 141, and by then the 20-line NOTES block
# printed straight through the AUX OUTPUT BANK header and over U6/J10, while
# half the group headers sat inside their own parts. Containment (which
# check_sch_bounds.py already guaranteed) is not readability.
#
# GROUPS is the only thing still maintained by hand, and it is a *taxonomy*,
# not geometry: every ref in design.py belongs to exactly one functional
# block, and a startup assertion enforces that. Everything below it - block
# extents, column packing, header positions, the NOTES reservation - is
# computed from the actual symbols and the actual text.
#
# Two properties the result must have, both machine-checked:
#   * nothing overlaps anything - check_sch_layout.py;
#   * two symbols' pin-label stubs never coincide, which silently merges two
#     nets - check_netlist.py. That has bitten this project twice. Placement
#     here reserves each symbol's *label-inclusive* extent (body, fields,
#     stub, and the rendered net name at the end of the stub), so facing
#     stubs cannot land on the same point in the first place.
GROUPS = [
    ("POWER IN\n5V DC terminal or USB, ORed Schottky diodes",
     ["J2", "D1", "D2", "U2", "C1", "C2", "C3", "C4", "LED2", "R9"]),
    ("USB-C\nnative USB flashing + ESD",
     ["J1", "U4", "R4", "R5"]),
    ("RESET / BOOT / DECOUPLING",
     ["SW1", "R1", "C5", "SW2", "R2", "C6", "C7", "C11"]),
    ("ESP32-S3-WROOM-1U-N16R2\nGPIOs = firmware Kconfig defaults",
     ["U1"]),
    ("WS2812B STATUS LED\nVDD dropped ~4.6V for 3.3V data margin",
     ["LED1", "R3", "D3", "C10"]),
    ("HEADERS\nJ5 display+touch (14-pin), J6 nav, J7 aux+I2C",
     ["J5", "J6", "J7"]),
    ("THERMOCOUPLE 1 (control)  MAX31856\nT- floats to J3, biased via BIAS",
     ["U3", "C13", "C14", "R14", "R15", "C15", "C16", "C17", "J3"]),
    ("THERMOCOUPLE 2 (load)  MAX31856\nT- floats to J8, biased via BIAS",
     ["U5", "C18", "C19", "R16", "R17", "C20", "C21", "C22", "J8"]),
    ("SSR DRIVE x2\nlow-side AO3400A; indicator LED across each terminal",
     ["Q5", "R6", "R7", "LED3", "R10", "J4",
      "Q6", "R19", "R20", "LED4", "R21", "J9"]),
    ("HARDWARE WATCHDOG\nC38/D7/C39/R46 diode charge pump on WDT_KICK holds\n"
     "Q3 on; Q3 pulls SSR_PG down, turning on high-side Q4, which\n"
     "supplies SSR_EN - the +5V rail feeding BOTH SSR terminals and\n"
     "both indicators. R47 is the fail-safe pull-up.\n"
     "SJ2 = bring-up defeat, REMOVE for service.",
     ["C38", "D7", "C39", "R46", "Q3", "Q4", "R47", "SJ2"]),
    ("AUX OUTPUT BANK\nULN2003 vent/purge/spare; COM->AUX_VP, SJ1 links to +5V",
     ["U6", "R23", "R24", "R25", "J10", "SJ1"]),
    ("ALARM BUZZER",
     ["BZ1", "Q2", "R11", "R8", "D4"]),
    ("PROTECTED INPUTS x3  lid / gas-flow / spare\n"
     "1k + 10k pull-up + 100nF each, SRV05-4 TVS",
     ["R12", "R13", "C12", "R26", "R27", "C23", "R28", "R29", "C24",
      "D5", "J11"]),
    ("CT CURRENT SENSING  ADE7953, I2C, current-only\n"
     "no mains - VP/VN to DNP J13",
     ["U7", "Y1", "C25", "C26", "R30", "C37", "R37", "R38", "C27", "C28",
      "C29", "C30", "C33", "C34", "C35", "C36", "R31", "R32", "R33", "C31",
      "R34", "R35", "R36", "C32", "D6", "J12", "J13"]),
    ("TOUCH DAMPING + I2C EXPANSION\n"
     "R39-R43 damp the shared SPI2 bus for the display module's\n"
     "XPT2046 (not on this board); J14 Qwiic and J7 5-8 (0.1 in)\n"
     "share the I2C bus, pulled up by R44/R45",
     ["J14", "R44", "R45", "R39", "R40", "R41", "R42", "R43"]),
    ("TEST POINTS",
     ["TP1", "TP2", "TP3", "TP4", "TP5", "TP6",
      "TP7", "TP8", "TP9", "TP10", "TP11", "TP12"]),
    ("MOUNTING / POWER FLAGS",
     ["H1", "H2", "H3", "H4",
      "#FLG01", "#FLG02", "#FLG03", "#FLG04", "#FLG05"]),
]

NOTES_TITLE = "NOTES  -  Bisque kiln controller, rev B"
NOTES = (
    "SSR terminals J4/J9: pin1 = SSR_EN (board +5V, watchdog-gated),\n"
    "  pin2 = the switched low side. Boot-safe: R7/R20 hold each\n"
    "  MOSFET gate down while the ESP32 pins are high-impedance.\n"
    "  NOT opto-isolated - rev B tried that and reverted it: an opto\n"
    "  only isolates if the SSR loop is powered off-board, and this\n"
    "  board powers it.\n"
    "\n"
    "TC1 terminal J3 / TC2 terminal J8: pin1 = K+, pin2 = K- - both\n"
    "  float, biased near AGND only through each MAX31856's internal\n"
    "  BIAS network. Ungrounded-junction probes required: two\n"
    "  grounded-junction probes in one kiln would loop through it.\n"
    "\n"
    "Nav switch J6 is panel-mounted; inputs use ESP32 pull-ups.\n"
    "\n"
    "J11: IN1/IN2/IN3 (lid/gas-flow/spare) + GND - dry contact each\n"
    "  channel to GND.\n"
    "\n"
    "Display J5 (14-pin, ST7796S + XPT2046 touch module, LCDWIKI\n"
    "  MSP4021): 1=+5V 2=GND 3=CS 4=RST 5=DC 6=SDI/MOSI 7=SCK 8=BL\n"
    "  9=SDO/MISO 10=T_CLK 11=T_CS 12=T_DIN 13=T_DO 14=T_IRQ.\n"
    "  PIN 1 IS +5V, NOT 3V3 - the module regulates on board; do not\n"
    "  wire a 3.3V-only panel to it. Logic is 3.3V; touch shares SPI2\n"
    "  with the LCD and both MAX31856s (R39-R43 damping).\n"
    "\n"
    "J12: CT current inputs, CTA_P/CTA_N/CTB_P/CTB_N - one CT clamp\n"
    "  per SSR zone.\n"
    "\n"
    "J13: DNP SELV voltage sense header. NOT mains-rated, not fitted\n"
    "  - do not wire to AC mains. Y1/C25/C26 load caps are an ASSUMED\n"
    "  value (unverified C_L), see design.py comment. ADE7953 I2C\n"
    "  address 0x38 collides with PCF8574A."
)

# --- layout engine ----------------------------------------------------------
# A1 landscape (841 x 594 mm). The usable box keeps every anchor well inside
# KiCad's ruled border and clear of the bottom-right title block; the same
# paper table lives in check_sch_bounds.py.
X0, Y0 = 22.0, 26.0
X1, Y1 = 792.0, 548.0

FONT_BODY = 1.27      # symbol fields and net labels
FONT_HDR = 2.0        # group headers
FONT_NOTE = 1.5       # the notes block
CHAR_W = 0.80         # stroke-font advance, em (rounds up from ~0.7)
LINE_H = 1.70         # stroke-font interline, em (rounds up from ~1.6)

GUT_X = 5.0           # gap between two symbols in a row
GUT_Y = 6.0           # gap between two rows inside a group
GUT_GROUP = 11.0      # gap below one group block and the next header
GUT_COL = 13.0        # gap between page columns
HDR_GAP = 3.5         # gap between a header's last line and its block
STUB = 2.54           # wire stub gen_sch emits from every connected pin
N_COLS = 3            # symbol columns; a 4th is the reserved notes column
EXTRA_GAP_MAX = 45.0  # cap on the leftover height spread between groups


def text_extent(txt, size):
    lines = txt.split("\n") or [""]
    return (max(len(ln) for ln in lines) * size * CHAR_W,
            len(lines) * size * LINE_H)


# --- power ports ------------------------------------------------------------
# A boxed global label reading "GND" and one reading "SPI_MOSI" are the same
# shape; a ground triangle is not. Rails are 147 of this sheet's 437 pin
# terminations - GND alone is 91 - and drawing them as real power ports is the
# largest readability win available without changing the netlist style at all:
# the port replaces the label at the same end of the same stub, so no part
# moves.
#
# Membership is *derived*, never listed: a net qualifies exactly when KiCad's
# power library holds a symbol of that name. That is also what makes it safe.
# KiCad takes a `(power global)` symbol's net name from its Value field, so an
# exact name match is the guarantee the net name survives - and
# check_netlist.py round-trips through KiCad to prove it did.
def _power_syms():
    nets = {n for c in COMPONENTS.values() for n in c["pins"].values()}
    nets |= set(PWR_FLAG_NETS)
    nets.discard(None)                # an explicitly unconnected pin
    out = {}
    for net in sorted(nets):
        try:
            out[net] = flatten("power", net)
        except KeyError:
            pass                      # VIN, VLED, AUX_VP, ... - no such port
    return out


PWR = _power_syms()


def pin_outv(pa):
    """Sheet-space direction a wire leaves a pin at library angle `pa`."""
    rad = math.radians(pa)
    return (-math.cos(rad), math.sin(rad))


def power_value_at(sym):
    """An upright port's Value text as (dx, dy, w, h) about its origin.

    Derived - out along the port's own axis, past the body - rather than read
    from the library, whose 3.556 mm for a rail leaves the glyphs 0.06 mm
    inside the bar once you measure them at this generator's (deliberately
    generous) stroke metrics. It lands within 0.01 mm of the library's own
    3.81 mm for GND, so the drawing is unchanged where it was already right.
    """
    bb = check_sch_layout.place(check_sch_layout.lib_body_box(sym),
                                0.0, 0.0, 0.0)
    pv = pin_outv(pins_of(sym)[0][4])       # way the wire leaves the port...
    away = (-pv[0], -pv[1])                 # ...so body and name lie this way
    for p in find_all(sym, "property"):
        if str(p[1]) != "Value" or check_sch_layout.is_hidden(p):
            continue
        size = check_sch_layout.effects_of(p)[0]
        w, h = len(str(p[2])) * size * CHAR_W, size * LINE_H
        reach = (bb[3] if away[1] > 0 else -bb[1]) + h / 2.0 + 0.2
        return (reach * away[0], reach * away[1], w, h)
    return None


def power_extent(sym):
    """Sheet box an upright port covers - body plus Value - about its origin."""
    box = list(check_sch_layout.place(check_sch_layout.lib_body_box(sym),
                                      0.0, 0.0, 0.0))
    v = power_value_at(sym)
    if v:
        dx, dy, w, h = v
        box = [min(box[0], dx - w / 2.0), min(box[1], dy - h / 2.0),
               max(box[2], dx + w / 2.0), max(box[3], dy + h / 2.0)]
    return tuple(box)


def power_path(net, outv, L):
    """Polyline from a pin to its power port, keeping the port upright.

    A ground triangle hangs below its wire and a rail bar sits above it, and
    the *wire* is what bends to meet them. Rotating the port to meet the pin
    instead - which this used to do - drew 35 of 141 ports sideways or upside
    down, and a rail arrow pointing downward reads as a ground.

    The turn is ELBOW, not STUB: a turn of exactly one pin pitch puts the
    port down on the *next pin's own wire*, which is a short waiting to
    happen and reads as one either way. A pitch and a half lands it in the
    clear space between two rows.

    Three cases, by how the pin's own direction relates to the direction the
    wire must be travelling when it arrives:

      already right   straight out, unchanged - and this is the common case,
                      a GND pin facing down or a rail pin facing up
      perpendicular   one elbow: out along the pin, then down (or up) into
                      the port
      exactly wrong   out, across, and back past the pin - a rail hanging off
                      a downward-facing pin has nowhere else to go

    Returns points relative to the pin, ending at the port's origin.
    """
    pv = pin_outv(pins_of(PWR[net])[0][4])   # way the wire leaves the port...
    need = (-pv[0], -pv[1])                  # ...so it must arrive like this
    p1 = (L * outv[0], L * outv[1])
    dot = outv[0] * need[0] + outv[1] * need[1]
    if dot > 0.5:
        return [(0.0, 0.0), p1]
    if abs(dot) < 0.5:
        return [(0.0, 0.0), p1,
                (p1[0] + ELBOW * need[0], p1[1] + ELBOW * need[1])]
    side = (1.0, 0.0) if abs(outv[0]) < 0.5 else (0.0, 1.0)
    p2 = (p1[0] + ELBOW * side[0], p1[1] + ELBOW * side[1])
    return [(0.0, 0.0), p1, p2,
            (p2[0] + (L + ELBOW) * need[0], p2[1] + (L + ELBOW) * need[1])]


# --- stubs and what terminates them -----------------------------------------
# One model, three consumers: the extent reserved by the packer, the field
# placement, and the geometry main() actually emits. They must agree - a
# reserved box that isn't the drawn box is how two stubs land on the same
# point and silently merge two nets - so all three read this.
LANE = 5.08     # extra stub length per crowded lane; > a port's 4.9 mm reach
ELBOW = 3.81    # an elbow's turn: 1.5 pin pitches, so it lands BETWEEN rows
LANE_GAP = 1.27  # gap when two terminators' text runs ALONG the pin row
LANE_CLEAR = 0.25  # ...and when it runs across it, where touching is the risk


def term_extent(net, outv, L=STUB):
    """Sheet box everything past a pin covers, measured from the PIN itself.

    From the pin, not from the stub end: a power port is now reached by a
    wire that may bend twice on the way, so there is no single stub end left
    to measure from.
    """
    sym = PWR.get(net)
    if sym is not None:
        pts = power_path(net, outv, L)
        pb = power_extent(sym)
        xs = [q[0] for q in pts] + [pts[-1][0] + pb[0], pts[-1][0] + pb[2]]
        ys = [q[1] for q in pts] + [pts[-1][1] + pb[1], pts[-1][1] + pb[3]]
        return (min(xs), min(ys), max(xs), max(ys))
    reach = L + len(net) * FONT_BODY * CHAR_W + 2.5
    half = FONT_BODY * LINE_H / 2.0
    padx = 0.0 if abs(outv[0]) > 0.5 else half
    pady = 0.0 if abs(outv[1]) > 0.5 else half
    return (min(0.0, reach * outv[0]) - padx, min(0.0, reach * outv[1]) - pady,
            max(0.0, reach * outv[0]) + padx, max(0.0, reach * outv[1]) + pady)


def stub_pins(sym, pinmap, fused=()):
    """Deduped pins, each with its net, outward direction and stub length.

    Stacked pins (the module's three GND pads on one point) share one stub,
    matching what main() draws. Length is 2.54 mm except where neighbours
    would collide: terminators are wider than the 2.54 mm pin pitch - a GND
    port is 3.05 mm of text under a 2.54 mm triangle - so two adjacent pins
    on the same rail print their names into each other. U7 carries three
    grounds in a row. Pushing every other one further out along its own stub
    separates them without moving the part, the pin, or the net.

    Returns [(pin tuple, net, outv, length)] in library pin order.
    """
    seen, out = set(), []
    for p in pins_of(sym):
        if (p[2], p[3]) in seen:
            continue
        seen.add((p[2], p[3]))
        out.append([p, pinmap.get(p[0]), pin_outv(p[4]), STUB])

    groups = {}
    for row in out:
        p, net, outv, _ = row
        if net is None or p[0] in fused:
            continue          # fused pins end in a wire, not a terminator, so
                              # they neither need a lane nor crowd one. Leaving
                              # them in stretched J3's TC1_N stub to 7.62 mm,
                              # far enough to cross the new TC1_P wire - and
                              # KiCad merged the two nets where the label sat.
        vert = abs(outv[1]) > 0.5
        key = (round(outv[0]), round(outv[1]), round(p[3] if vert else p[2], 3))
        groups.setdefault(key, []).append(row)

    for key, rows in groups.items():
        vert = abs(key[1]) > 0.5

        def _order(r):
            return r[0][2] if vert else -r[0][3]

        def _bent(r):
            return r[1] in PWR and len(power_path(r[1], r[2], STUB)) >= 3

        def pack(rows, base):
            """Greedy interval packing along the pin row, in order along it.

            Walking the rows in library order instead - which is what this
            did - packs a descending pin column as though it ascended, so the
            "is this lane free again" test can never pass and every pin takes
            a fresh lane. U1 came out as a 12-deep staircase reaching 58 mm,
            which is not how anyone draws a module.
            """
            used, reach = [], base - LANE
            for row in sorted(rows, key=_order):
                p, net, outv, _ = row
                tb = term_extent(net, outv, STUB)
                c = _order(row)
                w = max(-tb[0], tb[2]) if vert else max(-tb[1], tb[3])
                # A gap is only wanted where the two terminators' *text* runs
                # along the row and could read as one token - "+3V3+3V3" over
                # U3's AVDD/DVDD pair. That is ports on vertical pins and only
                # those; a column of global labels beside a module just has to
                # not touch, which is what puts them back in one tidy column.
                gap = LANE_GAP if (net in PWR and vert) else LANE_CLEAR
                for i, end in enumerate(used):
                    if c - w >= end + gap - 1e-9:
                        used[i] = c + w
                        row[3] = base + i * LANE
                        break
                else:
                    used.append(c + w)
                    row[3] = base + (len(used) - 1) * LANE
                # How far this terminator actually reaches, text and all -
                # not how long its stub is. An elbow placed a lane past the
                # longest *stub* still turns inside the longest *label*,
                # which is how seven ports came down on top of U7's and
                # J14's net names.
                fb = term_extent(net, outv, row[3])
                reach = max(reach, max(-fb[1], fb[3]) if vert
                            else max(-fb[0], fb[2]))
            return reach

        # Elbows are packed *after* the straight terminators and beyond them,
        # not alongside: an elbow's box is tall (it turns and drops), so
        # letting it take a lane in the first pass evicted J5's own pin
        # labels two lanes out for no reason. They still pack by interval
        # rather than one-per-lane, so two grounds far enough apart down the
        # same side share a depth.
        top = pack([r for r in rows if not _bent(r)], STUB)
        pack([r for r in rows if _bent(r)], top + LANE)
    return out


# --- fused pairs ------------------------------------------------------------
# A net with exactly two pins, both on parts in the same functional block, is
# a local connection - and drawing it as two boxed global labels 199 mm apart
# (LED2 and its own series resistor R9) says nothing a wire would not say
# better. 37 of the 46 block-local nets were drawn more than 60 mm apart,
# median 102 mm, because shelf() packs a group in GROUPS' written order and
# cuts a chain wherever the row happens to end.
#
# Fusing such a pair does two things at once: it emits one real wire instead
# of two labels, and it *forces* the two parts adjacent, because they stop
# being two things the packer may separate and become one cell it places
# whole.
#
# The wire still carries the net's name, as a plain local label on the wire
# rather than a boxed global one. That is not decoration - check_netlist.py
# compares KiCad's exported net names against design.py, and an unnamed wire
# would come back as "Net-(LED2-Pad1)" and fail. One light text replaces two
# heavy boxes.
WIRE = 5.08            # shortest leg of a fused connection
FUSE_STRETCH_MAX = 10  # leg lengthening tried, per leg, before giving up


def _shift(box, d):
    return (box[0] + d[0], box[1] + d[1], box[2] + d[0], box[3] + d[1])


def _shift_seg(seg, d):
    return ((seg[0][0] + d[0], seg[0][1] + d[1]),
            (seg[1][0] + d[0], seg[1][1] + d[1]))


def _seg_box(seg, pad=0.2):
    """A wire as a box, thick enough that check_sch_layout.overlap sees it."""
    (x0, y0), (x1, y1) = seg
    return (min(x0, x1) - pad, min(y0, y1) - pad,
            max(x0, x1) + pad, max(y0, y1) + pad)


def sym_of(ref):
    c = COMPONENTS[ref]
    return flatten(c["lib"], c["sym"])


def pin_xy(sym, no):
    """A pin's connection point relative to its symbol origin, sheet mm."""
    for p in pins_of(sym):
        if p[0] == no:
            return (p[2], -p[3])
    raise KeyError(no)


def pin_dir(sym, no):
    for p in pins_of(sym):
        if p[0] == no:
            return pin_outv(p[4])
    raise KeyError(no)


def fuse_leg(net):
    """Leg length for a fused net - long enough to carry its own name.

    The name is written along one leg, so a leg shorter than the text spills
    off the end of its wire and onto whatever is there: "LEDP_K" is 6.1 mm
    and printed straight over LED2. Sizing the wire to the label makes that
    impossible rather than unlikely, and keeps the offset on the 1.27 mm grid.
    """
    w = text_extent(net, FONT_BODY)[0]
    return max(WIRE, math.ceil((w + 1.27) / 1.27) * 1.27)


def rel_offset(sa, pa, va, sb, pb, vb, leg, s1=0.0, s2=0.0):
    """Where B's origin must sit, with A's origin at (0, 0), to be wired.

    B's pin is placed one leg out along A's pin direction and one leg back
    along B's own, so a straight run (vb == -va) is 2*leg end to end and a
    perpendicular pair turns one corner. `s1` and `s2` lengthen the two legs
    independently, which is how two parts hanging off one neighbour in the
    same direction are kept apart: J1's CC resistors R4/R5 come off pins
    2.54 mm apart and would otherwise be drawn on top of each other. Both
    knobs are needed - lengthening only the first leg slides B along a single
    line, and R5 had to move across it.

    Every term is a multiple of 1.27 mm, which is what lets main() snap each
    member independently without the two drifting apart:
    snap(a + k*1.27) == snap(a) + k*1.27 for integer k.
    """
    apx, apy = pin_xy(sa, pa)
    bpx, bpy = pin_xy(sb, pb)
    dx = apx + va[0] * (leg + s1) - vb[0] * (leg + s2) - bpx
    dy = apy + va[1] * (leg + s1) - vb[1] * (leg + s2) - bpy
    for v in (dx, dy):
        assert abs(v / 1.27 - round(v / 1.27)) < 1e-6, \
            "fused offset %r is off the 1.27 mm grid" % (v,)
    return (dx, dy)


def wire_points(a, b, va, vb):
    """The 1- or 2-segment path from pin A to pin B."""
    if va[0] * vb[0] + va[1] * vb[1] < -0.5:
        return [a, b]
    corner = (b[0], a[1]) if abs(va[0]) > 0.5 else (a[0], b[1])
    return [a, corner, b]


def fuse_pairs():
    """Two-pin block-local nets that can be drawn as a wire, in GROUPS order.

    Skipped, and left as labels: nets that leave their block (the label is
    doing real work there), rails (already ports), and pairs whose two pins
    point the *same* way - those need a U-turn around one of the bodies, and
    a wire that has to be read around a corner twice is not an improvement.
    """
    grp = {r: i for i, (_t, refs) in enumerate(GROUPS) for r in refs}
    net2 = {}
    for ref, c in COMPONENTS.items():
        for pin, net in c["pins"].items():
            if net:
                net2.setdefault(net, []).append((ref, pin))
    out = []
    for net, pins in sorted(net2.items()):   # by net name - deterministic
        if len(pins) != 2 or net in PWR:
            continue
        (ra, pa), (rb, pb) = pins
        if ra == rb or grp.get(ra) != grp.get(rb):
            continue
        va, vb = pin_dir(sym_of(ra), pa), pin_dir(sym_of(rb), pb)
        if va[0] * vb[0] + va[1] * vb[1] > 0.5:
            continue                         # same direction - needs a U-turn
        out.append((net, (ra, pa), (rb, pb), va, vb, fuse_leg(net)))
    return out


def fuse_plan():
    """Group fused pairs into cells, and drop any pair the cell can't honour.

    A cell is placed by walking its pairs outward from a seed, so the first
    pair to reach a part decides where it goes. Any *other* pair between
    already-placed parts - U6 drives three of J10's pins - then has to be
    checked rather than assumed: it is kept only if both legs still run the
    right way, and demoted back to a pair of labels if not. Nothing here may
    silently emit a wire that does not reach.
    """
    pairs = fuse_pairs()
    # Space cell members by their FULL extents, not just their bodies: two
    # resistors can clear each other and still have one's +3V3 port land
    # inside the other, which is exactly what R37 did to R38. Assume every
    # candidate pair fuses; a pair demoted below only ever needs *more* room,
    # and check_sch_layout is the backstop either way.
    cand = {p for it in pairs for p in (it[1], it[2])}
    adj = {}
    for item in pairs:
        adj.setdefault(item[1][0], []).append((item[2][0], item, False))
        adj.setdefault(item[2][0], []).append((item[1][0], item, True))

    def _fu(pins, ref):
        return {p for (rr, p) in pins if rr == ref}

    def _pair_segs(item, pos):
        """The wire a fused pair draws, given both parts' cell offsets."""
        _net, (ra, pa), (rb, pb), va, vb, _leg = item
        apx, apy = pin_xy(sym_of(ra), pa)
        bpx, bpy = pin_xy(sym_of(rb), pb)
        a = (pos[ra][0] + apx, pos[ra][1] + apy)
        b = (pos[rb][0] + bpx, pos[rb][1] + bpy)
        pts = wire_points(a, b, va, vb)
        return list(zip(pts, pts[1:]))

    def grow(seed, blocked):
        """Place a cell outward from `seed`, skipping anything unplaceable."""
        off = {seed: (0.0, 0.0)}
        order, queue = [seed], [seed]
        segs = [_shift_seg(s, (0.0, 0.0))
                for s in member_stubs(seed, _fu(cand, seed))]
        while queue:
            cur = queue.pop(0)
            for other, item, rev in adj[cur]:
                if other in off or other in blocked:
                    continue
                _net, (ra, pa), (rb, pb), va, vb, leg = item
                args = ((sym_of(rb), pb, vb, sym_of(ra), pa, va, leg) if rev
                        else (sym_of(ra), pa, va, sym_of(rb), pb, vb, leg))
                # Least total lengthening first, so a wire is only as long as
                # it has to be - and deterministically so.
                grid = sorted(((i, j) for i in range(FUSE_STRETCH_MAX + 1)
                               for j in range(FUSE_STRETCH_MAX + 1)),
                              key=lambda ij: (ij[0] + ij[1], ij[0]))
                spot = spot_segs = None
                for si, sj in grid:
                    d = rel_offset(*args, s1=si * 2.54, s2=sj * 2.54)
                    at = (off[cur][0] + d[0], off[cur][1] + d[1])
                    box = _shift(ref_extent_box(other, cand), at)
                    if any(check_sch_layout.overlap(
                            box, _shift(ref_extent_box(o, cand), off[o]))
                           for o in order):
                        continue
                    # ...and the new part's stubs and the new wire must not
                    # run along or through anything already drawn. Lengthening
                    # a leg to dodge a body can drop the wire straight down a
                    # neighbour's - R5's did.
                    pos = dict(off)
                    pos[other] = at
                    new = [_shift_seg(s, at)
                           for s in member_stubs(other, _fu(cand, other))]
                    new += _pair_segs(item, pos)
                    if any(check_sch_layout.seg_touch(a, b)
                           for a in new for b in segs):
                        continue
                    # ...nor through a part's body or its printed fields.
                    # Wire-versus-wire is not enough: R4's CC1 wire cleared
                    # every other wire and ran straight down "R5 / 5.1k".
                    others = [o for o in order if o not in (cur, other)]
                    if any(check_sch_layout.overlap(
                            _seg_box(s), _shift(ref_extent_box(o, cand),
                                                off[o]))
                           for s in new for o in others):
                        continue
                    if any(check_sch_layout.overlap(_seg_box(s), box)
                           for s in segs):
                        continue
                    spot, spot_segs = at, new
                    break
                if spot is None:
                    continue          # unplaceable from here; may be re-seeded
                off[other] = spot
                segs += spot_segs
                order.append(other)
                queue.append(other)
        return order, off

    cells, home, seen = [], {}, set()
    for _t, refs in GROUPS:
        for ref in refs:
            if ref in seen or ref not in adj:
                continue
            # The whole connected component, ignoring geometry.
            comp, stack, cset = [], [ref], set()
            while stack:
                r = stack.pop(0)
                if r in cset or r in seen:
                    continue
                cset.add(r)
                comp.append(r)
                stack += [o for o, _i, _r in adj[r]]
            # Which member to start from is not neutral: the first pair to
            # reach a part commits it, and a greedy commitment can leave a
            # later pair nowhere legal to go - seeded at J1, R4 lands where
            # R5 then cannot follow, though seeding at R5 seats both. Cells
            # are two or three parts, so try every seed and keep whichever
            # seats the most wires. Ties go to the earliest seed, so this
            # stays deterministic.
            best = None
            for seed in comp:
                order, off = grow(seed, seen)
                score = sum(1 for it in pairs
                            if it[1][0] in off and it[2][0] in off)
                if best is None or score > best[0]:
                    best = (score, order, off)
            _score, order, off = best
            seen.update(order)
            for r in order:
                home[r] = len(cells)
            cells.append({"refs": order, "off": off, "wires": []})

    kept, dropped = [], []
    for item in pairs:
        net, (ra, pa), (rb, pb), va, vb, _leg = item
        if home.get(ra) != home.get(rb):     # repair could not seat one of them
            dropped.append(net)
            continue
        cell = cells[home[ra]]
        ax, ay = cell["off"][ra]
        bx, by = cell["off"][rb]
        apx, apy = pin_xy(sym_of(ra), pa)
        bpx, bpy = pin_xy(sym_of(rb), pb)
        a = (ax + apx, ay + apy)
        b = (bx + bpx, by + bpy)
        along = (b[0] - a[0]) * va[0] + (b[1] - a[1]) * va[1]
        across = abs((b[0] - a[0]) * va[1] - (b[1] - a[1]) * va[0])
        if va[0] * vb[0] + va[1] * vb[1] < -0.5:        # straight run
            ok, pts = along > 1e-6 and across < 1e-6, [a, b]
        else:                                            # one corner
            corner = (b[0], a[1]) if abs(va[0]) > 0.5 else (a[0], b[1])
            leg_a = (corner[0] - a[0]) * va[0] + (corner[1] - a[1]) * va[1]
            leg_b = (corner[0] - b[0]) * vb[0] + (corner[1] - b[1]) * vb[1]
            ok, pts = leg_a > 1e-6 and leg_b > 1e-6, [a, corner, b]
        if not ok:
            dropped.append(net)
            continue
        cell["wires"].append((net, pts, (ra, pa), (rb, pb)))
        kept.append(item)

    # Each name picks the end of its wire with the least on it. Only the
    # *choice* is stored - main() re-derives the anchor from where the parts
    # actually landed, so the drawn label cannot disagree with the scored one.
    final = {p for it in kept for p in (it[1], it[2])}
    for cell in cells:
        content = []
        for ref in cell["refs"]:
            fu = {p for (rr, p) in final if rr == ref}
            content += [_shift(bx, cell["off"][ref])
                        for bx in member_boxes(ref, fu)]
        picked, wires = [], []
        for net, pts, a, b in cell["wires"]:
            best = None
            for i, (anchor, ang, just) in enumerate(label_options(pts)):
                bx = label_box(net, anchor, ang, just)
                score = sum(check_sch_layout.overlap(bx, o)
                            for o in content + picked)
                if best is None or score < best[0]:
                    best = (score, i, bx)
            picked.append(best[2])
            wires.append((net, pts, a, b, best[1]))
        cell["wires"] = wires
    return cells, home, kept, dropped


def field_pos(sym, pinmap, fused=()):
    """Where a symbol's Reference/Value fields go, relative to its origin.

    Both KiCad's default (above the body) and this generator's original code
    put the fields directly over the space a vertically-oriented pin's stub
    and its terminator occupy - so "R12 / 1k" printed straight through the
    "IN1_RAW" label rising off pin 1. For a part whose pins are *all*
    vertical (every two-pin passive here) the flanks are free instead, so the
    fields go to the right of the body.

    Everything else keeps the classic position above the body, but clearing
    the *whole* upward corridor rather than just the topmost pin. Clearing
    only the pin is what printed "ESP32-S3-WROOM-1U-N16R2" through U1's +3V3
    stub and "MAX31856MUD+" through U3's; nine parts did it, and every one of
    them was invisible to check_sch_layout because it unions a symbol's
    fields into the symbol's own box instead of testing them against it.

    Returns (dx, dy_reference, dy_value) in sheet mm.
    """
    pins = pins_of(sym)
    xs = [p[2] for p in pins] or [0.0]
    ys = [p[3] for p in pins] or [0.0]
    if pins and all(abs(p[4] % 180.0 - 90.0) < 1e-6 for p in pins):
        bx1 = check_sch_layout.lib_body_box(sym)[2]
        return (max(bx1, max(xs)) + 0.9, -0.95, 0.95)
    # The body, not just the topmost pin. A crystal's or a SOIC's outline
    # reaches above its highest pin, so measuring from pins alone dropped the
    # fields inside the part - "3.579545MHz" printed through Y1's plates, and
    # 43 others did the same.
    top = max(max(ys), check_sch_layout.lib_body_box(sym)[3])
    for p, net, outv, L in stub_pins(sym, pinmap, fused):
        if net is None or outv[1] > -0.5 or p[0] in fused:
            continue                                  # not leaving upward
        top = max(top, p[3] - term_extent(net, outv, L)[1])
    return (min(xs), -(top + 3.81), -(top + 3.81) + 1.9)


def body_extent(ref, value, sym, pinmap, fused=()):
    """Reach of just the body and the two visible fields, sheet mm.

    The part of a symbol that is genuinely solid. Cell packing compares these
    rather than full extents, because inside a cell the neighbouring reach is
    the connecting wire, which is the point.
    """
    bx0, by0, bx1, by1 = check_sch_layout.lib_body_box(sym)
    left, right, up, down = -bx0, bx1, by1, -by0
    # The Reference/Value fields, left-justified at field_pos() - mirroring
    # exactly what main() emits, so the reserved box is the drawn box.
    fdx, fdy_ref, fdy_val = field_pos(sym, pinmap, fused)
    fw, fh = text_extent(max(ref, value, key=len), FONT_BODY)
    return (max(left, -fdx), max(right, fdx + fw),
            max(up, -(fdy_ref - fh / 2.0)), max(down, fdy_val + fh / 2.0))


def sym_extent(ref, value, sym, pinmap, fused=()):
    """Reach from a symbol's origin as (left, right, up, down), sheet mm.

    Covers the library body, the Reference/Value fields placed above it, and
    every pin's wire stub plus whatever terminates that stub - a global label
    for a signal, a power port for a rail. Reserving the terminator - not just
    the pin - is what makes a stub-on-stub net merge geometrically impossible.

    A pin in `fused` reaches nowhere: its wire runs to another part inside the
    same cell, and cell_extent() reserves that.
    """
    left, right, up, down = body_extent(ref, value, sym, pinmap, fused)

    for p, net, outv, L in stub_pins(sym, pinmap, fused):
        if p[0] in fused:
            continue
        gx, gy = p[2], -p[3]                          # sheet coords, y down
        tb = (term_extent(net, outv, L) if net is not None
              else (0.0, 0.0, 0.0, 0.0))
        left = max(left, -(gx + tb[0]))
        right = max(right, gx + tb[2])
        up = max(up, -(gy + tb[1]))
        down = max(down, gy + tb[3])
    return (left, right, up, down)


def member_stubs(ref, fused):
    """Stub segments a placed part draws, relative to its own origin."""
    c = COMPONENTS[ref]
    sym = sym_of(ref)
    out = []
    for p, net, outv, L in stub_pins(sym, c["pins"], fused):
        if net is None or p[0] in fused:
            continue
        gx, gy = p[2], -p[3]
        pts = (power_path(net, outv, L) if net in PWR
               else [(0.0, 0.0), (L * outv[0], L * outv[1])])
        out += [((gx + a[0], gy + a[1]), (gx + b[0], gy + b[1]))
                for a, b in zip(pts, pts[1:])]
    return out


def ref_extent_box(ref, fused):
    """sym_extent() for a design.py ref, as a box about its origin."""
    c = COMPONENTS[ref]
    l, r, u, d = sym_extent(ref, c["value"], sym_of(ref), c["pins"],
                            {p for (rr, p) in fused if rr == ref})
    return (-l, -u, r, d)


def label_options(pts):
    """The two ways to write a fused net's name on its own wire.

    From the corner back along either leg, or from the middle of a straight
    run toward either end. fuse_leg() sized every leg to the name, so both
    options fit inside the wire; which one is chosen is decided by what else
    is nearby, since a name that fits its wire can still land on a
    neighbour's label - AUX1_OUT did exactly that to J10's AUX_VP.

    Returns [(anchor, angle, justify), ...].
    """
    if len(pts) == 3:
        ends = [(pts[1], pts[0]), (pts[1], pts[2])]
    else:
        mid = ((pts[0][0] + pts[1][0]) / 2.0, (pts[0][1] + pts[1][1]) / 2.0)
        ends = [(mid, pts[0]), (mid, pts[1])]
    out = []
    for anchor, toward in ends:
        if abs(anchor[1] - toward[1]) < 1e-6:
            out.append((anchor, 0, "left" if toward[0] > anchor[0] else "right"))
        else:
            out.append((anchor, 90, "left" if toward[1] < anchor[1] else "right"))
    return out


def label_box(net, anchor, ang, just):
    """Sheet box of a fused label, matching KiCad's `justify <j> bottom`."""
    w, h = text_extent(net, FONT_BODY)
    x, y = anchor
    if ang == 0:
        x0, x1 = (x, x + w) if just == "left" else (x - w, x)
        return (x0, y - h, x1, y)
    y0, y1 = (y - w, y) if just == "left" else (y, y + w)
    return (x - h, y0, x, y1)


def member_boxes(ref, fused):
    """Everything a placed part occupies, as separate boxes not one hull.

    Choosing where a fused name goes needs the gap between a part's body and
    its own labels, which sym_extent()'s hull has already swallowed.
    """
    c = COMPONENTS[ref]
    sym = sym_of(ref)
    l, r, u, d = body_extent(ref, c["value"], sym, c["pins"], fused)
    out = [(-l, -u, r, d)]
    for p, net, outv, L in stub_pins(sym, c["pins"], fused):
        if net is None or p[0] in fused:
            continue
        gx, gy = p[2], -p[3]
        tb = term_extent(net, outv, L)
        out.append((gx + tb[0], gy + tb[1], gx + tb[2], gy + tb[3]))
    return out


# Deferred to here only because fuse_plan() needs ref_extent_box() above it.
CELLS, CELL_OF, FUSED, FUSE_DROPPED = fuse_plan()
FUSED_PINS = {p for it in FUSED for p in (it[1], it[2])}


def cell_extent(cell, symcache):
    """Reach of a whole fused cell from its anchor, as (left, right, up, down).

    Its parts at their fixed relative offsets, the wires between them, and
    each wire's net-name label - packed as one object, which is what stops
    shelf() from separating two parts that share a wire.
    """
    box = [math.inf, math.inf, -math.inf, -math.inf]
    for ref in cell["refs"]:
        c = COMPONENTS[ref]
        fused = {p for (r, p) in FUSED_PINS if r == ref}
        l, r, u, d = sym_extent(ref, c["value"], symcache[(c["lib"], c["sym"])],
                                c["pins"], fused)
        ox, oy = cell["off"][ref]
        box = [min(box[0], ox - l), min(box[1], oy - u),
               max(box[2], ox + r), max(box[3], oy + d)]
    for net, pts, _a, _b, opt in cell["wires"]:
        for (x, y) in pts:
            box = [min(box[0], x), min(box[1], y),
                   max(box[2], x), max(box[3], y)]
        lb = label_box(net, *label_options(pts)[opt])
        box = [min(box[0], lb[0]), min(box[1], lb[1]),
               max(box[2], lb[2]), max(box[3], lb[3])]
    return (-box[0], box[2], -box[1], box[3])


def build_layout(symcache):
    """Deterministic two-level packer.

    Level 1 shelf-packs a group's symbols into rows no wider than a page
    column; level 2 stacks the group blocks down a column and moves to the
    next column when the block would run past the bottom of the sheet.
    Iteration follows GROUPS' written order throughout - no sorting, no dict
    iteration, no randomness - so a rebuild is byte-identical.

    Returns (at, headers, notes_title_at, notes_body_at).
    """
    listed = [r for _, refs in GROUPS for r in refs]
    assert len(listed) == len(set(listed)), "a ref is in two GROUPS entries"
    missing = [r for r in COMPONENTS if r not in set(listed)]
    assert not missing, "ungrouped refs in design.py: %s" % missing

    # The packer's unit is a *cell*: a fused group of parts with fixed
    # relative offsets, or - for everything not fused - one part on its own.
    # A cell's members are all in one GROUPS entry by construction, since
    # fuse_pairs() only fuses within a block.
    ext, units = {}, []
    for _title, refs in GROUPS:
        out, done = [], set()
        for ref in refs:
            if ref in done:
                continue
            ci = CELL_OF.get(ref)
            if ci is not None and len(CELLS[ci]["refs"]) > 1:
                cell = CELLS[ci]
                key = "cell%d" % ci
                members = [(r, cell["off"][r][0], cell["off"][r][1])
                           for r in cell["refs"]]
                ext[key] = cell_extent(cell, symcache)
                done.update(cell["refs"])
            else:
                key, members = ref, [(ref, 0.0, 0.0)]
                if ref.startswith("#FLG"):
                    sym = symcache[("power", "PWR_FLAG")]
                    value, pinmap = "PWR_FLAG", {"1": FLAG_NET[ref]}
                else:
                    c = COMPONENTS[ref]
                    sym, value, pinmap = symcache[(c["lib"], c["sym"])], \
                        c["value"], c["pins"]
                ext[key] = sym_extent(ref, value, sym, pinmap)
                done.add(ref)
            out.append((key, members))
        units.append(out)

    notes_w, notes_h = text_extent(NOTES, FONT_NOTE)
    nt_w, nt_h = text_extent(NOTES_TITLE, FONT_HDR)
    notes_w = max(notes_w, nt_w)
    notes_block_h = nt_h + HDR_GAP + notes_h

    # The notes column is a hard reservation: its width comes from the real
    # longest line and its height from the real line count, and the packer is
    # only ever handed the space left of it (plus, below the block, the
    # column's own leftovers).
    notes_x = X1 - notes_w
    avail = notes_x - GUT_COL - X0
    colw = (avail - (N_COLS - 1) * GUT_COL) / N_COLS
    cols = [(X0 + i * (colw + GUT_COL), colw, Y0) for i in range(N_COLS)]
    cols.append((notes_x, notes_w, Y0 + notes_block_h + GUT_GROUP))

    def shelf(cells, maxw):
        """Row-pack a group's cells left to right, wrapping at maxw.

        A cell is placed whole, so its members keep the exact relative offsets
        their shared wires require and a row break can no longer land in the
        middle of a two-part chain.
        """
        pos, cx, ry, rowh, bw = [], 0.0, 0.0, 0.0, 0.0
        for key, members in cells:
            l, r, u, d = ext[key]
            w, h = l + r, u + d
            if cx > 0.0 and cx + w > maxw:
                cx, ry, rowh = 0.0, ry + rowh + GUT_Y, 0.0
            for ref, mx, my in members:
                pos.append((ref, cx + l + mx, ry + u + my))
            cx += w + GUT_X
            rowh = max(rowh, h)
            bw = max(bw, cx - GUT_X)
        return pos, bw, ry + rowh

    # Pass 1: how tall is each group at a column's width? Summing that gives
    # the per-column target that keeps the columns balanced. Filling each
    # column to the bottom of the sheet instead would jam two columns full
    # and leave the third a quarter used - legal, but it reads as if the
    # circuit ran out halfway.
    blocks = []
    for (title, _refs), cells in zip(GROUPS, units):
        hh = text_extent(title, FONT_HDR)[1]
        blocks.append((title, cells, hh, hh + HDR_GAP + shelf(cells, colw)[2]))
    target = (sum(b[3] for b in blocks)
              + GUT_GROUP * (len(blocks) - 1)) / N_COLS

    # Pass 2: flow the blocks down the columns, breaking at the target.
    placed = []                       # (col index, y, title, hh, pos, bh)
    ci, cy = 0, cols[0][2]
    for title, cells, hh, _h0 in blocks:
        while True:
            cx0, cw, ctop = cols[ci]
            pos, bw, bh = shelf(cells, cw)
            h = hh + HDR_GAP + bh
            at_top = cy <= ctop + 1e-9
            past_target = (cy - ctop) + h > target and ci < N_COLS - 1
            if at_top or (cy + h <= Y1 and not past_target):
                break
            ci += 1
            if ci >= len(cols):
                sys.exit("schematic layout: out of sheet - enlarge the paper")
            cy = cols[ci][2]
        placed.append((ci, cy, title, hh, pos, bh))
        cy += hh + HDR_GAP + bh + GUT_GROUP

    # Pass 3: spend a column's leftover height on its inter-group gaps rather
    # than leaving it as one dead band at the bottom of the sheet. Only ever
    # increases separation, so it cannot create an overlap.
    shift = {}
    for c in range(len(cols)):
        rows = [i for i, p in enumerate(placed) if p[0] == c]
        if len(rows) < 2:
            continue
        last = placed[rows[-1]]
        slack = Y1 - (last[1] + last[3] + HDR_GAP + last[5])
        step = min(max(slack, 0.0) / (len(rows) - 1), EXTRA_GAP_MAX)
        for k, i in enumerate(rows):
            shift[i] = k * step

    at, headers = {}, []
    for i, (c, y, title, hh, pos, bh) in enumerate(placed):
        cx0 = cols[c][0]
        y += shift.get(i, 0.0)
        headers.append((title, cx0, y + hh / 2.0))
        by = y + hh + HDR_GAP
        for ref, dx, dy in pos:
            at[ref] = (cx0 + dx, by + dy)

    return (at, headers, (notes_x, Y0 + nt_h / 2.0),
            (notes_x, Y0 + nt_h + HDR_GAP + notes_h / 2.0))


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def esc_text(s):
    """Like esc(), but a real newline becomes KiCad's `\\n` line break.

    esc() escapes the backslash, so text carrying a literal "\\n" came out of
    it as "\\\\n" and KiCad plotted the two characters instead of breaking the
    line - which is why the old multi-line group headers rendered as one
    440 mm-wide run of prose.
    """
    return esc(s).replace("\n", "\\n")


def f(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def out_lib_symbols(symcache):
    from sexp import dump
    chunks = []
    for (lib, name), sym in symcache.items():
        s2 = [x if not isinstance(x, list) else x for x in sym]
        s2 = list(sym)
        s2[1] = "%s:%s" % (lib, name)
        chunks.append(dump(s2, 1))
    return chunks


def label_angle(vec):
    vx, vy = vec
    if vx > 0.5:
        return 0, "left"
    if vx < -0.5:
        return 180, "right"
    if vy < -0.5:
        return 90, "left"
    return 270, "right"


def main():
    # collect needed symbols
    symcache = {}
    for ref, c in COMPONENTS.items():
        key = (c["lib"], c["sym"])
        if key not in symcache:
            symcache[key] = flatten(*key)
    symcache[("power", "PWR_FLAG")] = flatten("power", "PWR_FLAG")
    for net, sym in PWR.items():
        symcache[("power", net)] = sym

    AT, HEADERS, NOTES_TITLE_AT, NOTES_AT = build_layout(symcache)

    body = []

    def emit(s):
        body.append(s)

    # Power ports get sequential #PWRnnnn references in emission order, which
    # is COMPONENTS' insertion order and then pin order - deterministic, so a
    # rebuild is byte-identical. check_netlist.py skips every "#" reference,
    # and nothing on the board side reads the schematic, so these exist on
    # this sheet only.
    pwr_seq = [0]

    def emit_terminal(net, lx, ly, outv, key):
        """Terminate a stub: a power port for a rail, a global label else."""
        sym = PWR.get(net)
        if sym is None:
            ang, just = label_angle(outv)
            emit('\t(global_label "%s" (shape %s) (at %s %s %d)\n'
                 '\t\t(effects (font (size 1.27 1.27)) (justify %s))\n'
                 '\t\t(uuid %s)\n'
                 '\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}" (at %s %s 0)\n'
                 '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n\t)'
                 % (esc(net), "passive", f(lx), f(ly), ang,
                    just, uid("lbl", *key), f(lx), f(ly)))
            return
        pwr_seq[0] += 1
        ref = "#PWR%04d" % pwr_seq[0]
        ang = 0                     # never rotated - see power_path()
        vx, vy = power_value_at(sym)[:2]
        emit('\t(symbol (lib_id "power:%s") (at %s %s %d) (unit 1)\n'
             '\t\t(in_bom yes) (on_board yes) (dnp no)\n'
             '\t\t(uuid %s)\n'
             '\t\t(property "Reference" "%s" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(property "Value" "%s" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)))\n\t\t)\n'
             '\t\t(property "Footprint" "" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(property "Datasheet" "" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(pin "1" (uuid %s))\n'
             '\t\t(instances (project "%s" (path "/%s" (reference "%s") (unit 1))))\n'
             '\t)' % (esc(net), f(lx), f(ly), ang, uid("pwr", *key), ref,
                      f(lx), f(ly), esc(net), f(lx + vx), f(ly + vy),
                      f(lx), f(ly), f(lx), f(ly), uid("pwrpin", *key),
                      PROJECT, ROOT, ref))

    # place components
    placed = {}
    for ref, c in COMPONENTS.items():
        sx, sy = AT[ref]
        sx, sy = snap(sx), snap(sy)
        key = (c["lib"], c["sym"])
        sym = symcache[key]
        pins = pins_of(sym)
        pinmap = c["pins"]
        fused_here = {p for (r, p) in FUSED_PINS if r == ref}
        fdx, fdy_ref, fdy_val = field_pos(sym, pinmap, fused_here)
        lib_id = "%s:%s" % key
        libprops = {p[1]: p for p in find_all(sym, "property")}
        ds = libprops.get("Datasheet")
        ds_val = ds[2] if ds else ""
        desc = libprops.get("Description")
        desc_val = desc[2] if desc else ""
        u = uid("sym", ref)
        prop = []
        prop.append('\t\t(property "Reference" "%s" (at %s %s 0)\n'
                    '\t\t\t(effects (font (size 1.27 1.27)) (justify left))\n\t\t)'
                    % (ref, f(sx + fdx), f(sy + fdy_ref)))
        prop.append('\t\t(property "Value" "%s" (at %s %s 0)\n'
                    '\t\t\t(effects (font (size 1.27 1.27)) (justify left))\n\t\t)'
                    % (esc(c["value"]), f(sx + fdx), f(sy + fdy_val)))
        prop.append('\t\t(property "Footprint" "%s" (at %s %s 0)\n'
                    '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)'
                    % (esc(c["fp"]), f(sx), f(sy)))
        prop.append('\t\t(property "Datasheet" "%s" (at %s %s 0)\n'
                    '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)'
                    % (esc(ds_val), f(sx), f(sy)))
        if desc_val:
            prop.append('\t\t(property "Description" "%s" (at %s %s 0)\n'
                        '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)'
                        % (esc(desc_val), f(sx), f(sy)))
        pin_uuid_lines = "".join('\t\t(pin "%s" (uuid %s))\n' % (p[0], uid("pin", ref, p[0]))
                                 for p in pins)
        emit('\t(symbol (lib_id "%s") (at %s %s 0) (unit 1)\n'
             '\t\t(in_bom yes) (on_board yes) (dnp no)\n'
             '\t\t(uuid %s)\n%s\n%s'
             '\t\t(instances (project "%s" (path "/%s" (reference "%s") (unit 1))))\n'
             '\t)' % (lib_id, f(sx), f(sy), u, "\n".join(prop), pin_uuid_lines,
                      PROJECT, ROOT, ref))
        # stubs + terminators / no-connects. stub_pins() collapses stacked
        # pins (module GND 1/40/41, USB VBUS) onto one stub and hands back the
        # same lengths the packer reserved space for.
        placed[ref] = (sx, sy)
        for p, net, outv, L in stub_pins(sym, pinmap, fused_here):
            no = p[0]
            gx, gy = sx + p[2], sy - p[3]
            if (ref, no) in FUSED_PINS:
                continue          # a wire to another part in this cell instead
            if net is None:
                emit('\t(no_connect (at %s %s) (uuid %s))'
                     % (f(gx), f(gy), uid("nc", ref, no)))
                continue
            pts = (power_path(net, outv, L) if net in PWR
                   else [(0.0, 0.0), (L * outv[0], L * outv[1])])
            pts = [(gx + a, gy + b) for a, b in pts]
            for i, (q0, q1) in enumerate(zip(pts, pts[1:])):
                emit('\t(wire (pts (xy %s %s) (xy %s %s))\n'
                     '\t\t(stroke (width 0) (type default))\n'
                     '\t\t(uuid %s)\n\t)'
                     % (f(q0[0]), f(q0[1]), f(q1[0]), f(q1[1]),
                        uid("wire", ref, no, i)))
            emit_terminal(net, pts[-1][0], pts[-1][1], outv, (ref, no))

    # Fused connections. Geometry is re-derived from where the two parts
    # actually landed, not from the cell's planned offsets, so a placement
    # that drifted would produce a visibly wrong wire rather than a
    # plausible one - and the offsets are whole 1.27 mm steps precisely so
    # that snapping each part independently cannot drift them.
    for cell in CELLS:
        for net, _pts, (ra, pa), (rb, pb), opt in cell["wires"]:
            sa, sb = sym_of(ra), sym_of(rb)
            apx, apy = pin_xy(sa, pa)
            bpx, bpy = pin_xy(sb, pb)
            a = (placed[ra][0] + apx, placed[ra][1] + apy)
            b = (placed[rb][0] + bpx, placed[rb][1] + bpy)
            pts = wire_points(a, b, pin_dir(sa, pa), pin_dir(sb, pb))
            for i, (p0, p1) in enumerate(zip(pts, pts[1:])):
                emit('\t(wire (pts (xy %s %s) (xy %s %s))\n'
                     '\t\t(stroke (width 0) (type default))\n'
                     '\t\t(uuid %s)\n\t)'
                     % (f(p0[0]), f(p0[1]), f(p1[0]), f(p1[1]),
                        uid("fuse", net, i)))
            (lx, ly), ang, just = label_options(pts)[opt]
            # A plain local label, not a global one: the net has exactly these
            # two pins, so it needs a name (check_netlist.py diffs KiCad's
            # exported names against design.py) but no box and no cross-sheet
            # machinery.
            emit('\t(label "%s" (at %s %s %d)\n'
                 '\t\t(effects (font (size 1.27 1.27)) (justify %s bottom))\n'
                 '\t\t(uuid %s)\n\t)'
                 % (esc(net), f(lx), f(ly), ang, just, uid("fuselbl", net)))

    # PWR_FLAG instances
    for ref in FLAG_REFS:
        net = FLAG_NET[ref]
        sx, sy = AT[ref]
        sx, sy = snap(sx), snap(sy)
        u = uid("sym", ref)
        emit('\t(symbol (lib_id "power:PWR_FLAG") (at %s %s 0) (unit 1)\n'
             '\t\t(in_bom yes) (on_board yes) (dnp no)\n'
             '\t\t(uuid %s)\n'
             '\t\t(property "Reference" "%s" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(property "Value" "PWR_FLAG" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(property "Footprint" "" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(property "Datasheet" "~" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n'
             '\t\t(pin "1" (uuid %s))\n'
             '\t\t(instances (project "%s" (path "/%s" (reference "%s") (unit 1))))\n'
             '\t)' % (f(sx), f(sy), u, ref, f(sx), f(sy - 4), f(sx), f(sy - 6),
                      f(sx), f(sy), f(sx), f(sy), uid("pin", ref, "1"),
                      PROJECT, ROOT, ref))
        # The flag's pin is at its own origin and points down, so a rail
        # flag - +5V, VBUS - is the "exactly wrong" case and its wire has to
        # come back up past the flag. This has to walk power_path() like any
        # other pin; hard-coding a 2.54 mm stub put #FLG02's and #FLG03's
        # ports on top of the flags themselves.
        outv = (0.0, 1.0)
        pts = (power_path(net, outv, STUB) if net in PWR
               else [(0.0, 0.0), (0.0, STUB)])
        pts = [(sx + a, sy + b) for a, b in pts]
        for i, (q0, q1) in enumerate(zip(pts, pts[1:])):
            emit('\t(wire (pts (xy %s %s) (xy %s %s))\n'
                 '\t\t(stroke (width 0) (type default))\n'
                 '\t\t(uuid %s)\n\t)'
                 % (f(q0[0]), f(q0[1]), f(q1[0]), f(q1[1]), uid("wire", ref, i)))
        emit_terminal(net, pts[-1][0], pts[-1][1], outv, (ref,))

    # group headers, then the reserved notes block
    def emit_text(txt, x, y, size, bold, key):
        emit('\t(text "%s" (at %s %s 0)\n'
             '\t\t(effects (font (size %s %s)%s) (justify left))\n'
             '\t\t(uuid %s)\n\t)'
             % (esc_text(txt), f(x), f(y), f(size), f(size),
                " bold" if bold else "", uid("txt", key)))

    for txt, x, y in HEADERS:
        emit_text(txt, x, y, FONT_HDR, True, txt)
    emit_text(NOTES_TITLE, NOTES_TITLE_AT[0], NOTES_TITLE_AT[1],
              FONT_HDR, True, "notes-title")
    emit_text(NOTES, NOTES_AT[0], NOTES_AT[1], FONT_NOTE, False, "notes")

    libsyms = out_lib_symbols(symcache)

    out = []
    out.append('(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0")')
    out.append('\t(uuid %s)' % ROOT)
    # A1 (841 x 594 mm), not A3, and the layout engine's X0/Y0/X1/Y1 above
    # are the usable box inside it. The packed content is ~715 x 546 mm: the
    # three symbol columns plus the reserved notes column do not fit A3's
    # 420 x 297, and A2's 594 x 420 is short in both axes. On A3 the exported
    # PDF silently clipped about 40% of the circuit while every connectivity
    # checker stayed green; check_sch_bounds.py now fails on any item outside
    # whatever this line declares, and check_sch_layout.py on any overlap.
    # Growing the sheet means growing X1/Y1 and PAPER's entry to match.
    out.append('\t(paper "A1")')
    out.append('\t(title_block\n\t\t(title "Bisque Kiln Controller")\n'
               '\t\t(date "2026-07-20")\n\t\t(rev "B")\n'
               '\t\t(company "Bisque project")\n'
               '\t\t(comment 1 "ESP32-S3-WROOM-1U-N16R2 + 2x MAX31856 + dual SSR + ADE7953")\n'
               '\t\t(comment 2 "4-layer, 100 x 100 mm, JLCPCB standard process")\n\t)')
    out.append('\t(lib_symbols\n\t\t' + "\n\t\t".join(libsyms) + '\n\t)')
    out.extend(body)
    out.append('\t(sheet_instances (path "/" (page "1")))')
    out.append(')')
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    dst = sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_sch"
    # Never let a demotion be silent: a pair that could not be seated falls
    # back to a pair of global labels, which is correct but is not what the
    # fusing was for.
    print("fused %d two-pin nets into wires across %d cells"
          % (len(FUSED), sum(1 for c in CELLS if len(c["refs"]) > 1)))
    if FUSE_DROPPED:
        print("  NOT fused (no clear placement found, left as labels): %s"
              % ", ".join(FUSE_DROPPED))
    text = main()
    with open(dst, "w") as fh:
        fh.write(text)
    print("wrote %s (%d bytes)" % (dst, len(text)))
    changed = sync_project(dst)
    if changed is not None:
        print("  root sheet in .kicad_pro: %s"
              % ("updated" if changed else "already in step"))
