#!/usr/bin/env python3
"""Regenerate datasheets/manifest.json from the design and the PDFs on disk.

The manifest used to be written only by the distributor sync scripts, and it
rotted exactly the way a hand-maintained index does: by 2026-08-17 it claimed
all 26 parts had FAILED to download while 13 PDFs sat in the directory beside
it, and it still listed `USBLC6-2SC6` for U4, `MAX31855KASA+` for U3 and
`ESP32-S3-WROOM-1-N16R8` for U1 - three parts this board no longer fits. An
index that is wrong in both directions at once is worse than no index, because
a reader trusts it.

So it is derived instead. Two inputs, both authoritative:

  * `design.COMPONENTS` - what the board actually fits, keyed by value, which
    is what makes a retired part impossible to leave behind: nothing maps to it.
  * the `.pdf` files actually present in datasheets/ - checked by listing the
    directory, never by trusting a previous manifest.

DOC_FOR below is the one hand-maintained thing, and it has to be: a datasheet's
filename is freeform and no rule connects `ADE7953_Analog_Devices.pdf` to the
value `ADE7953ACPZ`. Everything else - references, status, orphans, gaps - is
computed. A PDF that maps to no value in the design is reported as an orphan
rather than silently kept, and a fitted part with no PDF is reported as a gap.

Run with --check to verify without writing; `make pcb-check` does.

NOT a CI gate, and that is not an oversight: `datasheets/*` is gitignored (only
REV-B-NOTES.md is tracked), so the cache does not exist in a fresh clone and a
CI job asserting anything about it would fail every run. Being invisible to git
is also precisely why the old manifest rotted - nothing ever showed up in a
diff to contradict it - so the guard has to be a generator a human can re-run,
not a reviewer. Where there is no cache at all this exits 0 and says so.

Deliberately NOT a downloader. It records what is on disk; fetching a missing
datasheet is the distributor skills' job and a network operation, and mixing
the two is how the old manifest came to assert a download status it had never
re-tested.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import COMPONENTS
from gen_jlc import LCSC

HERE = os.path.dirname(os.path.abspath(__file__))
DS_DIR = os.path.join(HERE, "..", "datasheets")
SCHEMATIC = "bisque-controller.kicad_sch"

# datasheet filename -> the design.COMPONENTS *value* it documents.
#
# None means the file documents no single BOM line: supporting material kept on
# purpose (the SoC manual behind the module) rather than an orphan.
DOC_FOR = {
    "ADE7953_Analog_Devices.pdf": "ADE7953ACPZ",
    "TLV1117LV_TI.pdf": "TLV1117LV33",
    "AO3400A_30V_Vds_5.7A_Id_N-Channel_MOSFET_SOT-23.pdf": "AO3400A",
    "AO3401A_-4.0A_Id_-30V_Vds_P-Channel_MOSFET_SOT-23.pdf": "AO3401A",
    "SN74LVC1G123_TI.pdf": "SN74LVC1G123",
    "MAX31856.pdf": "MAX31856MUD+",
    "TFOM_3.579545M_XO_C2838127.pdf": "3.579545MHz XO",
    "ULN2003A.pdf": "ULN2003A",
    "WS2812B_RGB_LED_with_integrated_controller.pdf": "WS2812B",
    # The module's own datasheet is the WROOM-1 sheet; Espressif documents the
    # -1 and -1U together and the pinout is identical (check_pinmap.py's
    # MODULE_PIN_GPIO is built from it). Kept against the fitted -1U value.
    "ESP32-S3-WROOM-1-N16R8_RF_Module_ESP32-S3_SoC_Wi-Fi_802.11b_g_n_Bluetooth_BLE_32-bit_3.3V.pdf":
        "ESP32-S3-WROOM-1U-N16R2",
    # Supporting material, not a BOM line.
    "ESP32-S3_Series_Datasheet_v2.2.pdf": None,
}

# Datasheets for parts this board USED to fit. Kept rather than deleted - they
# are the evidence behind two design reversals and are cited by
# FAB-READINESS-REVIEW-REVB.md - but recorded as retired so nobody reads the
# presence of a USBLC6 PDF as a claim that U4 is a USBLC6. Listing one here is
# the deliberate alternative to deleting the file; anything in datasheets/ that
# is in neither DOC_FOR nor here is reported as an orphan.
RETIRED = {
    "LTV-817_LiteOn_Photocoupler_M_S_S-TA_S-TA1_S-TP_RevC.pdf":
        "U8/U9, removed in the opto-isolation reversal",
    "USBLC6-2SC6_ST.pdf":
        "U4 before it became an SRV05-4",
}

# Values that are real parts but for which no datasheet is expected: generic
# passives ordered by value and tolerance, and the "values" that are really
# connector/feature labels rather than part numbers.
NO_DATASHEET_EXPECTED = {
    "100R", "100R 1%", "100k", "100nF", "10k", "10nF", "10uF", "1M", "1k",
    "1uF", "22uF/25V", "33", "330R", "33nF", "4.7k", "4.7uF", "5.1k", "5R1",
    "680R",
    # labels on connectors, jumpers, test points and mechanical parts
    "5V_IN", "AC_SENSE_DNP", "AUX", "AUX_VP=5V", "BOOT", "CT", "DISPLAY",
    "FIDUCIAL", "INPUTS", "M3", "NAV_SW", "QWIIC", "RESET", "SSR1", "SSR2",
    "TC1_K", "TC2_K", "TP", "USB-C", "WDT_DEFEAT", "amber", "green",
    "active 5V",
}


def refs_for_value(value):
    return sorted(r for r, c in COMPONENTS.items() if c["value"] == value)


def lcsc_for_refs(refs):
    for r in refs:
        if r in LCSC:
            return LCSC[r][0]
    return ""


def build():
    """Return (manifest dict, orphan files, missing values)."""
    present = sorted(f for f in os.listdir(DS_DIR) if f.lower().endswith(".pdf"))
    by_value = {}
    orphans = []
    for fname in present:
        if fname in RETIRED:
            continue
        if fname not in DOC_FOR:
            orphans.append((fname, "in neither DOC_FOR nor RETIRED - map it, "
                                   "mark it retired, or delete the file"))
            continue
        value = DOC_FOR[fname]
        if value is None:
            continue                                  # supporting material
        if not refs_for_value(value):
            orphans.append((fname, "documents %r, which no component fits" % value))
            continue
        by_value.setdefault(value, []).append(fname)

    design_values = {c["value"] for c in COMPONENTS.values()}
    want = sorted(v for v in design_values if v not in NO_DATASHEET_EXPECTED)

    parts, missing = {}, []
    for value in want:
        refs = refs_for_value(value)
        entry = {
            "value": value,
            "references": refs,
            "lcsc": lcsc_for_refs(refs),
        }
        files = by_value.get(value)
        if files:
            f = files[0]
            entry.update({
                "file": f,
                "status": "ok",
                "source": "on-disk",
                "size_bytes": os.path.getsize(os.path.join(DS_DIR, f)),
            })
            if len(files) > 1:
                entry["additional_files"] = files[1:]
        else:
            entry.update({
                "status": "missing",
                "error": "no datasheet in datasheets/ - fetch with the digikey / "
                         "lcsc / element14 / mouser skill",
            })
            missing.append(value)
        parts[value] = entry

    extra = {
        f: {"file": f, "status": "reference", "value": None,
            "references": [], "lcsc": "",
            "note": "supporting material, not a BOM line",
            "size_bytes": os.path.getsize(os.path.join(DS_DIR, f))}
        for f, v in DOC_FOR.items() if v is None and f in present
    }

    manifest = {
        "schematic": SCHEMATIC,
        "generated_by": "generator/gen_datasheet_manifest.py",
        "last_sync": datetime.datetime.now(datetime.timezone.utc)
                             .isoformat(timespec="seconds"),
        "coverage": {
            "expected": len(want),
            "present": len(want) - len(missing),
            "missing": len(missing),
        },
        "parts": parts,
        "reference_material": extra,
        "retired_material": {
            f: {"file": f, "status": "retired", "note": why,
                "size_bytes": os.path.getsize(os.path.join(DS_DIR, f))}
            for f, why in sorted(RETIRED.items()) if f in present
        },
    }
    return manifest, orphans, missing


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify without writing; non-zero if stale or orphaned")
    args = ap.parse_args(argv[1:])

    # The cache is gitignored, so "not there" is the normal state of a fresh
    # clone and must not read as a failure.
    if not os.path.isdir(DS_DIR) or not any(
            f.lower().endswith(".pdf") for f in os.listdir(DS_DIR)):
        print("gen_datasheet_manifest: no datasheets/ cache present - nothing "
              "to index (sync with the digikey / lcsc / element14 skill)")
        return 0

    manifest, orphans, missing = build()
    path = os.path.join(DS_DIR, "manifest.json")
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"

    for f, why in orphans:
        print("FAIL: orphan datasheet %s - %s" % (f, why))

    if args.check:
        try:
            on_disk = json.load(open(path))
        except (OSError, ValueError):
            print("FAIL: datasheets/manifest.json missing or unparseable")
            return 1
        # last_sync is a timestamp; compare everything else.
        a = {k: v for k, v in on_disk.items() if k != "last_sync"}
        b = {k: v for k, v in manifest.items() if k != "last_sync"}
        if a != b:
            print("FAIL: datasheets/manifest.json is stale - run "
                  "python3 generator/gen_datasheet_manifest.py")
            return 1
        if orphans:
            return 1
        print("gen_datasheet_manifest: manifest current - %d/%d datasheets present, "
              "%d missing" % (manifest["coverage"]["present"],
                              manifest["coverage"]["expected"], len(missing)))
        return 0

    with open(path, "w") as fh:
        fh.write(text)
    print("wrote datasheets/manifest.json - %d/%d present, %d missing"
          % (manifest["coverage"]["present"], manifest["coverage"]["expected"],
             len(missing)))
    for v in missing:
        print("   missing: %-26s %s" % (v, ", ".join(refs_for_value(v))))
    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
