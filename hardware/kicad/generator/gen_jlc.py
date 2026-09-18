"""Generate JLCPCB assembly files (BOM.csv + CPL.csv) from design.py.

Every LCSC part number below was verified live against the LCSC catalog
(package, value and stock) — see VERIFIED_ON. The most recent sweep re-checked
the library tier and the stock of all 39 lines and re-fitted every land pattern
(`lcsc_pads.py --refresh`, then `check_jlc_placement.py`); no `fee_free` flag
had drifted. Re-verify before a production run, since stock and part status
drift.

CPL coordinates follow KiCad's footprint-position convention (Y negated), plus
a per-part correction to both the angle and the origin: JLCPCB places LCSC's
footprint for the part, not ours, and the two libraries do not always agree on
where zero rotation points or where the origin sits. See JLC_PLACEMENT, which
check_jlc_placement.py derives from LCSC's own land patterns and verifies.

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
import re
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import COMPONENTS

VERIFIED_ON = "2026-09-09"

# JLCPCB does not place our footprint. It places LCSC's footprint for that
# part number, anchoring *its* origin at Mid X / Mid Y and turning *its* pin 1
# by Rotation. Two things therefore have to be corrected per part: the angle
# between LCSC's zero-rotation reference and KiCad's, and any offset between
# the two footprints' origins.
#
# Both are measured, not guessed: check_jlc_placement.py fits LCSC's real land
# pattern (generator/lcsc_pads.json, fetched from EasyEDA's component API —
# the library the JLCPCB assembly preview renders) onto the KiCad footprint
# this board uses, and `--derive` prints this table. Every entry below is that
# fit; re-run the checker after changing a part number or a footprint.
#
# This replaced a package-family regex table taken from the community list in
# bennymeg/Fabrication-Toolkit. That list is right about the families it was
# built from and wrong here in two ways that reached the assembly preview:
# `^SOT-23 -> 180` also matches SOT-23-**6**, whose LCSC land is drawn across
# the pins rather than along them (270, not 180), and `^QFN- -> 90` is 180 out
# for the ADE7953's LFCSP-28. A per-part fit cannot make that class of mistake.
#
# dx/dy are millimetres in the CPL's frame (x right, y up), applied after the
# part's own board rotation. They are zero for all but two parts: KiCad anchors
# the ESP32-S3 module and the USB-C receptacle at their body centres, LCSC
# anchors them on the pad pattern.
JLC_PLACEMENT = {
    "C12891":   (  0,  0.000,  0.000),   # C1    C_1206_3216Metric                    resid 0.118 (2 pin#)
    "C149504":  (  0,  0.000,  0.000),   # R47   R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C15127":   (180,  0.000,  0.000),   # Q4    SOT-23                               resid 0.283 (3 pin#)
    "C15850":   (  0,  0.000,  0.000),   # C7    C_0805_2012Metric                    resid 0.050 (2 pin#)
    "C160404":  (  0,  0.000,  0.000),   # J14   JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00m resid 0.000 (4 pin#)
    "C165948":  (  0,  0.000,  1.571),   # J1    USB_C_Receptacle_HRO_TYPE-C-31-M-12  resid 0.000 (8 pin#)
    "C1710":    (  0,  0.000,  0.000),   # C16   C_0805_2012Metric                    resid 0.050 (2 pin#)
    "C1739":    (  0,  0.000,  0.000),   # C31   C_0805_2012Metric                    resid 0.050 (2 pin#)
    "C17408":   (  0,  0.000,  0.000),   # R14   R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C17414":   (  0,  0.000,  0.000),   # R1    R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C17513":   (  0,  0.000,  0.000),   # R9    R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C17630":   (  0,  0.000,  0.000),   # R3    R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C17634":   (  0,  0.000,  0.000),   # R39   R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C17673":   (  0,  0.000,  0.000),   # R44   R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C17724":   (  0,  0.000,  0.000),   # R31   R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C1779":    (  0,  0.000,  0.000),   # C27   C_0805_2012Metric                    resid 0.050 (2 pin#)
    "C17798":   (  0,  0.000,  0.000),   # R10   R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C20917":   (180,  0.000,  0.000),   # Q5    SOT-23                               resid 0.083 (3 pin#)
    "C2296":    (  0,  0.000,  0.000),   # LED3  LED_0805_2012Metric                  resid 0.113 (2 pin#)
    "C2297":    (  0,  0.000,  0.000),   # LED2  LED_0805_2012Metric                  resid 0.113 (2 pin#)
    "C2838127": (  0,  0.000,  0.000),   # Y1    Oscillator_SMD_Abracon_ASE-4Pin_3.2x resid 0.071 (4 pin#)
    "C2653162": (270,  0.000,  0.000),   # U3    TSSOP-14_4.4x5mm_P0.65mm             resid 0.062 (14 pin#)
    "C27834":   (  0,  0.000,  0.000),   # R4    R_0805_2012Metric                    resid 0.088 (2 pin#)
    "C28323":   (  0,  0.000,  0.000),   # C5    C_0805_2012Metric                    resid 0.050 (2 pin#)
    "C3013945": (  0,  0.000, -0.477),   # U1    ESP32-S3-WROOM-1U                    resid 0.022 (40 pin#)
    "C318884":  (  0,  0.000,  0.000),   # SW1   SW_Push_1P1T_XKB_TS-1187A            resid 0.025 (4 shape)
    "C49678":   (  0,  0.000,  0.000),   # C2    C_0805_2012Metric                    resid 0.050 (2 pin#)
    "C123302":  (180,  0.000,  0.000),   # U10   SSOP-8_2.95x2.8mm_P0.65mm            fitted by check_jlc_placement
    "C515890":  (270,  0.000,  0.000),   # U7    QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm  resid 0.075 (29 pin#)
    "C48937499": (270, -0.287, -0.000),  # U2    SOT-223-3_TabPin2                    resid 0.000 (2 pin#)
    "C7420376": (270,  0.000,  0.000),   # U4    SOT-23-6                             resid 0.062 (6 pin#)
    "C7512":    (270,  0.000,  0.000),   # U6    SOIC-16_3.9x9.9mm_P1.27mm            resid 0.261 (16 pin#)
    "C81598":   (  0,  0.000,  0.000),   # D4    D_SOD-123                            resid 0.085 (2 pin#)
    "C13585":   (  0,  0.000,  0.000),   # C41   C_1206_3216Metric                    resid 0.118 (2 pin#)
    "C369169":  (  0,  0.000,  0.000),   # F1    Fuse_1812_4532Metric                 resid 0.284 (2 pin#)
    "C475527":  (  0,  0.000,  0.000),   # L1    L_Changjiang_FXL0650                 resid 0.025 (2 pin#)
    "C61063":   (270,  0.000,  0.000),   # U11   SOIC-8_3.9x4.9mm_P1.27mm             resid 0.230 (8 pin#)
    "C19077547": (  0,  0.000,  0.000),   # D8    D_SMA                                resid 0.404 (2 pin#)
    "C8678":    (  0,  0.000,  0.000),   # D1    D_SMA                                resid 0.200 (2 pin#)
}


def jlc_placement(lcsc, kicad_rot):
    """KiCad angle -> (CPL angle, CPL dx, CPL dy, correction applied).

    dx/dy are already turned into board coordinates, so a caller adds them
    straight to Mid X / Mid Y.

    A part with no LCSC number is not being assembled, so there is nothing to
    correct against; anything else must be in the table, since silently
    shipping an uncorrected placement is how the SOT-23-6s went out 90 degrees
    off in the first place.
    """
    if not lcsc:
        return kicad_rot % 360, 0.0, 0.0, (0, 0.0, 0.0)
    if lcsc not in JLC_PLACEMENT:
        sys.exit("gen_jlc: %s has no JLC_PLACEMENT entry. Add the part to "
                 "lcsc_pads.json (generator/lcsc_pads.py --refresh) and paste "
                 "the row from check_jlc_placement.py --derive." % lcsc)
    rot, dx, dy = JLC_PLACEMENT[lcsc]
    a = math.radians(kicad_rot)
    c, s = math.cos(a), math.sin(a)
    return ((kicad_rot + rot) % 360, dx * c - dy * s, dx * s + dy * c,
            (rot, dx, dy))


# ref -> (LCSC part, description, fee_free, verified)
#
# fee_free is what it says and NOT "is a Basic part", which is what this field
# held until the feeder bill was actually checked against JLCPCB's API. Two
# libraries carry no feeder loading fee on Economic PCBA: Basic (351 parts)
# and Preferred Extended (1235), the latter being parts JLCPCB keeps mounted
# but has moved out of Basic. Reading the flag as "Basic" made C107114 (30 pF)
# and C7420333 (BAT54S) count against the bill they are exempt from, and the
# total below printed $33 for a board that owes $27.
#
# The distinction is only visible in the API, not on the part page's category
# line, so it is recorded here per part rather than derived:
#     componentLibraryType == "base" or preferredComponentFlag
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
    "C25": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
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
    "C38": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "C39": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C40": ("C1739", "0805B333K500NT 33nF 50V X7R 0805", True, True),
    "C41": ("C13585", "CL31A106KBHNNNE 10uF 50V X5R 1206", True, True),
    "C42": ("C13585", "CL31A106KBHNNNE 10uF 50V X5R 1206", True, True),
    "C43": ("C49678", "CC0805KRX7R9BB104 100nF 50V X7R 0805", True, True),
    "C44": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "C45": ("C12891", "CL31A226KAHNNNE 22uF 25V X5R 1206", True, True),
    "D1": ("C8678", "SS34 SMA", True, True),
    "D2": ("C8678", "SS34 SMA", True, True),
    "D3": ("C81598", "1N4148W SOD-123 - VLED drop diode, silicon on purpose", True, True),
    "D4": ("C81598", "1N4148W SOD-123", True, True),
    "D5": ("C7420376", "SRV05-4 TVS array SOT-23-6", True, True),
    "D6": ("C7420376", "SRV05-4 TVS array SOT-23-6", True, True),
    "D7": ("C8678", "SS34 40V 3A Schottky SMA - U11 catch diode", True, True),
    # The one SMAJ30A of 44 listings that LCSC files as Preferred rather
    # than Extended, which is the whole reason for it (#348) - same MPN,
    # same DO-214AC land pattern, same 30V/400W part, $3 less per order.
    # Pure listing arbitrage, so it is also the cheapest line here to
    # revert: nothing but this string and its JLC_PLACEMENT row moves.
    # Stock is the catch - 651 units against C908776's 197k, thinner
    # than anything else on the BOM. Fine for prototypes, re-check
    # before a production run, and fall back to C908776 if it is gone.
    "D8": ("C19077547", "SMAJ30A 30V 400W unidirectional TVS SMA", True, True),
    "F1": ("C369169", "JK-mSMD075-33 PPTC 750mA hold / 1.5A trip, 33V, 1812", False, True),
    "L1": ("C475527", "FXL0650-470-M 47uH 2A 2.6A-sat 230mohm 7x6.6mm", False, True),
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
    # Watchdog high-side switch: the one P-channel part on the board.
    "Q4": ("C15127", "AO3401A P-channel SOT-23", True, True),
    "Q5": ("C20917", "AO3400A SOT-23", True, True),
    "Q6": ("C20917", "AO3400A SOT-23", True, True),
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
    "R14": ("C17408", "100R 0805 1%", True, True),
    "R15": ("C17408", "100R 0805 1%", True, True),
    "R16": ("C17408", "100R 0805 1%", True, True),
    "R17": ("C17408", "100R 0805 1%", True, True),
    "R19": ("C17408", "100R 0805 1%", True, True),
    "R20": ("C17414", "10k 0805 1%", True, True),
    "R21": ("C17798", "680R 0805 1%", True, True),
    "R23": ("C17414", "10k 0805 1%", True, True),
    "R24": ("C17414", "10k 0805 1%", True, True),
    "R25": ("C17414", "10k 0805 1%", True, True),
    "R26": ("C17513", "1k 0805 1%", True, True),
    "R27": ("C17414", "10k 0805 1%", True, True),
    "R28": ("C17513", "1k 0805 1%", True, True),
    "R29": ("C17414", "10k 0805 1%", True, True),
    "R30": ("C17414", "10k 0805 1%", True, True),
    "R31": ("C17724", "0805W8F510KT5E 5.1R 0805 1%", True, True),
    "R32": ("C17513", "1k 0805 1%", True, True),
    "R33": ("C17513", "1k 0805 1%", True, True),
    "R34": ("C17724", "0805W8F510KT5E 5.1R 0805 1%", True, True),
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
    "R46": ("C149504", "100k 0805 1%", True, True),
    "R47": ("C149504", "100k 0805 1%", True, True),
    "R48": ("C149504", "100k 0805 1%", True, True),
    "R49": ("C149504", "100k 0805 1%", True, True),
    "R50": ("C17414", "10k 0805 1%", True, True),
    "R51": ("C17414", "10k 0805 1%", True, True),
    "R52": ("C17414", "10k 0805 1%", True, True),
    "R53": ("C17414", "10k 0805 1%", True, True),
    "R54": ("C17634", "33R 0805 1%", True, True),
    "R55": ("C17634", "33R 0805 1%", True, True),
    "R56": ("C17634", "33R 0805 1%", True, True),
    "R57": ("C17634", "33R 0805 1%", True, True),
    "R58": ("C17634", "33R 0805 1%", True, True),
    "R59": ("C17513", "1k 0805 1%", True, True),
    "R60": ("C17513", "1k 0805 1%", True, True),
    "R61": ("C17513", "1k 0805 1%", True, True),
    "SW1": ("C318884", "TS-1187A-B-A-B 5.1x5.1mm SMD tactile switch", True, True),
    "SW2": ("C318884", "TS-1187A-B-A-B 5.1x5.1mm SMD tactile switch", True, True),
    "U1": ("C3013945", "ESP32-S3-WROOM-1U-N16R2 (16MB flash, 2MB quad PSRAM, U.FL)", False, True),
    "U2": ("C48937499", "TLV1117LV33DCYR SOT-223 LDO (700mV max dropout)", False, True),
    "U3": ("C2653162", "MAX31856MUD+T TSSOP-14", False, True),
    "U4": ("C7420376", "SRV05-4 TVS array SOT-23-6", True, True),
    "U5": ("C2653162", "MAX31856MUD+T TSSOP-14", False, True),
    "U6": ("C7512", "ULN2003ADR SOIC-16 Darlington array", True, True),
    "U7": ("C515890", "ADE7953ACPZ-RL LFCSP-28 energy metering", False, True),
    "U10": ("C123302", "SN74LVC1G123DCTR retriggerable monostable SSOP-8", False, True),
    "U11": ("C61063", "XL1509-5.0E1 4.5-40Vin 5V fixed 2A 150kHz buck SOIC-8", True, True),
    "Y1": ("C2838127", "TFOM3.579545M4RHKCNT2T 3.579545MHz XO SMD3225-4P", False, True),
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
# place or buy. SJ1/SJ2: open solder-jumper footprints (AUX_VP<-+5V link and
# the WDT bring-up defeat) - populated with solder, not a component. SJ3/SJ4
# went with the optocouplers (see design.py's SSR block). J13: a
# fitted-but-DNP 2-pin header for a future SELV AC-sense accessory (Task 10)
# - "NO MAINS ON THIS BOARD" per design.py, so this build does not stuff it.
# FID1-3: optical alignment targets, bare copper on no net. They must be
# listed HERE and not left to the H-prefix rule assembly_refs() uses for the
# mounting holes - a designator that is neither H-prefixed nor in this set
# reaches the BOM as a blank-LCSC row, i.e. a part to "buy" that is not a
# part, and JLCPCB's PCBA upload rejects the pair.
NOT_ASSEMBLED = {
    "TP1", "TP2", "TP3", "TP4", "TP5", "TP6",
    "TP7", "TP8", "TP9", "TP10", "TP11", "TP12",
    "SJ1", "SJ2",
    "J13",
    "FID1", "FID2", "FID3",
}

# Parts that ARE parts, and are deliberately not fitted. Distinct from
# NOT_ASSEMBLED above, and the distinction is the whole point: the eighteen
# refs up there are mostly not parts at all. A test point is a bare pad, a
# solder jumper is copper, a fiducial is bare copper - there is nothing to
# populate, so calling them "do not populate" asserts something false.
#
# J13 is the real case. It is a 2-pin header that could be fitted and is not:
# the board ships with the ADE7953's voltage channel unconnected (which is why
# R60/R61 exist, to stop VP/VN floating), and fitting J13 is how someone opts
# into mains voltage sensing later.
#
# Consumed on BOTH sides - gen_sch.py writes `(dnp yes)` and kicad_build.py
# sets the footprint attribute - so the schematic and the board agree by
# construction and `--schematic-parity` has nothing to disagree about.
#
# What this buys, measured rather than assumed: KiCad greys the symbol and
# draws a red X through it in the exported schematic. Before it, the only
# thing in the schematic saying J13 is unfitted was its value string,
# `AC_SENSE_DNP` - and the schematic PDF is what someone opens when they are
# deciding whether to wire the voltage channel. The netlist is unaffected:
# setting it adds one property and leaves the component and both its pins in
# their nets, so check_netlist.py sees no change.
DNP = {"J13"}

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
# Four of these six are Chinese generics on LCSC and the Mouser column is
# the *genuine* part the KiCad footprint was drawn from — so it fits at least
# as well, clone dimensional tolerance being the usual source of trouble. It
# also costs several times more: a real Phoenix MKDS is dollars against cents
# for the WJ500V clone, taking this list from ~$1.50/board to roughly
# $8–12/board.
#
# Every MPN here is the part the footprint's own `descr` names, so the fit is
# a documented fact rather than a judgement — the KK-254 footprints carry
# "old/engineering part number: AE-6410-NNA example for new part number:
# 22-27-2NN1" and the terminal blocks are named MKDS-1,5-N-5.08. Look the
# footprint up before adding a row; do not pattern-match the digits.
#
# Confirmed 2026-09-09 against Mouser's live catalog, one search per MPN, so
# these are lines Mouser actually carries and not merely parts it lists. There
# is still no Mouser API key (and Mouser blocks scripted fetches, so this took
# a real browser) — re-confirm stock and price at order time.
MOUSER_ALT = {
    "C240822": ("22-27-2081", "Molex",
                "identical part - the LCSC line is already genuine Molex"),
    "C239381": ("22-27-2061", "Molex",
                "genuine KK-254 1x06; LCSC line is an A2547WV clone"),
    "C17701004": ("22-27-2141", "Molex",
                  "genuine KK-254 1x14 (AE-6410-14A); LCSC line is an "
                  "XD-2510-14A clone"),
    "C8465": ("1715721", "Phoenix Contact",
              "MKDS 1,5/2-5,08 - the part this footprint is named for"),
    "C42377749": ("1715747", "Phoenix Contact",
                  "MKDS 1,5/4-5,08 - the part this footprint is named for"),
    "C96093": ("CMI-1295-0585T", "Same Sky",
               "12x9.5mm body, 7.6mm pitch, 5V THT active - datasheet-verified"),
    # Mouser hosts WS2812B datasheets and sells third-party modules built on
    # it, but no bare Worldsemi 5050 could be found in their catalog.
    "C2761795": ("", "",
                 "NOT AT MOUSER - source from LCSC, DigiKey, Adafruit or SparkFun"),
}

# Cable-side parts: the female crimp housings and terminals that mate with the
# board's male pin headers. Nothing here is fitted TO the board - these are
# what you crimp onto the loom at the far end - but they belong on the same
# shopping list, because a board with no mating connectors is a board you
# cannot wire up, and an order placed one line short is discovered a week
# later. They are written with Kind="mating" so a reader (and a filter) can
# tell them from the parts that get soldered down.
#
# Only the KK-254 wafers need them. The screw terminals (J2-J4, J8-J12) clamp
# bare wire, J13 is a DNP header (NOT_ASSEMBLED), and J14 is a JST SH Qwiic
# socket wired with a ready-made cable rather than a crimped one.
#
# The chain of fact, because this file's own rule is not to pattern-match the
# digits - the KK family has four different 14-circuit vertical friction-lock
# headers, and the housing numbering is not the header numbering:
#
#   1. the footprints name the headers 22-27-2141 / -2061 / -2081 in their
#      `descr` (that is where MOUSER_ALT's rows come from), Molex series 6410;
#   2. Molex's part page for 22272141 says, under "Mates With / Use With":
#      "KK 254 Single Row Crimp Housings - 2695";
#   3. series 2695 is 22-01-3NN7 (engineering number 2695-NNRP), and each of
#      those pages lists series 6410 back among the headers it mates and
#      series 2759 among the "KK 254 Female Crimp Terminals" it takes;
#   4. series 2759's chart carries exactly one tin part, 08-50-0113, plus the
#      gold 08-55-0101/0102/0131 - all of them 30-22 AWG.
#
# The terminal row is the one judgement call, and it is between three real
# parts rather than a guess:
#
#   * 08-50-0114 - tin, MOQ 1 at Mouser (54 k in stock, $0.16/1). Molex marks
#     it OBSOLETE, so that stock is finite. Chosen anyway, because the headers
#     are matte tin and this is the only tin terminal you can buy one of.
#   * 08-50-0113 - the active tin successor, but Mouser sells it only by the
#     10 k reel. DigiKey has it as cut tape if you want the current part.
#   * 08-55-0102 - active, bagged loose pieces, MOQ 1, same $0.16 - but gold
#     mating plating onto a tin pin. Fine at 4 A and 25 mating cycles; not
#     what you would specify for a box that lives warm.
#
# Confirmed 2026-09-10 on Molex's own part pages, whose distributor-inventory
# table (OEMSecrets) carries live Mouser stock, MOQ and price and is not
# behind Mouser's bot wall - the cheap check MOUSER_ALT's comment recommends.
# Re-confirm at order time, and buy spare terminals: the count below is exact
# and a miscrimp costs one.
KK254_HOUSING = {
    # board ref -> (Mouser MPN, Molex engineering number)
    "J5": ("22-01-3147", "2695-14RP"),
    "J6": ("22-01-3067", "2695-06RP"),
    "J7": ("22-01-3087", "2695-08RP"),
}

KK254_TERMINAL = (
    "08-50-0114", "Molex",
    "KK 254 female crimp terminal, 30-22 AWG, tin (series 2759)",
    "one per circuit across %s; Molex-obsolete but the only tin terminal "
    "Mouser sells at MOQ 1 - the active successor 08-50-0113 is reel-only "
    "there, and 08-55-0102 is active/bagged/MOQ 1 but gold onto a tin pin",
)

# Footprint substring identifying a KK-254 wafer, so a fourth one added to the
# board without a KK254_HOUSING row fails the build instead of shipping a
# shopping list you cannot make a loom from.
KK254_FP_MARK = "Molex_KK-254_"

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


def ref_key(ref):
    """Sort key that orders J2 before J10 rather than after it."""
    m = re.match(r"^([A-Za-z]+)(\d*)", ref)
    return (m.group(1), int(m.group(2) or 0), ref)


def group_by_part(refs):
    """refs -> {(value, footprint, lcsc): [ref, ...]}"""
    groups = {}
    for ref in refs:
        c = COMPONENTS[ref]
        part = LCSC.get(ref)
        key = (c["value"], c["fp"], part[0] if part else "")
        groups.setdefault(key, []).append(ref)
    return groups


def group_by_orderable(refs):
    """[(values, footprint, lcsc, [ref, ...])] - ONE entry per orderable part.

    group_by_part() keys on the schematic value as well, which is right for
    BOM.csv (JLCPCB's Comment column is per line) and wrong for a shopping
    list: J2/J3/J4/J8/J9 are five identical WJ500V-5.08-2P blocks that happen
    to be called 24V_IN, TC1_K, SSR1, TC2_K and SSR2, and you buy five of one
    part, not one each of five. Keying on (footprint, LCSC) collapses them.

    The values are not thrown away - they are joined in designator order, so
    the row still says which connector is which without splitting the line.
    """
    groups = {}
    for ref in refs:
        c = COMPONENTS[ref]
        part = LCSC.get(ref)
        groups.setdefault((c["fp"], part[0] if part else ""), []).append(ref)
    out = []
    for (fp, lcsc), grefs in groups.items():
        grefs.sort(key=ref_key)
        out.append((" / ".join(COMPONENTS[r]["value"] for r in grefs),
                    fp, lcsc, grefs))
    return sorted(out, key=lambda e: ref_key(e[3][0]))


def mating_rows(hand_refs):
    """[(designators, comment, qty, description, mpn, mfr, note)] - the
    cable-side parts the hand-fitted headers need.

    Derived from the board rather than typed out: the circuit counts come from
    each connector's own pin map, so the terminal quantity cannot drift when a
    header changes width. See KK254_HOUSING for where the part numbers come
    from.
    """
    kk = sorted((r for r in hand_refs if KK254_FP_MARK in COMPONENTS[r]["fp"]),
                key=ref_key)
    missing = [r for r in kk if r not in KK254_HOUSING]
    if missing:
        raise SystemExit(
            "KK-254 header(s) with no mating housing in KK254_HOUSING: %s - "
            "add the Molex 2695 part for that circuit count; the table's "
            "comment says how to look one up" % ", ".join(missing))

    rows = []
    for ref in kk:
        mpn, eng = KK254_HOUSING[ref]
        n = len(COMPONENTS[ref]["pins"])
        header = MOUSER_ALT[LCSC[ref][0]][0]
        rows.append((ref, "%s mate" % COMPONENTS[ref]["value"], 1,
                     "KK 254 crimp housing, %d ckt, friction ramp with "
                     "polarizing ribs (%s)" % (n, eng),
                     mpn, "Molex",
                     "mates %s, the %s header on the board" % (ref, header)))
    if kk:
        refs = ",".join(kk)
        mpn, mfr, desc, note = KK254_TERMINAL
        rows.append((refs, "loom terminals",
                     sum(len(COMPONENTS[r]["pins"]) for r in kk),
                     desc, mpn, mfr, note % refs))
    return rows


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
            jrot, dx, dy, applied = jlc_placement((LCSC.get(ref) or ("",))[0], rot)
            if any(applied):
                corrections.append((ref, fp_name, rot, jrot, applied[0], dx, dy))
            # Mid X / Mid Y is where LCSC's footprint origin goes, which is
            # not always where ours sits - see JLC_PLACEMENT.
            w.writerow([ref, "%.3fmm" % (x + dx), "%.3fmm" % (-y + dy),
                        "Top", "%.1f" % jrot])

    # Shopping list for the parts JLCPCB is *not* fitting. Same LCSC part
    # numbers, so it can be pasted straight into an LCSC cart alongside the
    # PCBA order — but nothing here is bound to LCSC's catalogue any more,
    # which matters for the KK-254 wafers (the lowest-stock lines on the BOM).
    #
    # One row per orderable part, not per designator: see group_by_orderable().
    # Kind separates the parts that get soldered to the board ("board") from
    # the housings and terminals that go on the other end of the loom
    # ("mating"), which are not on the board at all and therefore have no
    # designator, footprint or LCSC line of their own.
    no_alt = []
    mates = mating_rows(hand_refs)
    with open(hand_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Kind", "Designator", "Comment", "Footprint",
                    "LCSC Part #", "Qty per board", "Description",
                    "Mouser MPN", "Mouser Manufacturer", "Notes"])
        for value, fp, lcsc, grefs in group_by_orderable(hand_refs):
            part = LCSC.get(grefs[0])
            mpn, mfr, note = MOUSER_ALT.get(lcsc, ("", "", ""))
            if not mpn:
                no_alt.append("%s (%s)" % (",".join(grefs), lcsc))
            w.writerow(["board", ",".join(grefs), value, fp.split(":", 1)[1],
                        lcsc, len(grefs), part[1] if part else "",
                        mpn, mfr, note])
        for mrefs, comment, qty, desc, mpn, mfr, note in mates:
            w.writerow(["mating", mrefs, comment, "", "", qty, desc,
                        mpn, mfr, note])

    ext = {LCSC[r][0] for r in refs if r in LCSC and not LCSC[r][2]}
    print("wrote %s, %s, %s" % (bom_path, cpl_path, hand_path))
    print("%d parts to JLCPCB (%d BOM lines), %d hand-soldered on "
          "%d line(s), LCSC verified %s"
          % (len(refs), len(groups), len(hand_refs),
             len(group_by_orderable(hand_refs)), VERIFIED_ON))
    print("%d unique Extended part(s) -> $%d in feeder fees: %s"
          % (len(ext), 3 * len(ext), ", ".join(sorted(ext))))
    print("hand-soldered: %s" % ", ".join(sorted(hand_refs, key=ref_key)))
    print("mating connectors (cable side, %d line(s)): %s"
          % (len(mates), ", ".join("%s x%d" % (r[4], r[2]) for r in mates)))
    if no_alt:
        print("  no Mouser second source for: %s" % ", ".join(no_alt))
    if corrections:
        print("JLCPCB placement corrections applied (%d):" % len(corrections))
        for ref, fp_name, rot, jrot, crot, dx, dy in corrections:
            # dx/dy as written to the CPL, i.e. already turned by the part's
            # own board angle - not the table's unrotated pair.
            shift = "" if not (dx or dy) else "  origin %+.3f,%+.3f mm" % (dx, dy)
            print("  %-5s %-35s %3.0f -> %3.0f (+%d)%s"
                  % (ref, fp_name[:35], rot, jrot, crot, shift))
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
