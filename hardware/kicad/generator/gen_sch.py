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
import inspect_libs


def _find_sym_base():
    cand = [os.environ.get("KICAD_SYMBOL_DIR", "")]
    cand += ["/usr/share/kicad/symbols",
             "/usr/local/share/kicad/symbols",
             "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
             r"C:\Program Files\KiCad\10.0\share\kicad\symbols",
             r"C:\Program Files\KiCad\9.0\share\kicad\symbols",
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


# --- schematic placement (symbol origin, mm) --------------------------------
SCH_AT = {
    "U1": (170, 165),
    # power row
    "J2": (30, 40), "D1": (62, 40), "D2": (90, 40), "U2": (122, 40),
    "C1": (152, 40), "C2": (176, 40), "C3": (200, 40), "C4": (224, 40),
    "LED2": (252, 40), "R9": (280, 40),
    # usb row
    "J1": (36, 88), "U4": (88, 88), "R4": (122, 88), "R5": (148, 88),
    # thermocouple row (right)
    "U3": (250, 110), "J3": (302, 110), "C8": (330, 110), "C9": (356, 110),
    # ssr row (right)
    "Q1": (235, 155), "R6": (270, 153), "R7": (296, 155), "J4": (326, 155),
    "LED3": (356, 153), "R10": (384, 155),
    # buzzer row (right)
    "BZ1": (235, 195), "Q2": (266, 197), "R11": (296, 193), "R8": (322, 197),
    "D4": (350, 193),
    # ws2812 row
    "LED1": (40, 170), "R3": (78, 168), "D3": (108, 168), "C10": (134, 170),
    # headers row
    "J5": (40, 215), "J6": (76, 215), "J7": (112, 215),
    # en/boot + decoupling row (bottom left)
    "SW1": (40, 258), "R1": (74, 258), "C5": (100, 258), "SW2": (130, 258),
    "R2": (164, 258), "C6": (196, 258), "C7": (222, 258), "C12": (248, 258),
    # mounting holes
    "H1": (330, 252), "H2": (352, 252), "H3": (374, 252), "H4": (396, 252),
}

GROUP_TEXT = [
    ("POWER IN  (5V DC terminal or USB, ORed Schottky diodes)", 25, 22),
    ("USB-C  (native USB flashing + ESD)", 25, 66),
    ("WS2812B STATUS LED  (VDD dropped ~4.6V for 3.3V data margin)", 25, 150),
    ("HEADERS  DISPLAY(J5) NAV(J6) AUX(J7)", 25, 198),
    ("RESET / BOOT / DECOUPLING", 25, 240),
    ("ESP32-S3-WROOM-1  (GPIOs = firmware Kconfig defaults)", 140, 130),
    ("THERMOCOUPLE  MAX31855 (T- grounded per datasheet)", 225, 92),
    ("SSR DRIVE  (low-side switch, J4 supplies the +5V loop)", 225, 138),
    ("ALARM BUZZER", 225, 180),
    ("MOUNTING / POWER FLAGS", 290, 238),
]

NOTES = (
    "Bisque kiln controller  -  ESP32-S3-WROOM-1, hand-solderable parts only\\n"
    "SSR terminal J4: +5V / SSR- loop, switched low-side by Q1 (boot-safe: R7 pulldown)\\n"
    "TC terminal J3: pin1 = K+ (yellow), pin2 = K- (red, grounded at U3)\\n"
    "Nav switch J6 is panel-mounted; inputs use ESP32 internal pull-ups\\n"
    "Display J5 pinout: 3V3 GND CS RST DC MOSI SCK BL (ST7796S SPI module)"
)


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


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

    body = []

    def emit(s):
        body.append(s)

    # place components
    for ref, c in COMPONENTS.items():
        sx, sy = SCH_AT[ref]
        sx, sy = snap(sx), snap(sy)
        key = (c["lib"], c["sym"])
        sym = symcache[key]
        pins = pins_of(sym)
        pinmap = c["pins"]
        # bbox of pins for property placement
        ys = [p[3] for p in pins] or [0]
        xs = [p[2] for p in pins] or [0]
        top = sy - max(ys) - 3.81
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
                    % (ref, f(sx + min(xs)), f(top)))
        prop.append('\t\t(property "Value" "%s" (at %s %s 0)\n'
                    '\t\t\t(effects (font (size 1.27 1.27)) (justify left))\n\t\t)'
                    % (esc(c["value"]), f(sx + min(xs)), f(top + 1.9)))
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
    fx0, fy0 = 294, 248
    flag_pins = pins_of(symcache[("power", "PWR_FLAG")])
    for i, net in enumerate(PWR_FLAG_NETS):
        sx = snap(fx0 + (i % 3) * 13)
        sy = snap(fy0 + (i // 3) * 14)
        ref = "#FLG%02d" % (i + 1)
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

    # group titles + notes
    for txt, x, y in GROUP_TEXT:
        emit('\t(text "%s" (at %s %s 0)\n'
             '\t\t(effects (font (size 2 2) bold) (justify left))\n'
             '\t\t(uuid %s)\n\t)' % (esc(txt), f(x), f(y), uid("txt", txt)))
    emit('\t(text "%s" (at 25 281 0)\n'
         '\t\t(effects (font (size 1.6 1.6)) (justify left))\n'
         '\t\t(uuid %s)\n\t)' % (NOTES, uid("txt", "notes")))

    libsyms = out_lib_symbols(symcache)

    out = []
    out.append('(kicad_sch (version 20230121) (generator eeschema)')
    out.append('\t(uuid %s)' % ROOT)
    out.append('\t(paper "A3")')
    out.append('\t(title_block\n\t\t(title "Bisque Kiln Controller")\n'
               '\t\t(date "2026-07-20")\n\t\t(rev "A")\n'
               '\t\t(company "Bisque project")\n'
               '\t\t(comment 1 "ESP32-S3-WROOM-1 + MAX31855 + SSR drive")\n'
               '\t\t(comment 2 "Hand-solderable: >=0805, SOIC, SOT, THT connectors")\n\t)')
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
