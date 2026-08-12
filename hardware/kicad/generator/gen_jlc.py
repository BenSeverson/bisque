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

Designators in NOT_ASSEMBLED (test points, solder jumpers, the DNP AC-sense
header) are excluded even earlier, before HAND_SOLDER is consulted — they
have no manufactured part at all, so they must not appear in the shopping
list either.
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import COMPONENTS

VERIFIED_ON = "2026-08-11"

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
    "BZ1": ("C96093", "TMB12A05 active magnetic buzzer 5V 12mm THT P7.6", False, True),
    "C1": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "C2": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C3": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "C4": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C5": ("C28323", "CL21B105KBFNNNE 1uF 50V X7R 0805", True, True),
    "C6": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C7": ("C15850", "CL21A106KAYNNNE 10uF 25V X5R 0805", True, True),
    "C10": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C11": ("C15850", "CL21A106KAYNNNE 10uF 25V X5R 0805", True, True),
    "C12": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C13": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C14": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C15": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C16": ("C1710", "CL21B103KBANNNC 10nF 50V X7R 0805", True, True),
    "C17": ("C1710", "CL21B103KBANNNC 10nF 50V X7R 0805", True, True),
    "C18": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C19": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C20": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C21": ("C1710", "CL21B103KBANNNC 10nF 50V X7R 0805", True, True),
    "C22": ("C1710", "CL21B103KBANNNC 10nF 50V X7R 0805", True, True),
    "C23": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C24": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C25": ("C107114", "CC0805JRNPO9BN300 30pF 50V NP0 0805", False, True),
    "C26": ("C107114", "CC0805JRNPO9BN300 30pF 50V NP0 0805", False, True),
    "C27": ("C1779", "CL21A475KAQNNNE 4.7uF 25V X5R 0805", True, True),
    "C28": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C29": ("C1779", "CL21A475KAQNNNE 4.7uF 25V X5R 0805", True, True),
    "C30": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C31": ("C1739", "0805B333K500NT 33nF 50V X7R 0805", True, True),
    "C32": ("C1739", "0805B333K500NT 33nF 50V X7R 0805", True, True),
    "C33": ("C1779", "CL21A475KAQNNNE 4.7uF 25V X5R 0805", True, True),
    "C34": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C35": ("C15850", "CL21A106KAYNNNE 10uF 25V X5R 0805", True, True),
    "C36": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C37": ("C28323", "CL21B105KBFNNNE 1uF 50V X7R 0805", True, True),
    "C38": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C39": ("C28323", "CL21B105KBFNNNE 1uF 50V X7R 0805", True, True),
    "D1": ("C8678", "SS34 SMA", True, True),
    "D2": ("C8678", "SS34 SMA", True, True),
    "D3": ("C2480", "SS14 SMA", True, True),
    "D4": ("C81598", "1N4148W SOD-123", True, True),
    "D5": ("C558418", "SRV05-4 TVS array SOT-23-6", False, True),
    "D6": ("C558418", "SRV05-4 TVS array SOT-23-6", False, True),
    "D7": ("C7420333", "BAT54S dual series Schottky SOT-23", False, True),
    "J1": ("C165948", "HRO TYPE-C-31-M-12 USB-C 16P", False, True),
    "J2": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J3": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J4": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J5": ("C17701004", "XD-2510-14A KK-254 friction-lock wafer 1x14", False, True),
    "J6": ("C239381", "A2547WV-6P KK-254 friction-lock wafer 1x06", False, True),
    "J7": ("C240822", "Molex 22-27-2081 KK-254 friction-lock wafer 1x08", False, True),
    "J8": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J9": ("C8465", "WJ500V-5.08-2P 5.08mm screw terminal 1x02", False, True),
    "J10": ("C42377749", "WJ500V-5.08-04P 5.08mm screw terminal 1x04", False, True),
    "J11": ("C42377749", "WJ500V-5.08-04P 5.08mm screw terminal 1x04", False, True),
    "J12": ("C42377749", "WJ500V-5.08-04P 5.08mm screw terminal 1x04", False, True),
    "J14": ("C160404", "JST SM04B-SRSS-TB(LF)(SN) SH 1x04", False, True),
    "LED1": ("C2761795", "WS2812B-B/T 5050 RGB", False, True),
    "LED2": ("C2297", "KT-0805G green LED 0805", True, True),
    "LED3": ("C2296", "KT-0805Y amber LED 0805", True, True),
    "LED4": ("C2296", "KT-0805Y amber LED 0805", True, True),
    "Q2": ("C20917", "AO3400A SOT-23", True, True),
    "Q3": ("C20917", "AO3400A SOT-23", True, True),
    "R1": ("C17414", "10k 0805 1%", True, True),
    "R2": ("C17414", "10k 0805 1%", True, True),
    "R3": ("C17630", "330R 0805 1%", True, True),
    "R4": ("C27834", "5.1k 0805 1%", True, True),
    "R5": ("C27834", "5.1k 0805 1%", True, True),
    "R6": ("C17557", "220R 0805 1%", True, True),
    "R7": ("C17414", "10k 0805 1%", True, True),
    "R8": ("C17414", "10k 0805 1%", True, True),
    "R9": ("C17513", "1k 0805 1%", True, True),
    "R10": ("C17798", "680R 0805 1%", True, True),
    "R11": ("C17408", "100R 0805 1%", True, True),
    "R12": ("C17513", "1k 0805 1%", True, True),
    "R13": ("C17414", "10k 0805 1%", True, True),
    "R14": ("C17408", "100R 0805 1%", True, True),
    "R15": ("C17408", "100R 0805 1%", True, True),
    "R16": ("C17408", "100R 0805 1%", True, True),
    "R17": ("C17408", "100R 0805 1%", True, True),
    "R18": ("C17477", "0R 0805 jumper", True, True),
    "R19": ("C17557", "220R 0805 1%", True, True),
    "R20": ("C17414", "10k 0805 1%", True, True),
    "R21": ("C17798", "680R 0805 1%", True, True),
    "R22": ("C17477", "0R 0805 jumper", True, True),
    "R23": ("C17414", "10k 0805 1%", True, True),
    "R24": ("C17414", "10k 0805 1%", True, True),
    "R25": ("C17414", "10k 0805 1%", True, True),
    "R26": ("C17513", "1k 0805 1%", True, True),
    "R27": ("C17414", "10k 0805 1%", True, True),
    "R28": ("C17513", "1k 0805 1%", True, True),
    "R29": ("C17414", "10k 0805 1%", True, True),
    "R30": ("C17414", "10k 0805 1%", True, True),
    "R31": ("C17774", "0805W8F680KT5E 6.8R 0805 1%", False, True),
    "R32": ("C17513", "1k 0805 1%", True, True),
    "R33": ("C17513", "1k 0805 1%", True, True),
    "R34": ("C17774", "0805W8F680KT5E 6.8R 0805 1%", False, True),
    "R35": ("C17513", "1k 0805 1%", True, True),
    "R36": ("C17513", "1k 0805 1%", True, True),
    "R37": ("C17414", "10k 0805 1%", True, True),
    "R38": ("C17414", "10k 0805 1%", True, True),
    "R39": ("C17634", "33R 0805 1%", True, True),
    "R40": ("C17634", "33R 0805 1%", True, True),
    "R41": ("C17634", "33R 0805 1%", True, True),
    "R42": ("C17634", "33R 0805 1%", True, True),
    "R43": ("C17634", "33R 0805 1%", True, True),
    "R44": ("C17673", "4.7k 0805 1%", True, True),
    "R45": ("C17673", "4.7k 0805 1%", True, True),
    "R46": ("C17514", "1M 0805 1%", True, True),
    "SW1": ("C318884", "TS-1187A-B-A-B 5.1x5.1mm SMD tactile switch", True, True),
    "SW2": ("C318884", "TS-1187A-B-A-B 5.1x5.1mm SMD tactile switch", True, True),
    "U1": ("C3013945", "ESP32-S3-WROOM-1U-N16R2 (16MB flash, 2MB quad PSRAM, U.FL)", False, True),
    "U2": ("C6186", "AMS1117-3.3 SOT-223", True, True),
    "U3": ("C2653162", "MAX31856MUD+T TSSOP-14", False, True),
    "U4": ("C7519", "USBLC6-2SC6 SOT-23-6", False, True),
    "U5": ("C2653162", "MAX31856MUD+T TSSOP-14", False, True),
    "U6": ("C7512", "ULN2003ADR SOIC-16 Darlington array", True, True),
    "U7": ("C515890", "ADE7953ACPZ-RL LFCSP-28 energy metering", False, True),
    "U8": ("C109227", "LTV-817S-TA1-C optocoupler SMD-4P", True, True),
    "U9": ("C109227", "LTV-817S-TA1-C optocoupler SMD-4P", True, True),
    "Y1": ("C7471632", "3.579545MHz crystal HC-49S-SMD", False, True),
}

