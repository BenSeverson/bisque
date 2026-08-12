"""Generate bisque-controller.kicad_sch (KiCad 9 format).

Netlist-style schematic: symbols are placed in functional groups; every
connected pin gets a short wire stub ending in a global label named after
its net. Unused pins get explicit no-connect markers.
"""
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


def field_pos(sym):
    """Where a symbol's Reference/Value fields go, relative to its origin.

    Both KiCad's default (above the body) and this generator's original code
    put the fields directly over the space a vertically-oriented pin's stub
    and global label occupy - so "R12 / 1k" printed straight through the
    "IN1_RAW" label rising off pin 1. For a part whose pins are *all*
    vertical (every two-pin passive here) the flanks are free instead, so
    the fields go to the right of the body; everything else keeps the
    classic position above it.

    Returns (dx, dy_reference, dy_value) in sheet mm.
    """
    pins = pins_of(sym)
    xs = [p[2] for p in pins] or [0.0]
    ys = [p[3] for p in pins] or [0.0]
    if pins and all(abs(p[4] % 180.0 - 90.0) < 1e-6 for p in pins):
        bx1 = check_sch_layout.lib_body_box(sym)[2]
        return (max(bx1, max(xs)) + 0.9, -0.95, 0.95)
    return (min(xs), -(max(ys) + 3.81), -(max(ys) + 3.81) + 1.9)


