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
    # thermocouple rows (right) - TC1 (control) then TC2 (load) below it
    "U3": (250, 95), "C13": (268, 95), "C14": (286, 95), "R14": (304, 95),
    "R15": (322, 95), "C15": (340, 95), "C16": (358, 95), "C17": (376, 95),
    "J3": (394, 95),
    "U5": (250, 135), "C18": (268, 135), "C19": (286, 135), "R16": (304, 135),
    "R17": (322, 135), "C20": (340, 135), "C21": (358, 135), "C22": (376, 135),
    "J8": (394, 135),
    # ssr rows (right) - two opto-isolated channels, ch2 8mm south of ch1
    "U8": (210, 155), "R6": (240, 153), "R7": (266, 157), "LED3": (296, 153),
    "R10": (296, 163), "R18": (326, 157), "J4": (356, 155),
    # SJ3/SJ4: the per-channel "+5V -> opto collector" solder links. East of
    # their own terminal, >=20mm clear of every neighbour (the pin-label-stub
    # merge hazard the SSR/aux rows document above).
    "SJ3": (386, 155),
    "U9": (213, 178), "R19": (243, 176), "R20": (269, 180), "LED4": (299, 176),
    "R21": (299, 186), "R22": (329, 180), "J9": (359, 178),
    "SJ4": (389, 178),
    # aux output bank (vent/purge/spare) - own row, clear of everything else.
    # Device:R symbols need >12.7mm vertical spacing when stacked at the same
    # x: each pin's label stub extends 2.54mm past the pin (at +-3.81mm from
    # the symbol origin), so facing pins on adjacent resistors land their
    # *labels* on the same point - a short - even once the pins themselves
    # are clear. 20mm gives solid margin; this is exactly the Task 7 hazard
    # the brief warned about (it hit the pin-point version of this).
    "U6": (60, 300), "R23": (94, 280), "R24": (94, 300), "R25": (94, 320),
    "J10": (140, 300), "SJ1": (170, 280),
    # buzzer row (right)
    "BZ1": (235, 195), "Q2": (266, 197), "R11": (296, 193), "R8": (322, 197),
    "D4": (350, 193),
    # ws2812 row
    "LED1": (40, 170), "R3": (78, 168), "D3": (108, 168), "C10": (134, 170),
    # headers row
    "J5": (40, 215), "J6": (76, 215), "J7": (112, 215),
    # protected dry-contact inputs (lid/gas-flow/spare) - channel 1 is rev
    # A's lid filter, unmoved; channels 2/3 extend the row eastward, then
    # the TVS array and terminal. All entries here are >=20mm apart in x
    # or y (Task 7/8 pin-label-stub-merge hazard).
    "R12": (152, 222), "R13": (180, 222), "C12": (208, 222),
    "R26": (236, 222), "R27": (264, 222), "C23": (292, 222),
    "R28": (320, 222), "R29": (348, 222), "C24": (376, 222),
    "D5": (208, 250), "J11": (260, 250),
    # en/boot + decoupling row (bottom left)
    "SW1": (40, 258), "R1": (74, 258), "C5": (100, 258), "SW2": (130, 258),
    "R2": (164, 258), "C6": (196, 258), "C7": (222, 258), "C11": (248, 258),
    # mounting holes
    "H1": (330, 252), "H2": (352, 252), "H3": (374, 252), "H4": (396, 252),
    # CT current sensing (ADE7953, Task 10) - fresh area clear of everything
    # else on the page. Entries are on a 30mm grid (>=28mm apart in x or y),
    # the Task 9 hazard margin: Device:R/C symbols stacked closer than that
    # let facing pin-label stubs coincide and silently short two nets
    # (Task 7 SSR2_IND_A/ALARM, Task 8 GND/AUX2/AUX3).
    "U7": (430, 40), "Y1": (460, 40), "C25": (490, 40), "C26": (520, 40),
    "R30": (550, 40),
    "C37": (430, 70), "R37": (460, 70), "R38": (490, 70), "C27": (520, 70),
    "C28": (550, 70),
    "C29": (430, 100), "C30": (460, 100), "C33": (490, 100),
    "C34": (520, 100), "C35": (550, 100),
    "C36": (430, 130), "R31": (460, 130), "R32": (490, 130),
    "R33": (520, 130), "C31": (550, 130),
    "R34": (430, 160), "R35": (460, 160), "R36": (490, 160),
    "C32": (520, 160), "D6": (550, 160),
    "J12": (430, 190), "J13": (460, 190),
    # Touch damping + I2C expansion (Task 11) - fresh area clear of
    # everything else on the page, 30mm grid (>=28mm apart in x or y), the
    # Task 9/10 hazard margin: Device:R symbols stacked closer than that let
    # facing pin-label stubs coincide and silently short two nets.
    "J14": (25, 350), "R44": (55, 350), "R45": (85, 350),
    "R39": (25, 380), "R40": (55, 380), "R41": (85, 380),
    "R42": (115, 380), "R43": (145, 380),
    # Hardware watchdog (Task 12) - fresh area clear of everything else,
    # 30mm grid (>=28mm apart in x or y), the Task 9/10/11 hazard margin:
    # Device:R/C symbols stacked closer than that let facing pin-label
    # stubs coincide and silently short two nets.
    "C38": (25, 430), "D7": (55, 430), "C39": (85, 430),
    "R46": (115, 430), "Q3": (145, 430), "SJ2": (175, 430),
    # Test points (Task 13) - fresh area clear of everything else,
    # 30mm grid (>=28mm apart in x or y), the Task 9/10/11/12 hazard margin:
    # Device:R/C symbols stacked closer than that let facing pin-label
    # stubs coincide and silently short two nets.
    "TP1": (25, 490), "TP2": (55, 490), "TP3": (85, 490), "TP4": (115, 490),
    "TP5": (145, 490), "TP6": (175, 490),
    "TP7": (25, 520), "TP8": (55, 520), "TP9": (85, 520), "TP10": (115, 520),
    "TP11": (145, 520), "TP12": (175, 520),
}

