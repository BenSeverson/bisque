"""Generate JLCPCB assembly files (BOM.csv + CPL.csv) from design.py.

LCSC part numbers: entries marked ok=True were verified against the LCSC
catalog; entries marked ok=False are well-known commodity candidates that
MUST be confirmed (or swapped via JLC's part search) in the order UI —
JLC's BOM matcher will offer in-stock equivalents for these generic parts.

CPL coordinates follow KiCad's footprint-position convention (Y negated).
JLCPCB's order preview auto-aligns the centroid file to the board outline;
verify rotations of U1/U3/U4/Q1/Q2/D1-D4/J1 in the preview (JLC's zero
angle sometimes differs from KiCad's) and nudge in their editor if needed.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import COMPONENTS

# ref -> (LCSC part, description, basic_part, verified)
LCSC = {
    "U1": ("C2913202", "ESP32-S3-WROOM-1-N16R8 (16MB flash, 8MB octal PSRAM)", False, True),
    "U2": ("C6186", "AMS1117-3.3 SOT-223", True, True),
    "U3": ("C52028", "MAX31855KASA+T SOIC-8", False, True),
    "U4": ("C7519", "USBLC6-2SC6 SOT-23-6", False, True),
    "Q1": ("C20917", "AO3400A SOT-23", True, True),
    "Q2": ("C20917", "AO3400A SOT-23", True, True),
    "D1": ("C8678", "SS34 SMA", True, True),
    "D2": ("C8678", "SS34 SMA", True, True),
    "D3": ("C2480", "SS14 SMA", True, True),
    "D4": ("C81598", "1N4148W SOD-123", True, True),
    "LED1": ("C2761795", "WS2812B 5050 RGB", False, False),
    "LED2": ("C2297", "green LED 0805", True, False),
    "LED3": ("C2296", "yellow LED 0805", True, False),
    "R1": ("C17414", "10k 0805", True, True),
    "R2": ("C17414", "10k 0805", True, True),
    "R3": ("C17630", "330R 0805", True, True),
    "R4": ("C27834", "5.1k 0805", True, True),
    "R5": ("C27834", "5.1k 0805", True, True),
    "R6": ("C17408", "100R 0805", True, True),
    "R7": ("C17414", "10k 0805", True, True),
    "R8": ("C17414", "10k 0805", True, True),
    "R9": ("C17513", "1k 0805", True, True),
    "R10": ("C17798", "680R 0805", True, False),
    "R11": ("C17408", "100R 0805", True, True),
    "C1": ("C12891", "22uF 25V X5R 1206", True, False),
    "C2": ("C49678", "100nF 50V X7R 0805", True, True),
    "C3": ("C12891", "22uF 25V X5R 1206", True, False),
    "C4": ("C49678", "100nF 0805", True, True),
    "C5": ("C28323", "1uF 0805", True, False),
    "C6": ("C49678", "100nF 0805", True, True),
    "C7": ("C15850", "10uF 0805", True, False),
    "C8": ("C49678", "100nF 0805", True, True),
    "C9": ("C57112", "10nF 0805", True, False),
    "C10": ("C49678", "100nF 0805", True, True),
    "C12": ("C15850", "10uF 0805", True, False),
    "BZ1": ("", "active buzzer 5V 12mm THT P7.6 - pick in JLC part search", False, False),
    "J1": ("C165948", "HRO TYPE-C-31-M-12 USB-C 16P", False, True),
    "J2": ("C8465", "5.08mm screw terminal 1x02 (KF301 type)", False, False),
    "J3": ("C8465", "5.08mm screw terminal 1x02", False, False),
    "J4": ("C8465", "5.08mm screw terminal 1x02", False, False),
    "J5": ("", "KK-254 friction-lock wafer 1x08 (Molex 22-27-2081 or A2547 clone)", False, False),
    "J6": ("", "KK-254 friction-lock wafer 1x06 (Molex 22-27-2061 or A2547 clone)", False, False),
    "J7": ("", "KK-254 friction-lock wafer 1x08", False, False),
    "SW1": ("", "6x6mm THT tactile switch - pick in JLC part search", False, False),
    "SW2": ("", "6x6mm THT tactile switch", False, False),
}


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    bom_path = os.path.join(outdir, "BOM.csv")
    cpl_path = os.path.join(outdir, "CPL.csv")
    # group identical parts
    groups = {}
    for ref, c in COMPONENTS.items():
        if ref.startswith("H"):
            continue
        part = LCSC.get(ref)
        key = (c["value"], c["fp"], part[0] if part else "")
        groups.setdefault(key, []).append(ref)
    with open(bom_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Notes"])
        for (value, fp, lcsc), refs in sorted(groups.items(), key=lambda kv: kv[1][0]):
            part = LCSC.get(refs[0])
            note = ""
            if part:
                note = part[1]
                if not part[3]:
                    note += " [CONFIRM part # at order time]"
                if not part[0]:
                    note = part[1]
            w.writerow([value, ",".join(refs), fp.split(":", 1)[1], lcsc, note])
    with open(cpl_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref, c in COMPONENTS.items():
            if ref.startswith("H"):
                continue
            x, y, rot = c["at"]
            w.writerow([ref, "%.3fmm" % x, "%.3fmm" % (-y), "Top", "%.1f" % rot])
    print("wrote %s, %s" % (bom_path, cpl_path))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "jlcpcb")