def sym_extent(ref, value, sym, pinmap):
    """Reach from a symbol's origin as (left, right, up, down), sheet mm.

    Covers the library body, the Reference/Value fields placed above it, and
    every pin's wire stub plus the global label drawn at the end of that
    stub. Reserving the label - not just the pin - is what makes a
    stub-on-stub net merge geometrically impossible.
    """
    import math
    bx0, by0, bx1, by1 = check_sch_layout.lib_body_box(sym)
    left, right, up, down = -bx0, bx1, by1, -by0

    pins = pins_of(sym)
    # The Reference/Value fields, left-justified at field_pos() - mirroring
    # exactly what main() emits, so the reserved box is the drawn box.
    fdx, fdy_ref, fdy_val = field_pos(sym)
    fw, fh = text_extent(max(ref, value, key=len), FONT_BODY)
    left = max(left, -fdx)
    right = max(right, fdx + fw)
    up = max(up, -(fdy_ref - fh / 2.0))
    down = max(down, fdy_val + fh / 2.0)

    half = FONT_BODY * LINE_H / 2.0 + 0.6
    for no, name, px, py, pa, etype, style in pins:
        net = pinmap.get(no)
        rad = math.radians(pa)
        ovx, ovy = -math.cos(rad), math.sin(rad)      # sheet coords, y down
        reach = STUB
        if net is not None:
            reach += len(net) * FONT_BODY * CHAR_W + 2.5
        gx, gy = px, -py
        ex, ey = gx + reach * ovx, gy + reach * ovy
        padx = 0.0 if abs(ovx) > 0.5 else half
        pady = 0.0 if abs(ovy) > 0.5 else half
        left = max(left, -min(gx, ex) + padx)
        right = max(right, max(gx, ex) + padx)
        up = max(up, -min(gy, ey) + pady)
        down = max(down, max(gy, ey) + pady)
    return (left, right, up, down)


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

    ext = {}
    for _title, refs in GROUPS:
        for ref in refs:
            if ref.startswith("#FLG"):
                sym = symcache[("power", "PWR_FLAG")]
                value, pinmap = "PWR_FLAG", {"1": FLAG_NET[ref]}
            else:
                c = COMPONENTS[ref]
                sym, value, pinmap = symcache[(c["lib"], c["sym"])], \
                    c["value"], c["pins"]
            ext[ref] = sym_extent(ref, value, sym, pinmap)

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

    def shelf(refs, maxw):
        """Row-pack a group's members left to right, wrapping at maxw."""
        pos, cx, ry, rowh, bw = [], 0.0, 0.0, 0.0, 0.0
        for ref in refs:
            l, r, u, d = ext[ref]
            w, h = l + r, u + d
            if cx > 0.0 and cx + w > maxw:
                cx, ry, rowh = 0.0, ry + rowh + GUT_Y, 0.0
            pos.append((ref, cx + l, ry + u))
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
    for title, refs in GROUPS:
        hh = text_extent(title, FONT_HDR)[1]
        blocks.append((title, refs, hh, hh + HDR_GAP + shelf(refs, colw)[2]))
    target = (sum(b[3] for b in blocks)
              + GUT_GROUP * (len(blocks) - 1)) / N_COLS

    # Pass 2: flow the blocks down the columns, breaking at the target.
    placed = []                       # (col index, y, title, hh, pos, bh)
    ci, cy = 0, cols[0][2]
    for title, refs, hh, _h0 in blocks:
        while True:
            cx0, cw, ctop = cols[ci]
            pos, bw, bh = shelf(refs, cw)
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

    AT, HEADERS, NOTES_TITLE_AT, NOTES_AT = build_layout(symcache)

    body = []

    def emit(s):
        body.append(s)

    # place components
    for ref, c in COMPONENTS.items():
        sx, sy = AT[ref]
        sx, sy = snap(sx), snap(sy)
        key = (c["lib"], c["sym"])
        sym = symcache[key]
        pins = pins_of(sym)
        pinmap = c["pins"]
        fdx, fdy_ref, fdy_val = field_pos(sym)
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
        # stubs + labels / no-connects
        seen_nopin = set()
        for no, name, px, py, pa, etype, style in pins:
            gx, gy = sx + px, sy - py
            if (gx, gy) in seen_nopin:
                # stacked pins (e.g. module GND 1/40/41, USB VBUS) share one point
                continue
            seen_nopin.add((gx, gy))
            net = pinmap.get(no, None)
            if net is None:
                emit('\t(no_connect (at %s %s) (uuid %s))'
                     % (f(gx), f(gy), uid("nc", ref, no)))
                continue
            import math
            rad = math.radians(pa)
            outv = (-math.cos(rad), math.sin(rad))  # sheet coords (y down)
            lx, ly = gx + 2.54 * outv[0], gy + 2.54 * outv[1]
            emit('\t(wire (pts (xy %s %s) (xy %s %s))\n'
                 '\t\t(stroke (width 0) (type default))\n'
                 '\t\t(uuid %s)\n\t)'
                 % (f(gx), f(gy), f(lx), f(ly), uid("wire", ref, no)))
            ang, just = label_angle(outv)
            emit('\t(global_label "%s" (shape %s) (at %s %s %d)\n'
                 '\t\t(effects (font (size 1.27 1.27)) (justify %s))\n'
                 '\t\t(uuid %s)\n'
                 '\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}" (at %s %s 0)\n'
                 '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n\t)'
                 % (esc(net), "passive" if True else "input", f(lx), f(ly), ang,
                    just, uid("lbl", ref, no), f(lx), f(ly)))

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
        # flag pin is at symbol origin; stub down to a label
        lx, ly = sx, sy + 2.54
        emit('\t(wire (pts (xy %s %s) (xy %s %s))\n'
             '\t\t(stroke (width 0) (type default))\n'
             '\t\t(uuid %s)\n\t)' % (f(sx), f(sy), f(lx), f(ly), uid("wire", ref)))
        emit('\t(global_label "%s" (shape passive) (at %s %s 270)\n'
             '\t\t(effects (font (size 1.27 1.27)) (justify right))\n'
             '\t\t(uuid %s)\n'
             '\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}" (at %s %s 0)\n'
             '\t\t\t(effects (font (size 1.27 1.27)) hide)\n\t\t)\n\t)'
             % (esc(net), f(lx), f(ly), uid("lbl", ref), f(lx), f(ly)))

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
    text = main()
    with open(dst, "w") as fh:
        fh.write(text)
    print("wrote %s (%d bytes)" % (dst, len(text)))