GROUP_TEXT = [
    ("POWER IN  (5V DC terminal or USB, ORed Schottky diodes)", 25, 22),
    ("USB-C  (native USB flashing + ESD)", 25, 66),
    ("WS2812B STATUS LED  (VDD dropped ~4.6V for 3.3V data margin)", 25, 150),
    ("HEADERS  DISPLAY+TOUCH(J5, 14-pin) NAV(J6) AUX+I2C(J7)", 25, 198),
    ("PROTECTED INPUTS x3  lid/gas-flow/spare  (1k + 10k pull-up + 100nF each, SRV05-4 TVS)",
     145, 205),
    ("RESET / BOOT / DECOUPLING", 25, 240),
    ("ESP32-S3-WROOM-1  (GPIOs = firmware Kconfig defaults)", 140, 130),
    ("THERMOCOUPLE 1 (control)  MAX31856  (T- floats to J3, biased via BIAS)", 225, 82),
    ("THERMOCOUPLE 2 (load)  MAX31856  (T- floats to J8, biased via BIAS)", 225, 122),
    ("SSR DRIVE x2  (opto-isolated, LTV-817S; indicator LED parallel branch)",
     195, 143),
    ("ALARM BUZZER", 225, 180),
    ("MOUNTING / POWER FLAGS", 290, 238),
    ("AUX OUTPUT BANK  (ULN2003 vent/purge/spare; COM->AUX_VP, SJ1 links to +5V)",
     25, 280),
    ("CT CURRENT SENSING  ADE7953, I2C, current-only  (no mains - VP/VN to DNP J13)",
     430, 20),
    ("TOUCH DAMPING + I2C EXPANSION  (Task 11)  R39-43 damp the shared SPI2\\n"
     "bus for the display module's XPT2046 (not on this board); J14 Qwiic +\\n"
     "J7 5-8 (0.1\") share the I2C bus, pulled up by R44/R45",
     25, 340),
    ("HARDWARE WATCHDOG  (Task 12)  C38/D7/C39/R46 diode charge pump on\\n"
     "WDT_KICK holds Q3 on; Q3 gates SSR_EN (both opto + both indicator LED\\n"
     "returns). SJ2 = bring-up defeat, REMOVE for service.",
     25, 420),
]

NOTES = (
    "Bisque kiln controller  -  ESP32-S3-WROOM-1U-N16R2 (rev B)\\n"
    "SSR terminals J4/J9: opto-isolated (LTV-817S), boot-safe (R7/R20 pulldown).\\n"
    "SSR1_A/B, SSR2_A/B float - no GND/+3V3/+5V on the isolated side. SJ3/SJ4\\n"
    "  are per-channel solder links to +5V, SHIPPED OPEN: closing one sources the\\n"
    "  SSR1/SSR2 collector from board +5V and gives up that channel's isolation.\\n"
    "SSR_EN is the shared opto+indicator cathode return, gated by the watchdog.\\n"
    "TC1 terminal J3 / TC2 terminal J8: pin1 = K+, pin2 = K- - both float, biased near\\n"
    "AGND only through each MAX31856's internal BIAS network. Ungrounded-junction\\n"
    "probes required: two grounded-junction probes in one kiln would loop through it.\\n"
    "Nav switch J6 is panel-mounted; inputs use ESP32 internal pull-ups\\n"
    "J11: IN1/IN2/IN3 (lid/gas-flow/spare) + GND - dry contact each channel to GND\\n"
    "Display J5 (14-pin, ST7796S + XPT2046 touch module - LCDWIKI MSP4021):\\n"
    "  1=+5V 2=GND 3=CS 4=RST 5=DC 6=SDI/MOSI 7=SCK 8=BL 9=SDO/MISO\\n"
    "  10=T_CLK 11=T_CS 12=T_DIN 13=T_DO 14=T_IRQ.  PIN 1 IS +5V, NOT 3V3 - the\\n"
    "  module regulates on board; do not wire a 3.3V-only panel to it. Logic is\\n"
    "  3.3V; touch shares SPI2 with the LCD and both MAX31856s (R39-R43 damping)\\n"
    "J12: CT current inputs, CTA_P/CTA_N/CTB_P/CTB_N - one CT clamp per SSR zone.\\n"
    "J13: DNP SELV voltage sense header. NOT mains-rated, not fitted - do not wire\\n"
    "  to AC mains. Y1/C25/C26 load caps are an ASSUMED value (unverified C_L),\\n"
    "  see design.py comment. ADE7953 I2C address 0x38 collides with PCF8574A."
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
    out.append('(kicad_sch (version 20260306) (generator "eeschema") (generator_version "10.0")')
    out.append('\t(uuid %s)' % ROOT)
    # A1 (841 x 594 mm), not A3. SCH_AT spreads the rev B blocks over roughly
    # 565 x 522 mm of sheet - the ADE7953, ULN2003, touch, watchdog and
    # test-point rows all live well past A3's 420 x 297 mm, and A2's 594 x 420
    # is still 100 mm too short in y. On A3 the exported PDF silently clipped
    # about 40% of the circuit while every connectivity checker stayed green;
    # check_sch_bounds.py now fails on any item that falls outside whatever
    # this line declares.
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
