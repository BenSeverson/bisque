"""Generate JLCPCB assembly files (BOM.csv + CPL.csv) from design.py.

Every LCSC part number below was verified live against the LCSC catalog
(package, value and stock) — see VERIFIED_ON. Re-verify before a production
run, since stock and part status drift.

CPL coordinates follow KiCad's footprint-position convention (Y negated).
Rotations are KiCad angles plus a per-package correction, because JLCPCB's
pick-and-place uses a different zero-rotation reference for some package
families; see JLC_ROTATION.

Parts in HAND_SOLDER are deliberately left off *both* files and written to
hand-solder-parts.csv instead — see that table for why. JLCPCB's PCBA upload
rejects a CPL carrying designators the BOM doesn't have, so a part must drop
out of both or neither.
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import COMPONENTS

VERIFIED_ON = "2026-07-29"

# JLCPCB's pick-and-place zero-rotation reference differs from KiCad's for
# several package families. These corrections come from the community-
# maintained table in bennymeg/Fabrication-Toolkit
# (plugins/transformations.csv), which is derived from real JLCPCB order
# feedback rather than guesswork.
#
# Families absent from that table need no correction. That notably includes
# chip passives (R/C/LED 0805, 1206), SMA and SOD-123 diodes, the WS2812B
# PLCC-4, the ESP32-S3-WROOM-1 module, USB-C, terminal blocks, 2.54 mm
# headers and 6 mm tactile switches — for all of these KiCad's orientation
# already matches JLCPCB's.
#
# Matched against the bare footprint name (the part after "Library:"),
# first match wins.
JLC_ROTATION = (
    (r"^SOT-223", 180),
    (r"^SOT-23", 180),
    (r"^SOIC-8_", 270),
    (r"^SOIC-", 270),
    (r"^D_SOT-23", 180),
    (r"^QFN-", 90),
    (r"^DFN-", 270),
    (r"^TSSOP-", 270),
    (r"^SSOP-", 270),
    (r"^MSOP-", 270),
    (r"^LQFP-", 270),
    (r"^TQFP-", 270),
)


def jlc_rotation(fp_name, kicad_rot):
    """KiCad angle -> JLCPCB CPL angle. Returns (angle, offset_applied)."""
    for pattern, offset in JLC_ROTATION:
        if re.match(pattern, fp_name):
            return (kicad_rot + offset) % 360, offset
    return kicad_rot % 360, 0


# ref -> (LCSC part, description, basic_part, verified)
LCSC = {
    "U1": ("C3013945", "ESP32-S3-WROOM-1U-N16R2 (16MB flash, 2MB quad PSRAM, U.FL)", False, True),
    "U2": ("C6186", "AMS1117-3.3 SOT-223", True, True),
    "U3": ("C52028", "MAX31855KASA+T SOIC-8", False, True),
    "U4": ("C7519", "USBLC6-2SC6 SOT-23-6", False, True),
    "Q1": ("C20917", "AO3400A SOT-23", True, True),
    "Q2": ("C20917", "AO3400A SOT-23", True, True),
    "D1": ("C8678", "SS34 SMA", True, True),
    "D2": ("C8678", "SS34 SMA", True, True),
    "D3": ("C2480", "SS14 SMA", True, True),
    "D4": ("C81598", "1N4148W SOD-123", True, True),
    "LED1": ("C2761795", "WS2812B-B/T 5050 RGB", False, True),
    "LED2": ("C2297", "KT-0805G green LED 0805", True, True),
    "LED3": ("C2296", "KT-0805Y yellow LED 0805", True, True),
    "R1": ("C17414", "10k 0805 1%", True, True),
    "R2": ("C17414", "10k 0805 1%", True, True),
    "R3": ("C17630", "330R 0805 1%", True, True),
    "R4": ("C27834", "5.1k 0805 1%", True, True),
    "R5": ("C27834", "5.1k 0805 1%", True, True),
    "R6": ("C17408", "100R 0805 1%", True, True),
    "R7": ("C17414", "10k 0805 1%", True, True),
    "R8": ("C17414", "10k 0805 1%", True, True),
    "R9": ("C17513", "1k 0805 1%", True, True),
    "R10": ("C17798", "680R 0805 1%", True, True),
    "R11": ("C17408", "100R 0805 1%", True, True),
    "R12": ("C17513", "1k 0805 1%", True, True),
    "R13": ("C17414", "10k 0805 1%", True, True),
    "C1": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "C2": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C3": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "C4": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C5": ("C28323", "CL21B105KBFNNNE 1uF 50V X7R 0805", True, True),
    "C6": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C7": ("C15850", "CL21A106KAYNNNE 10uF 25V X5R 0805", True, True),
    "C8": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    # C1710, not C57112: C57112 is an 0603 part and this land pattern is 0805.
    "C9": ("C1710", "CL21B103KBANNNC 10nF 50V X7R 0805", True, True),
    "C10": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C11": ("C15850", "CL21A106KAYNNNE 10uF 25V X5R 0805", True, True),
    "C12": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "BZ1": ("C96093", "TMB12A05 active magnetic buzzer 5V 12mm THT P7.6", False, True),
    "J1": ("C165948", "HRO TYPE-C-31-M-12 USB-C 16P", False, True),
    "J2": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J3": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J4": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J5": ("C240822", "Molex 22-27-2081 KK-254 friction-lock wafer 1x08", False, True),
    "J6": ("C239381", "A2547WV-6P KK-254 friction-lock wafer 1x06", False, True),
    "J7": ("C240822", "Molex 22-27-2081 KK-254 friction-lock wafer 1x08", False, True),
    "SW1": ("C318884", "TS-1187A-B-A-B 5.1x5.1mm SMD tactile switch", True, True),
    "SW2": ("C318884", "TS-1187A-B-A-B 5.1x5.1mm SMD tactile switch", True, True),
}

# Parts fitted by hand rather than by JLCPCB.
#
# Each unique Extended part costs a $3 feeder-loading fee regardless of how
# many boards are built, and any through-hole part forces the whole order
# onto Standard assembly (Economic is SMD, top-side only) with a per-joint
# charge on top. The seven through-hole parts here are $1.45/board of
# connectors and a buzzer on 2.54 mm and 5.08 mm pitch — the easiest joints
# on the board — but between them they carried four of the ten unique
# Extended parts. LED1 is the fifth: no addressable RGB LED at LCSC is a
# Basic part (checked across WS2812/SK6812/XL-xxxx), so its $3 buys nothing
# a soldering iron can't do to a 5050 with four edge-accessible pads.
#
# Dropping these takes the order from 10 unique Extended parts to 4 (U1, U3,
# U4, J1) and from Standard assembly to Economic. The remaining SMD parts are
# the ones where machine placement is actually worth paying for.
HAND_SOLDER = {
    "BZ1",                            # 12 mm buzzer, 7.6 mm pitch
    "J2", "J3", "J4",                 # 5.08 mm screw terminals
    "J5", "J6", "J7",                 # KK-254 friction-lock wafers
    "LED1",                           # WS2812B, PLCC-4 5050
}

# Second source at Mouser for the hand-fitted parts, keyed by LCSC part
# number, so the shopping list works against either supplier.
#
# Three of these five are Chinese generics on LCSC and the Mouser column is
# the *genuine* part the KiCad footprint was drawn from — so it fits at least
# as well, clone dimensional tolerance being the usual source of trouble. It
# also costs several times more: a real Phoenix MKDS is dollars against cents
# for the WJ500V clone, taking this list from ~$1.50/board to roughly
# $8–12/board.
#
# Verified 2026-07-31 by MPN and datasheet, *not* by live API — there is no
# Mouser API key configured and Mouser blocks automated page fetches. Confirm
# stock and price at order time.
MOUSER_ALT = {
    "C240822": ("22-27-2081", "Molex",
                "identical part - the LCSC line is already genuine Molex"),
    "C239381": ("22-27-2061", "Molex",
                "genuine KK-254 1x06; LCSC line is an A2547WV clone"),
    "C8465": ("1715721", "Phoenix Contact",
              "MKDS 1,5/2-5,08 - the part this footprint is named for"),
    "C96093": ("CMI-1295-0585T", "Same Sky",
               "12x9.5mm body, 7.6mm pitch, 5V THT active - datasheet-verified"),
    # Mouser hosts WS2812B datasheets and sells third-party modules built on
    # it, but no bare Worldsemi 5050 could be found in their catalog.
    "C2761795": ("", "",
                 "NOT AT MOUSER - source from LCSC, DigiKey, Adafruit or SparkFun"),
}

_FP_ATTR_CACHE = {}


def is_through_hole(fpf):
    """True when the footprint file declares (attr through_hole)."""
    if fpf not in _FP_ATTR_CACHE:
        path = os.path.join(os.path.dirname(__file__), "fp", fpf)
        try:
            with open(path) as fh:
                _FP_ATTR_CACHE[fpf] = "(attr through_hole)" in fh.read()
        except OSError:
            _FP_ATTR_CACHE[fpf] = False
    return _FP_ATTR_CACHE[fpf]


def assembly_refs():
    """Refs that go to assembly, in design order (mounting holes excluded)."""
    return [ref for ref in COMPONENTS if not ref.startswith("H")]


def group_by_part(refs):
    """refs -> {(value, footprint, lcsc): [ref, ...]}"""
    groups = {}
    for ref in refs:
        c = COMPONENTS[ref]
        part = LCSC.get(ref)
        key = (c["value"], c["fp"], part[0] if part else "")
        groups.setdefault(key, []).append(ref)
    return groups


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    bom_path = os.path.join(outdir, "BOM.csv")
    cpl_path = os.path.join(outdir, "CPL.csv")
    hand_path = os.path.join(outdir, "hand-solder-parts.csv")

    all_refs = assembly_refs()
    refs = [r for r in all_refs if r not in HAND_SOLDER]
    hand_refs = [r for r in all_refs if r in HAND_SOLDER]

    groups = group_by_part(refs)

    missing = [r for r in refs if not (LCSC.get(r) or ("",))[0]]
    tht = sorted({r for r in refs if is_through_hole(COMPONENTS[r]["fpf"])})

    with open(bom_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Notes"])
        for (value, fp, lcsc), grefs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            part = LCSC.get(grefs[0])
            note = part[1] if part else ""
            if part and not part[3]:
                note += " [CONFIRM part # at order time]"
            if not lcsc:
                note += " [NO LCSC PART - will not be assembled]"
            if is_through_hole(COMPONENTS[grefs[0]]["fpf"]):
                note += " [THT - needs Standard assembly; confirm JLC can place it]"
            w.writerow([value, ",".join(grefs), fp.split(":", 1)[1], lcsc, note])

    corrections = []
    with open(cpl_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in refs:
            c = COMPONENTS[ref]
            x, y, rot = c["at"]
            fp_name = c["fp"].split(":", 1)[1]
            jrot, offset = jlc_rotation(fp_name, rot)
            if offset:
                corrections.append((ref, fp_name, rot, jrot, offset))
            w.writerow([ref, "%.3fmm" % x, "%.3fmm" % (-y), "Top", "%.1f" % jrot])

    # Shopping list for the parts JLCPCB is *not* fitting. Same LCSC part
    # numbers, so it can be pasted straight into an LCSC cart alongside the
    # PCBA order — but nothing here is bound to LCSC's catalogue any more,
    # which matters for the KK-254 wafers (the lowest-stock lines on the BOM).
    no_alt = []
    with open(hand_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Comment", "Footprint", "LCSC Part #",
                    "Qty per board", "Description",
                    "Mouser MPN", "Mouser Manufacturer", "Second-source note"])
        for (value, fp, lcsc), grefs in sorted(group_by_part(hand_refs).items(),
                                               key=lambda kv: kv[1][0]):
            part = LCSC.get(grefs[0])
            mpn, mfr, note = MOUSER_ALT.get(lcsc, ("", "", ""))
            if not mpn:
                no_alt.append("%s (%s)" % (",".join(grefs), lcsc))
            w.writerow([",".join(grefs), value, fp.split(":", 1)[1], lcsc,
                        len(grefs), part[1] if part else "",
                        mpn, mfr, note])

    ext = {LCSC[r][0] for r in refs if r in LCSC and not LCSC[r][2]}
    print("wrote %s, %s, %s" % (bom_path, cpl_path, hand_path))
    print("%d parts to JLCPCB (%d BOM lines), %d hand-soldered, LCSC verified %s"
          % (len(refs), len(groups), len(hand_refs), VERIFIED_ON))
    print("%d unique Extended part(s) -> $%d in feeder fees: %s"
          % (len(ext), 3 * len(ext), ", ".join(sorted(ext))))
    print("hand-soldered: %s" % ", ".join(sorted(hand_refs)))
    if no_alt:
        print("  no Mouser second source for: %s" % ", ".join(no_alt))
    if corrections:
        print("JLCPCB rotation corrections applied (%d):" % len(corrections))
        for ref, fp_name, rot, jrot, offset in corrections:
            print("  %-5s %-28s %3.0f -> %3.0f (+%d)" % (ref, fp_name, rot, jrot, offset))
    if tht:
        print("WARNING: through-hole parts still in the assembly BOM (forces "
              "Standard assembly): %s" % ", ".join(tht))
    else:
        print("no through-hole parts in the assembly BOM -> Economic "
              "(SMD, top-side) assembly is sufficient")
    if missing:
        print("WARNING: no LCSC part for: %s" % ", ".join(missing))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "jlcpcb")