# Board features with no manufactured part: excluded from the BOM, the CPL,
# AND hand-solder-parts.csv. HAND_SOLDER (below) is the wrong bucket for
# these - it feeds hand-solder-parts.csv, a shopping list meant to be pasted
# into a cart, and a designator with no LCSC number would land there as a
# blank-LCSC row (a part to "buy" that isn't a part). assembly_refs() drops
# these before either bucket sees them, the same way mounting holes already
# are.
#
# TP1-TP12: 1 mm bring-up test pads (Task 13) - bare copper, nothing to
# place or buy. SJ1-SJ4: open solder-jumper footprints (AUX_VP<-+5V link,
# WDT bring-up defeat, and the two per-channel SSR collector<-+5V links) -
# populated with solder, not a component. J13: a
# fitted-but-DNP 2-pin header for a future SELV AC-sense accessory (Task 10)
# - "NO MAINS ON THIS BOARD" per design.py, so this build does not stuff it.
NOT_ASSEMBLED = {
    "TP1", "TP2", "TP3", "TP4", "TP5", "TP6",
    "TP7", "TP8", "TP9", "TP10", "TP11", "TP12",
    "SJ1", "SJ2", "SJ3", "SJ4",
    "J13",
}

# Parts fitted by hand rather than by JLCPCB.
#
# Each unique Extended part costs a $3 feeder-loading fee regardless of how
# many boards are built, and any through-hole part forces the whole order
# onto Standard assembly (Economic is SMD, top-side only) with a per-joint
# charge on top. The through-hole parts here are connectors and a buzzer on
# 2.54 mm and 5.08 mm pitch — the easiest joints on the board. LED1 is added
# for cost, not solderability: no addressable RGB LED at LCSC is a Basic
# part (checked across WS2812/SK6812/XL-xxxx), so its $3 buys nothing a
# soldering iron can't do to a 5050 with four edge-accessible pads.
#
# This takes the order from Standard assembly (any THT part forces it) to
# Economic (SMD, top-side only) - see the task 15 report for the resulting
# unique-Extended-part count. The remaining SMD parts are the ones where
# machine placement is actually worth paying for.
HAND_SOLDER = {
    "BZ1",                                     # 12 mm buzzer, 7.6 mm pitch
    "J2", "J3", "J4", "J8", "J9",              # 5.08 mm screw terminals (2-pos)
    "J10", "J11", "J12",                       # 5.08 mm screw terminals (4-pos)
    "J5", "J6", "J7",                          # KK-254 friction-lock wafers
    "LED1",                                    # WS2812B, PLCC-4 5050
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
    """True when the footprint file declares (attr through_hole).

    Raises FileNotFoundError on a missing snapshot rather than guessing
    "SMD" - a missing file used to be swallowed here and silently treated as
    SMD, which is exactly backwards for this board: the screw terminals and
    headers ARE through-hole, and misclassifying one of them as SMD is what
    lets a Standard-assembly part slip onto an Economic-assembly order,
    which JLCPCB either rejects at upload or - worse - builds wrong.
    """
    if fpf not in _FP_ATTR_CACHE:
        path = os.path.join(os.path.dirname(__file__), "fp", fpf)
        with open(path) as fh:
            _FP_ATTR_CACHE[fpf] = "(attr through_hole)" in fh.read()
    return _FP_ATTR_CACHE[fpf]


def assembly_refs():
    """Refs that go to assembly, in design order.

    Excludes mounting holes (H-prefixed) and NOT_ASSEMBLED (board features
    with no manufactured part - test points, solder jumpers, the DNP
    AC-sense header).
    """
    return [ref for ref in COMPONENTS
            if not ref.startswith("H") and ref not in NOT_ASSEMBLED]


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
