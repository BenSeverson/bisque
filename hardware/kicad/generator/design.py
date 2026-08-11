"""Bisque kiln controller PCB — single source of truth.

Components, pin->net connectivity, and PCB placement. Both the schematic and
board generators derive everything from these tables, so the two files can
never disagree on connectivity.

Pin GPIO mapping mirrors main/Kconfig.projbuild defaults (the firmware's
source of truth):
  SPI: MOSI=11 MISO=13 SCLK=12 | TC CS=10 | SSR=17
  LCD: CS=8 DC=9 RST=46 BL=3   | WS2812=48 | ALARM=7
  BTN: UP=4 DOWN=5 SEL=1 LEFT=6 RIGHT=2
  J7:  VENT=14 AUX_A=15 AUX_B=16 | TXD0/RXD0 console
  J11: IN1(lid)=4 IN2(gas flow)=2 IN3(spare)=1

J7's four signal nets are real copper here. VENT defaults to that GPIO in
Kconfig to match this board; AUX_A/AUX_B are declared but not yet driven by
any code. IN1/IN2/IN3 (Task 9) land on their own terminal, J11, not J7 -
rev A's lid switch was the only occupant of J7.6 and has moved there. Note
that an enabled-but-unwired IN1 (lid) reads open and holds the SSR off - it
needs a switch, a jumper to GND, or -1. The full as-built map, the
constraints behind it, and the planned expansion live in
docs/pin-assignments.md — keep that table in sync with this one.
"""

# --- board outline (mm, page coords) ---
BX0, BY0, BX1, BY1 = 20.0, 20.0, 120.0, 120.0   # 100 x 100 mm

# Placement regions (docs/.../2026-08-10-pcb-rev-b-hardware-design.md §6.2).
# The quiet analog region holds both thermocouple cold junctions and the CT
# front-end; keep it away from the ULN2003 and the SSR optos.
#   digital   x 20..120  y 20..48   module, USB-C, reclaimed antenna band
#   switching x 20..60   y 50..92   ULN2003, SSR optos, watchdog, buzzer
#   analog    x 92..120  y 50..92   MAX31856 x2, ADE7953, CT front-end
#   headers   x 20..120  y 94..120  LCD / nav / aux / I2C, screw terminals
#   barrier   x 20..60   y 74..92   GND pour keepout across the opto row

# net name -> netclass ("signal" default).
# AUX_VP is an externally supplied coil rail the board does not generate, and
# the SSR_* nets are on the isolated side of the opto barrier — neither may
# join the GND/power pour logic.
POWER_NETS = {"GND", "+5V", "+3V3", "VBUS", "VIN", "VLED"}

# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------
# ref: (lib, symbol, fp_lib_id, fp_file, value, (pcb_x, pcb_y, rot), {pin: net})
# net None => explicit no-connect

R0805 = ("Resistor_SMD:R_0805_2012Metric", "R_0805_2012Metric.kicad_mod")
C0805 = ("Capacitor_SMD:C_0805_2012Metric", "C_0805_2012Metric.kicad_mod")
C1206 = ("Capacitor_SMD:C_1206_3216Metric", "C_1206_3216Metric.kicad_mod")
SMA = ("Diode_SMD:D_SMA", "D_SMA.kicad_mod")
SOT23 = ("Package_TO_SOT_SMD:SOT-23", "SOT-23.kicad_mod")
LED0805 = ("LED_SMD:LED_0805_2012Metric", "LED_0805_2012Metric.kicad_mod")
TBLOCK = ("TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
          "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal.kicad_mod")

COMPONENTS = {
    # --- MCU -------------------------------------------------------------
    "U1": dict(lib="RF_Module", sym="ESP32-S3-WROOM-1",
               fp="RF_Module:ESP32-S3-WROOM-1U", fpf="ESP32-S3-WROOM-1U.kicad_mod",
               value="ESP32-S3-WROOM-1U-N16R2", at=(70.0, 33.0, 0),
               pins={"1": "GND", "2": "+3V3", "3": "EN", "4": "IN1",
                     "5": "T_CS", "6": "T_IRQ", "7": "ALARM",
                     "8": "AUX2", "9": "AUX3", "10": "SSR1_CTRL",
                     "11": "I2C_SDA", "12": "LCD_CS", "13": "USB_DN",
                     "14": "USB_DP", "15": "LCD_BL", "16": "LCD_RST",
                     "17": "LCD_DC", "18": "TC1_CS", "19": "SPI_MOSI",
                     "20": "SPI_SCLK", "21": "SPI_MISO", "22": "AUX1",
                     "23": "SSR2_CTRL", "24": "I2C_SCL", "25": "LED_DATA",
                     "26": None, "27": "IO0", "28": "TC2_CS",
                     "29": "WDT_KICK", "30": None, "31": "BTN_UP",
                     "32": "BTN_DOWN", "33": "BTN_LEFT", "34": "BTN_RIGHT",
                     "35": "BTN_SEL", "36": "RXD0", "37": "TXD0",
                     "38": "IN2", "39": "IN3", "40": "GND",
                     "41": "GND"}),
    # --- Power -----------------------------------------------------------
    "J2": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="5V_IN", at=(27.0, 33.0, 270),
               pins={"1": "VIN", "2": "GND"}),
    "D1": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS34", at=(38.0, 28.0, 180),
               pins={"1": "+5V", "2": "VIN"}),
    "D2": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS34", at=(102.5, 106.0, 270),
               pins={"1": "+5V", "2": "VBUS"}),
    "U2": dict(lib="Regulator_Linear", sym="AMS1117-3.3",
               fp="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
               fpf="SOT-223-3_TabPin2.kicad_mod",
               value="AMS1117-3.3", at=(51.0, 33.5, 0),
               pins={"1": "GND", "2": "+3V3", "3": "+5V"}),
    "C1": dict(lib="Device", sym="C", fp=C1206[0], fpf=C1206[1],
               value="22uF/25V", at=(44.5, 28.0, 90),
               pins={"1": "+5V", "2": "GND"}),
    "C2": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="100nF", at=(44.5, 32.5, 90),
               pins={"1": "+5V", "2": "GND"}),
    "C3": dict(lib="Device", sym="C", fp=C1206[0], fpf=C1206[1],
               value="22uF/25V", at=(57.0, 32.5, 270),
               pins={"1": "+3V3", "2": "GND"}),
    "C4": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="100nF", at=(59.5, 32.5, 270),
               pins={"1": "+3V3", "2": "GND"}),
    "LED2": dict(lib="Device", sym="LED", fp=LED0805[0], fpf=LED0805[1],
                 value="green", at=(63.0, 32.5, 270),
                 pins={"1": "LEDP_K", "2": "+3V3"}),
    "R9": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="1k", at=(65.5, 32.5, 270),
               pins={"1": "LEDP_K", "2": "GND"}),
    # decoupling at module
    "C6": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="100nF", at=(76.8, 28.0, 90),
               pins={"1": "+3V3", "2": "GND"}),
    "C7": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="10uF", at=(74.0, 27.6, 0),
               pins={"1": "+3V3", "2": "GND"}),
    # --- EN / BOOT -------------------------------------------------------
    "R1": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(64.8, 28.5, 90),
               pins={"1": "+3V3", "2": "EN"}),
    # Rotated 90 deg (not 0) so the GND pad faces the open pour below rather
    # than the sliver between C5, R1 and the module's left edge. At rot 0 that
    # sliver was too narrow to take a stitching via once vias were barred from
    # sitting inside pads (router.VIA_PAD_GAP), stranding this pad on F.Cu.
    "C5": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="1uF", at=(68.0, 28.7, 90),
               pins={"1": "EN", "2": "GND"}),
    "R2": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(103.4, 35.0, 270),
               pins={"1": "+3V3", "2": "IO0"}),
    # SMD tactile switches, not the 6 mm THT part: XKB TS-1187A (LCSC
    # C318884) is a JLCPCB *Basic* part, so it carries no $3 feeder fee and
    # stays on the SMT line. The THT switches were one of five unique
    # Extended parts that existed only to force Standard assembly.
    "SW1": dict(lib="Switch", sym="SW_Push",
                fp="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
                fpf="SW_Push_1P1T_XKB_TS-1187A.kicad_mod",
                value="RESET", at=(55.0, 23.2, 0),
                pins={"1": "EN", "2": "GND"}),
    "SW2": dict(lib="Switch", sym="SW_Push",
                fp="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
                fpf="SW_Push_1P1T_XKB_TS-1187A.kicad_mod",
                value="BOOT", at=(101.0, 50.2, 0),
                pins={"1": "IO0", "2": "GND"}),
    # --- USB -------------------------------------------------------------
    "J1": dict(lib="Connector", sym="USB_C_Receptacle_USB2.0_16P",
               fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
               fpf="USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod",
               value="USB-C", at=(96.0, 115.6, 0),
               pins={"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
                     "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
                     "A5": "CC1", "B5": "CC2",
                     "A6": "USB_DP", "B6": "USB_DP",
                     "A7": "USB_DN", "B7": "USB_DN",
                     "A8": None, "B8": None,
                     # shield pin: "S1" in KiCad <=9 libs, "SH" in KiCad 10
                     "S1": "GND", "SH": "GND"}),
    "R4": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="5.1k", at=(91.0, 108.0, 90),
               pins={"1": "CC1", "2": "GND"}),
    "R5": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="5.1k", at=(103.5, 117.9, 0),
               pins={"1": "CC2", "2": "GND"}),
    "U4": dict(lib="Power_Protection", sym="USBLC6-2SC6",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="USBLC6-2SC6", at=(96.0, 102.0, 90),
               pins={"1": "USB_DN", "6": "USB_DN",
                     "3": "USB_DP", "4": "USB_DP",
                     "5": "VBUS", "2": "GND"}),
    # --- Thermocouple ------------------------------------------------------
    # 2x MAX31856 (TSSOP-14) replacing the rev A MAX31855. Pinout confirmed
    # against the KiCad 10 Sensor_Temperature:MAX31856 symbol and the Maxim
    # 19-7534 Rev 0 datasheet (see hardware/kicad/datasheets/REV-B-NOTES.md
    # SS5): 1 AGND 2 BIAS 3 T- 4 T+ 5 AVDD 6 DNC 7 ~DRDY 8 DVDD 9 ~CS 10 SCK
    # 11 SDO 12 SDI 13 ~FAULT 14 DGND. ~DRDY/~FAULT/DNC are left NC - both
    # status bits are readable from registers, and polling them is what keeps
    # the GPIO budget closing (spec 4.1). AVDD/DVDD are separate pins but must
    # share one 3V3 rail (datasheet: AVDD-DVDD limited to +-100mV) with
    # independent 100nF decoupling per pin, each to this board's single GND
    # net (no AGND/DGND split plane exists elsewhere on this board).
    #
    # REV-B-NOTES.md SS5a overrides the brief here: there is NO bias bypass
    # capacitor. "This pin is floating when no conversions are taking place...
    # No bypass or decoupling is specified" (datasheet p.10), unlike AVDD/DVDD
    # which both explicitly call for one. The 0.01uF cap in the datasheet's own
    # application drawings belongs to the T- common-mode filter, not to BIAS.
    # The brief's C14 (100nF, BIAS->GND) is therefore omitted outright.
    #
    # BIAS routing: Figure 8 (the filtered topology this design follows, with
    # the 100R series resistors) is explicit that "BIAS connects to the
    # thermocouple side of the resistor" (SS5a) - i.e. the RAW terminal-side
    # node, upstream of the series R, NOT the IC-side filtered T- pin. That is
    # a different diagram from the datasheet's simple Typical Application
    # Circuit (no series resistors), where BIAS and T- share one pin-level
    # node - do not conflate the two. So here BIAS (pin 2) joins TC1_N/TC2_N
    # (the raw terminal net, same node as J3.2/R15.1), while T- (pin 3) stays
    # alone on the IC-side filtered node TC1_N_F/TC2_N_F, symmetric with
    # T+'s TC1_P_F/TC2_P_F. The open-thermocouple detection bias current
    # sources from BIAS through the thermocouple itself, not through the
    # external filter resistor - routing it through R15/R17 the way the
    # simple-circuit reading would have put that bias current across the
    # filter resistor, which Figure 8's topology specifically avoids.
    #
    # Input filter per REV-B-NOTES.md SS5c / datasheet Figure 8 ("Typical
    # Connection to Reduce the Effect of Noise Pickup"), fit unconditionally -
    # this board sits beside SSR-switched mains wiring with a Wi-Fi radio on
    # the same PCB, the RF-field case the datasheet calls out: 100R 1% series
    # in each leg (1% so the T+/T- series resistors stay matched - datasheet
    # p.28 ties resistor mismatch directly to offset voltage), then, on the
    # IC side of those resistors, 100nF differential across T+/T- plus 10nF
    # common-mode from each leg to GND. No TVS on these nets (spec 4.1): a TVS
    # array's leakage into a ~40uV/degC source is an accuracy error, not
    # protection - the RC filter plus the chip's own input clamps are it.
    #
    # TC1_N/TC2_N run to the screw terminal raw, NOT to GND - unlike rev A's
    # MAX31855 whose T- was grounded at the chip, each MAX31856 channel keeps
    # its own floating differential pair (T- is only soft-referenced near
    # AGND through the internal ~2k BIAS network, not hard-tied to it).
    # Ungrounded-junction probes are required on the finished board: both
    # channels reference T- through that shared internal biasing, so two
    # grounded-junction probes in one kiln chamber would form a ground loop
    # through the kiln body (documentation obligation, Task 16 - not a board
    # change).
    "U3": dict(lib="Sensor_Temperature", sym="MAX31856",
               fp="Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
               fpf="TSSOP-14_4.4x5mm_P0.65mm.kicad_mod",
               value="MAX31856MUD+", at=(104.0, 56.0, 90),
               pins={"1": "GND", "2": "TC1_N", "3": "TC1_N_F",
                     "4": "TC1_P_F", "5": "+3V3", "6": None, "7": None,
                     "8": "+3V3", "9": "TC1_CS", "10": "SPI_SCLK",
                     "11": "SPI_MISO", "12": "SPI_MOSI", "13": None,
                     "14": "GND"}),
    "C13": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(100.0, 53.0, 90),
                pins={"1": "+3V3", "2": "GND"}),
    "C14": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(100.0, 59.0, 90),
                pins={"1": "+3V3", "2": "GND"}),
    "R14": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="100R 1%", at=(108.0, 54.0, 0),
                pins={"1": "TC1_P", "2": "TC1_P_F"}),
    "R15": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="100R 1%", at=(108.0, 58.0, 0),
                pins={"1": "TC1_N", "2": "TC1_N_F"}),
    "C15": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(111.0, 56.0, 0),
                pins={"1": "TC1_P_F", "2": "TC1_N_F"}),
    "C16": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10nF", at=(111.0, 53.5, 0),
                pins={"1": "TC1_P_F", "2": "GND"}),
    "C17": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10nF", at=(111.0, 58.5, 0),
                pins={"1": "TC1_N_F", "2": "GND"}),
    "J3": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="TC1_K", at=(117.0, 56.0, 90),
               pins={"1": "TC1_P", "2": "TC1_N"}),
    # --- Thermocouple channel 2 (load TC) - exact copy of channel 1 above,
    # 14mm south, TC2_* nets and TC2_CS. ---
    "U5": dict(lib="Sensor_Temperature", sym="MAX31856",
               fp="Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
               fpf="TSSOP-14_4.4x5mm_P0.65mm.kicad_mod",
               value="MAX31856MUD+", at=(104.0, 70.0, 90),
               pins={"1": "GND", "2": "TC2_N", "3": "TC2_N_F",
                     "4": "TC2_P_F", "5": "+3V3", "6": None, "7": None,
                     "8": "+3V3", "9": "TC2_CS", "10": "SPI_SCLK",
                     "11": "SPI_MISO", "12": "SPI_MOSI", "13": None,
                     "14": "GND"}),
    "C18": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(100.0, 67.0, 90),
                pins={"1": "+3V3", "2": "GND"}),
    "C19": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(100.0, 73.0, 90),
                pins={"1": "+3V3", "2": "GND"}),
    "R16": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="100R 1%", at=(108.0, 68.0, 0),
                pins={"1": "TC2_P", "2": "TC2_P_F"}),
    "R17": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="100R 1%", at=(108.0, 72.0, 0),
                pins={"1": "TC2_N", "2": "TC2_N_F"}),
    "C20": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(111.0, 70.0, 0),
                pins={"1": "TC2_P_F", "2": "TC2_N_F"}),
    "C21": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10nF", at=(111.0, 67.5, 0),
                pins={"1": "TC2_P_F", "2": "GND"}),
    "C22": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10nF", at=(111.0, 72.5, 0),
                pins={"1": "TC2_N_F", "2": "GND"}),
    "J8": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="TC2_K", at=(117.0, 70.0, 90),
               pins={"1": "TC2_P", "2": "TC2_N"}),
    # --- SSR output: two opto-isolated channels ---------------------------
    # LTV-817S-TA1-C (REV-B-NOTES.md SS7). Pinout confirmed from the Lite-On
    # datasheet SS2.3: 1 anode, 2 cathode, 3 emitter, 4 collector - matches
    # KiCad's unnamed Isolator:LTV-817 pin order.
    #
    # Footprint: NONE of the brief's four SO-4_4.4x*_P2.54mm candidates fit -
    # all measure ~6.0-6.3mm pad span; the datasheet's own package drawing
    # (SS2.3) and LCSC's independently-decoded footprint both call for a
    # ~10.16/10.00mm gull-wing lead span. REV-B-NOTES.md SS7b: "choosing any
    # of the four would place each pad roughly 1.85mm per side inboard of the
    # actual gull-wing feet - the part would not land on copper at all."
    # Using Package_DIP:SMDIP-4_W9.53mm instead (9.53mm span, the closest
    # stock KiCad part per the notes: ~0.32mm heel / ~0.69mm toe, 0.235mm/side
    # inboard of LCSC's geometry - acceptable, not ideal, and the least-bad
    # stock option short of hand-drawing to LCSC's exact geometry). The
    # _Clearance8mm variant is NOT used: that extra creepage is a mains-
    # crossing provision, and this barrier is low-voltage on both sides -
    # the extra 8mm creepage would only burn density-constrained board area.
    #
    # GPIO -> R(series) -> opto LED anode -> cathode -> SSR_EN, with the
    # indicator LED as a PARALLEL branch off the same GPIO (not in series:
    # ~2.0V indicator + ~1.2V opto leaves nothing to drop from 3.3V). Both
    # the opto LED cathode and the indicator LED cathode land on SSR_EN,
    # never GND directly - Task 12's watchdog MOSFET gates SSR_EN as the
    # shared return path for both LEDs, so an indicator that stayed lit
    # while the watchdog had cut the SSR would misreport the board's state.
    # R7/R20 (10k) pulldown each GPIO so both opto LEDs stay dark through
    # boot and reset.
    #
    # 220R series, 3.3V GPIO: I_F = (3.3 - V_F) / 220R. Datasheet SS4.2/Fig.4
    # (REV-B-NOTES.md SS7c): V_F ~1.09V typ at 5mA, ~1.4V worst-case max
    # (only specified at 20mA) -> I_F ~8.6-10.1mA. That clears the notes'
    # "do not drive below 5mA" floor (CTR is only guaranteed at the bin's
    # 5mA test condition and falls off steeply below it) with margin, and at
    # I_F >= 5mA the CTR-C bin (200-400% @ 5mA) guarantees I_C >= 10mA min,
    # comfortably inside the SSR input's few-mA trigger requirement.
    "U8": dict(lib="Isolator", sym="LTV-817",
               fp="Package_DIP:SMDIP-4_W9.53mm",
               fpf="SMDIP-4_W9.53mm.kicad_mod",
               value="LTV-817S-TA1-C", at=(30.0, 78.0, 0),
               pins={"1": "SSR1_LED_A", "2": "SSR_EN",
                     "3": "SSR1_B", "4": "SSR1_A"}),
    "R6": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="220R", at=(36.0, 78.0, 180),
               pins={"1": "SSR1_CTRL", "2": "SSR1_LED_A"}),
    "R7": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(40.0, 76.0, 90),
               pins={"1": "SSR1_CTRL", "2": "GND"}),
    "LED3": dict(lib="Device", sym="LED", fp=LED0805[0], fpf=LED0805[1],
                 value="amber", at=(24.5, 74.0, 270),
                 pins={"1": "SSR1_IND_K", "2": "SSR1_IND_A"}),
    "R10": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="680R", at=(28.0, 74.0, 90),
                pins={"1": "SSR1_CTRL", "2": "SSR1_IND_A"}),
    "R18": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="0R", at=(24.5, 71.0, 0),
                pins={"1": "SSR1_IND_K", "2": "SSR_EN"}),
    "J4": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="SSR1", at=(22.5, 82.0, 270),
               pins={"1": "SSR1_A", "2": "SSR1_B"}),
    # --- SSR channel 2: exact copy of channel 1, 8mm south -----------------
    "U9": dict(lib="Isolator", sym="LTV-817",
               fp="Package_DIP:SMDIP-4_W9.53mm",
               fpf="SMDIP-4_W9.53mm.kicad_mod",
               value="LTV-817S-TA1-C", at=(30.0, 86.0, 0),
               pins={"1": "SSR2_LED_A", "2": "SSR_EN",
                     "3": "SSR2_B", "4": "SSR2_A"}),
    "R19": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="220R", at=(36.0, 86.0, 180),
                pins={"1": "SSR2_CTRL", "2": "SSR2_LED_A"}),
    "R20": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(40.0, 84.0, 90),
                pins={"1": "SSR2_CTRL", "2": "GND"}),
    "LED4": dict(lib="Device", sym="LED", fp=LED0805[0], fpf=LED0805[1],
                 value="amber", at=(24.5, 90.0, 270),
                 pins={"1": "SSR2_IND_K", "2": "SSR2_IND_A"}),
    "R21": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="680R", at=(28.0, 90.0, 90),
                pins={"1": "SSR2_CTRL", "2": "SSR2_IND_A"}),
    "R22": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="0R", at=(24.5, 93.0, 0),
                pins={"1": "SSR2_IND_K", "2": "SSR_EN"}),
    "J9": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="SSR2", at=(22.5, 90.0, 270),
               pins={"1": "SSR2_A", "2": "SSR2_B"}),
    # --- Aux output bank (vent / purge / spare) --------------------------
    # ULN2003A: 7 Darlington channels with integrated freewheel diodes to COM,
    # and a JLCPCB *Basic* part - so it replaces ~19 discrete parts at zero
    # feeder fee. Pin order (SOIC-16, confirmed against KiCad 10's own
    # Transistor_Array:ULN2003A symbol): I1..I7 = 1..7, GND = 8, COM = 9,
    # O7..O1 = 10..16 (note O1 is pin 16, so the outputs run backwards).
    #
    # COM goes to AUX_VP, its own screw terminal, NOT the board's +5V: a gas
    # purge solenoid is realistically 12V or 24V DC and the ULN is rated 50V /
    # 500mA per channel. A solder link (SJ1) ties AUX_VP to +5V for plain 5V
    # relays. The buzzer deliberately keeps its discrete driver (Q2/D4/R8/R11)
    # so a 5V buzzer and a 24V solenoid never share a COM rail.
    #
    # R23-R25 hold the inputs low while the ESP32 pins are high-impedance at
    # boot - a floating Darlington input must not energize a solenoid. Per
    # REV-B-NOTES.md SS6, 10k is sufficient: worst case (ignoring the ULN's
    # own nominal-only internal pulldowns) V_in(max) = 50nA x 10k = 0.5mV,
    # ~1000x margin under any threshold that would turn a channel on, and
    # GPIO 14/15/16 carry no pull-up at reset.
    #
    # Designators: the task brief called these R20-R22, but Task 7 (SSR
    # optocoupler channels) already consumed R20-R22 - verified against the
    # live COMPONENTS dict before adding these. Using R23-R25 instead.
    "U6": dict(lib="Transistor_Array", sym="ULN2003A",
               fp="Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
               fpf="SOIC-16_3.9x9.9mm_P1.27mm.kicad_mod",
               value="ULN2003A", at=(44.0, 60.0, 0),
               pins={"1": "AUX1", "2": "AUX2", "3": "AUX3",
                     "4": None, "5": None, "6": None, "7": None,
                     "8": "GND", "9": "AUX_VP",
                     "10": None, "11": None, "12": None, "13": None,
                     "14": "AUX3_OUT", "15": "AUX2_OUT", "16": "AUX1_OUT"}),
    "R23": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(38.0, 56.0, 90),
                pins={"1": "AUX1", "2": "GND"}),
    "R24": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(38.0, 59.0, 90),
                pins={"1": "AUX2", "2": "GND"}),
    "R25": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(38.0, 62.0, 90),
                pins={"1": "AUX3", "2": "GND"}),
    # 4-position terminal: coil rail + three switched low sides.
    "J10": dict(lib="Connector", sym="Screw_Terminal_01x04",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                fpf="TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal.kicad_mod",
                value="AUX", at=(22.5, 60.0, 270),
                pins={"1": "AUX_VP", "2": "AUX1_OUT",
                      "3": "AUX2_OUT", "4": "AUX3_OUT"}),
    # Solder link: AUX_VP <- +5V for 5V relay coils. Open by default.
    "SJ1": dict(lib="Jumper", sym="SolderJumper_2_Open",
                fp="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
                fpf="SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm.kicad_mod",
                value="AUX_VP=5V", at=(30.0, 55.0, 0),
                pins={"1": "+5V", "2": "AUX_VP"}),
    # --- Buzzer ----------------------------------------------------------
    "BZ1": dict(lib="Device", sym="Buzzer",
                fp="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
                fpf="Buzzer_12x9.5RM7.6.kicad_mod",
                value="active 5V", at=(38.0, 98.0, 0),
                pins={"1": "+5V", "2": "BUZZ_K"}),
    "D4": dict(lib="Device", sym="D", fp="Diode_SMD:D_SOD-123",
               fpf="D_SOD-123.kicad_mod", value="1N4148W", at=(49.5, 104.0, 0),
               pins={"1": "+5V", "2": "BUZZ_K"}),
    "Q2": dict(lib="Transistor_FET", sym="AO3400A", fp=SOT23[0], fpf=SOT23[1],
               value="AO3400A", at=(58.0, 100.0, 0),
               pins={"1": "BUZZ_GATE", "2": "GND", "3": "BUZZ_K"}),
    "R11": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="100R", at=(58.8, 94.0, 0),
                pins={"1": "ALARM", "2": "BUZZ_GATE"}),
    "R8": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(62.0, 97.5, 90),
               pins={"1": "BUZZ_GATE", "2": "GND"}),
    # --- WS2812B status LED ---------------------------------------------
    "LED1": dict(lib="LED", sym="WS2812B",
                 fp="LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
                 fpf="LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm.kicad_mod",
                 value="WS2812B", at=(75.0, 106.0, 0),
                 pins={"1": "VLED", "2": None, "3": "GND", "4": "WS_DIN"}),
    "R3": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="330R", at=(82.0, 104.35, 180),
               pins={"1": "LED_DATA", "2": "WS_DIN"}),
    "D3": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS14", at=(72.55, 99.5, 90),
               pins={"1": "VLED", "2": "+5V"}),
    "C10": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(69.0, 101.5, 0),
                pins={"1": "VLED", "2": "GND"}),
    # --- Protected dry-contact inputs (lid / gas flow / spare) -----------
    # Generalises rev A's single lid-switch filter (below) to three
    # identical channels, all on J11, plus one SRV05-4 TVS array covering
    # them. 1k series, 10k pull-up to +3V3, 100nF to GND per channel. Open
    # contact reads HIGH = "open/inactive", so a broken wire, a pulled
    # connector or a failed-open switch all read "open" and fail safe.
    # IN1 = lid (IO4), IN2 = gas-flow interlock (IO2), IN3 = spare (IO1) -
    # see docs/pin-assignments.md. Wire a dry contact between each channel
    # and J11.4 (GND).
    #
    # R13 replaces the ESP32's weak ~45k internal pull-up with a stiff 10k,
    # so an open switch holds the node high against far more leakage and
    # capacitive pickup. R12 limits fault/ESD current into the pin, and C12
    # sees R12||R13 (~0.9k) with the switch closed - a ~1.8 kHz corner
    # (~90us), rising to ~160 Hz (10k x 100nF) with it open. Fast enough to
    # leave mechanical bounce to the firmware, which samples at 500 ms;
    # slow enough to swallow EMI transients. Closed-switch level is
    # 3.3V x 1k/11k = 0.30V, well under the ESP32's 0.25 x VDD (0.83V) V_IL.
    #
    # Rev A skipped a TVS (a unique Extended part / $3 feeder fee for one
    # input); rev B's externally-exposed net count goes from two to ~ten,
    # so one SRV05-4 array (D5) now covers all three raw inputs upstream of
    # the series resistors. NOT extended to the thermocouple inputs
    # (TC1_P/N, TC2_P/N, Task 6) - array leakage into a ~40 uV/C source is
    # an accuracy error, not protection.
    #
    # Designator note: the brief that originated this block called for
    # R23-R26; R23-R25 were already consumed by Task 8's ULN2003 pulldowns
    # by the time this landed, so the second and third channels use the
    # next free run, R26-R29, instead. Re-verify against the live
    # COMPONENTS dict before reusing numbers near here - a duplicate key
    # silently overwrites the earlier component.
    #
    # Placement: R12/R13/C12 (channel 1, née rev A's lid filter) keep their
    # original spot in the free band between LED1 and J7. Channels 2 and 3
    # extend the same schematic row/PCB band eastward; D5 and J11 sit just
    # past them. See gen_sch.py SCH_AT for the >=20mm spacing rule that
    # keeps facing pin-label stubs from merging nets (Tasks 7, 8).
    "R12": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(87.3, 107.6, 180),
                pins={"1": "IN1_RAW", "2": "IN1"}),
    "R13": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(83.5, 101.5, 0),
                pins={"1": "+3V3", "2": "IN1"}),
    "C12": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(83.8, 107.6, 0),
                pins={"1": "IN1", "2": "GND"}),
    "R26": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(96.0, 100.0, 180),
                pins={"1": "IN2_RAW", "2": "IN2"}),
    "R27": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(92.0, 97.0, 0),
                pins={"1": "+3V3", "2": "IN2"}),
    "C23": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(92.0, 106.0, 0),
                pins={"1": "IN2", "2": "GND"}),
    "R28": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(96.0, 108.0, 180),
                pins={"1": "IN3_RAW", "2": "IN3"}),
    "R29": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(92.0, 109.0, 0),
                pins={"1": "+3V3", "2": "IN3"}),
    "C24": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(92.0, 112.0, 0),
                pins={"1": "IN3", "2": "GND"}),
    # SRV05-4: 1 IO1, 2 VN(GND), 3 IO2, 4 IO3, 5 VP(+3V3), 6 IO4 (spare).
    "D5": dict(lib="Power_Protection", sym="SRV05-4",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="SRV05-4", at=(101.0, 104.0, 0),
               pins={"1": "IN1_RAW", "2": "GND", "3": "IN2_RAW",
                     "4": "IN3_RAW", "5": "+3V3", "6": None}),
    "J11": dict(lib="Connector", sym="Screw_Terminal_01x04",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                fpf="TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal.kicad_mod",
                value="INPUTS", at=(112.0, 104.0, 90),
                pins={"1": "IN1_RAW", "2": "IN2_RAW",
                      "3": "IN3_RAW", "4": "GND"}),
    # --- CT current sensing (ADE7953, I2C, current-only) -----------------
    # Two current channels, one per SSR zone. I2C rather than SPI: the bus
    # exists for the expansion header anyway (Task 11), so the chip costs
    # zero extra GPIOs.
    #
    # NO MAINS ON THIS BOARD. The voltage channel (VP/VN) is unpopulated and
    # goes to J13, a DNP SELV header, so a future off-board isolated AC
    # accessory upgrades this to true power in firmware alone. IRMS is
    # reported against a configured nominal mains voltage until then
    # (REV-B-NOTES.md SS1: IRMSA/IRMSB are computed entirely within the
    # current signal path and do not depend on VP/VN).
    #
    # Every value below is taken from hardware/kicad/datasheets/REV-B-NOTES.md
    # (ADE7953 Rev. C), which OVERRIDES the task brief's guessed values.
    # Designators were renumbered against the live COMPONENTS dict: the
    # brief's R27-R33/D8 collide with Task 9 (R27/R28/R29) and Task 7 (D5).
    #
    # Interface strapping (REV-B-NOTES.md SS3, correcting the brief):
    #   pins 7/8 PULL_HIGH -> +3V3 direct, no resistor (Table 5: "internal
    #     node pins", not interface-select - the brief's framing was wrong)
    #   pin 14 PULL_LOW -> GND direct, no resistor; routed into the EP land
    #   pin 25 SCLK -> +3V3 via R37 10k pull-up (interface-select: 1 = I2C)
    #   pin 28 ~CS -> +3V3 via R38 10k pull-up (interface-select: 1 = I2C/UART)
    #   pin 27 MOSI/SCL/Rx -> I2C_SCL, pin 26 MISO/SDA/Tx -> I2C_SDA (the
    #     ACTUAL bus signals - the brief had these swapped onto pins 25/28)
    # 10k is Figure 35's Test Circuit value; the datasheet gives no
    # resistor spec for 25/28 (COULD NOT VERIFY #3), only "pulled high".
    # Both pins are static logic inputs nothing else drives, so the value
    # isn't critical - resistors instead of hard ties buy an override path
    # for bring-up or a future SPI experiment for 2 cents.
    #
    # I2C address is fixed at 0x38 (no address pins, REV-B-NOTES.md SS3) -
    # collides with a PCF8574A expander and some touch controllers on the
    # Task 11 expansion header. Nothing else on THIS board's bus conflicts.
    #
    # Pins left unconnected: 1 ZX (voltage zero-cross, meaningless with no
    # voltage channel), 20 ~REVP (needs both channels), 23/24 CF1/CF2
    # (calibration frequency outputs, unused). 21 ZX_I and 22 ~IRQ are also
    # left NC for now - REV-B-NOTES.md SS1/SS3 recommend routing both to a
    # GPIO (ZX_I for the datasheet's recommended synchronous IRMS read;
    # IRQ for the power-up-complete signal) but no GPIO is allocated to
    # this task's scope; a bare test point is a candidate for Task 13.
    #
    # EP (pin 29) is a ground pin, not just a thermal tab (REV-B-NOTES.md
    # SS2, Rev. C p.10/p.68: "Connect the pad to AGND and DGND") - tied GND.
    "U7": dict(lib="Sensor", sym="ADE7953xCP",
               fp="Package_DFN_QFN:QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm",
               fpf="QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm.kicad_mod",
               value="ADE7953ACPZ", at=(104.0, 86.0, 0),
               pins={"1": None, "2": "ADE_RESET", "3": "ADE_VINTD",
                     "4": "GND", "5": "CTA_F", "6": "GND",
                     "7": "+3V3", "8": "+3V3", "9": "CTB_F", "10": "GND",
                     "11": "ADE_VN", "12": "ADE_VP", "13": "ADE_REF",
                     "14": "GND", "15": "ADE_VINTA", "16": "GND",
                     "17": "+3V3", "18": "ADE_CLKIN", "19": "ADE_CLKOUT",
                     "20": None, "21": None, "22": None, "23": None,
                     "24": None, "25": "ADE_SCLK", "26": "I2C_SDA",
                     "27": "I2C_SCL", "28": "ADE_CS", "29": "GND"}),
    # Crystal: 3.579545 MHz parallel-resonant AT, per REV-B-NOTES.md SS4.
    # Footprint corrected per the task brief's amendment #2: KiCad's
    # Crystal_SMD_HC49-SD_HandSoldering (NOT the non-"_SMD_" name in the
    # original brief text).
    "Y1": dict(lib="Device", sym="Crystal",
               fp="Crystal:Crystal_SMD_HC49-SD_HandSoldering",
               fpf="Crystal_SMD_HC49-SD_HandSoldering.kicad_mod",
               value="3.579545MHz", at=(114.0, 76.0, 0),
               pins={"1": "ADE_CLKIN", "2": "ADE_CLKOUT"}),
    # Crystal load caps - ASSUMED VALUE, NOT A VERIFIED DATASHEET NUMBER.
    # REV-B-NOTES.md SS4/SS10#1: the specified crystal (LCSC C7471632, YXC
    # H6OEL89CSC-SUGYLC-3.579545M) has no published C_L - LCSC exposes no
    # datasheet or C_L field for this MPN, and it explicitly warns "Task 10
    # must not simply copy 20 pF" (ADI's reference-design value is for
    # ADI's own reference crystal, not this one). The notes give the
    # formula C = 2 x (C_L - C_stray) and note that IF this part turns out
    # to be a 20 pF C_L crystal, the load caps should be ~30 pF, not 20 pF.
    # ASSUMPTION (open item for board bring-up, not a datasheet fact):
    # 30 pF, taking the notes' own worked "if C_L=20pF" figure as the best
    # available estimate absent a real C_L. Verify against YXC's datasheet
    # (if obtainable) or by measuring startup margin/frequency on the first
    # populated board before relying on accuracy-critical IRMS readings.
    "C25": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="30pF", at=(111.0, 74.0, 0),
                pins={"1": "ADE_CLKIN", "2": "GND"}),
    "C26": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="30pF", at=(117.0, 74.0, 0),
                pins={"1": "ADE_CLKOUT", "2": "GND"}),
    # ~RESET (pin 2): REV-B-NOTES.md SS4 - Figure 35's Test Circuit shows a
    # 10k pull-up to 3.3V with a 1uF cap to ground for a power-on reset
    # stretch (Figure 78's application circuit shows nothing on this pin -
    # it's application-dependent). Datasheet minimum low pulse is 10us; a
    # software reset and the datasheet's own reset interrupt are both
    # available if this network is omitted, but the stretch is cheap.
    "R30": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(97.0, 78.0, 0),
                pins={"1": "+3V3", "2": "ADE_RESET"}),
    "C37": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="1uF", at=(97.0, 81.0, 0),
                pins={"1": "ADE_RESET", "2": "GND"}),
    # SCLK / ~CS interface-select pull-ups - see the strapping note above.
    "R37": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(97.0, 84.0, 0),
                pins={"1": "+3V3", "2": "ADE_SCLK"}),
    "R38": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(97.0, 87.0, 0),
                pins={"1": "+3V3", "2": "ADE_CS"}),
    # VINTA/VINTD/REF/VDD decoupling - REV-B-NOTES.md SS4 (Table 5, cross-
    # checked against Figure 78): each of VINTA, VINTD and REF (all internal
    # LDO/reference OUTPUTS to be decoupled, never driven) gets 4.7uF || 100nF;
    # VDD gets 10uF || 100nF. That's 8 physical capacitors, more than the
    # brief's 4 pre-allocated designators (C27-C30) provided for, so the
    # extra four are allocated sequentially from C33 as the task instructions
    # direct. The ceramic (100nF) of each pair is the one to place closest to
    # the IC per the datasheet's own layout guidance (Rev. C p.68); exact
    # placement is Task 14's job.
    "C27": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="4.7uF", at=(118.0, 76.0, 0),
                pins={"1": "ADE_VINTA", "2": "GND"}),
    "C28": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(118.0, 78.0, 0),
                pins={"1": "ADE_VINTA", "2": "GND"}),
    "C29": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="4.7uF", at=(118.0, 80.0, 0),
                pins={"1": "ADE_VINTD", "2": "GND"}),
    "C30": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(118.0, 82.0, 0),
                pins={"1": "ADE_VINTD", "2": "GND"}),
    "C33": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="4.7uF", at=(118.0, 84.0, 0),
                pins={"1": "ADE_REF", "2": "GND"}),
    "C34": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(118.0, 86.0, 0),
                pins={"1": "ADE_REF", "2": "GND"}),
    "C35": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10uF", at=(118.0, 88.0, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "C36": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(118.0, 90.0, 0),
                pins={"1": "+3V3", "2": "GND"}),
    # Channel A burden + anti-alias. The ADE7953's current inputs are
    # bipolar, referenced to AGND directly - no mid-rail bias divider like a
    # single-supply ADC (this is not in REV-B-NOTES.md; it's how a
    # differential current-sense front-end normally works, and the brief's
    # amended text already reflects it). R32/C31 form a ~4.8 kHz pole, well
    # above the 60 Hz fundamental and its usable harmonics, well below the
    # modulator rate.
    #
    # Sizing (not from REV-B-NOTES.md - the notes don't cover the CT/burden
    # network, only the ADE7953 itself): a 2000:1 current-output clamp
    # (100A:50mA, e.g. SCT-013-000) against the ADE7953's +-500mV full-scale
    # differential input. 100A rms -> 50mA rms -> 70.7mA peak;
    # 0.5V / 70.7mA ~= 7.1 Ohm, so 6.8 Ohm gives headroom. This CT ratio is
    # a calibration constant the firmware will need - see docs/pin-
    # assignments.md (Task 16).
    "R31": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="6R8", at=(108.0, 82.0, 0),
                pins={"1": "CTA_P", "2": "CTA_N"}),
    "R32": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(105.0, 82.0, 0),
                pins={"1": "CTA_P", "2": "CTA_F"}),
    "R33": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(105.0, 84.0, 0),
                pins={"1": "CTA_N", "2": "GND"}),
    "C31": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="33nF", at=(102.0, 83.0, 0),
                pins={"1": "CTA_F", "2": "GND"}),
    # Channel B - exact copy of channel A above, 6mm south.
    "R34": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="6R8", at=(108.0, 88.0, 0),
                pins={"1": "CTB_P", "2": "CTB_N"}),
    "R35": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(105.0, 88.0, 0),
                pins={"1": "CTB_P", "2": "CTB_F"}),
    "R36": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(105.0, 90.0, 0),
                pins={"1": "CTB_N", "2": "GND"}),
    "C32": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="33nF", at=(102.0, 89.0, 0),
                pins={"1": "CTB_F", "2": "GND"}),
    # Spec SS5.5's second SRV05-4 (the first, D5, covers the dry-contact
    # inputs). NOT on the thermocouple inputs - array leakage into a
    # ~40uV/degC source is an accuracy error, not protection. SRV05-4
    # pinout matches D5's: 1 IO1, 2 GND, 3 IO2, 4 IO3, 5 VP(+3V3), 6 IO4.
    "D6": dict(lib="Power_Protection", sym="SRV05-4",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="SRV05-4", at=(108.0, 91.0, 0),
               pins={"1": "CTA_P", "2": "GND", "3": "CTA_N",
                     "4": "CTB_P", "5": "+3V3", "6": "CTB_N"}),
    "J12": dict(lib="Connector", sym="Screw_Terminal_01x04",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                fpf="TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal.kicad_mod",
                value="CT", at=(116.0, 86.0, 90),
                pins={"1": "CTA_P", "2": "CTA_N", "3": "CTB_P", "4": "CTB_N"}),
    # DNP: SELV AC voltage input for a future true-power upgrade. Not
    # fitted - NO MAINS ON THIS BOARD. REV-B-NOTES.md SS1 ("Handling of the
    # unused voltage inputs"): the datasheet gives no explicit guidance for
    # leaving VP/VN floating (COULD NOT VERIFY #4); this DNP header is the
    # engineering recommendation - it keeps the high-impedance PGA inputs
    # off a floating net on a board that also carries SSR switching, while
    # leaving the pins genuinely unpopulated absent the header being fitted.
    "J13": dict(lib="Connector_Generic", sym="Conn_01x02",
                fp="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
                fpf="PinHeader_1x02_P2.54mm_Vertical.kicad_mod",
                value="AC_SENSE_DNP", at=(96.0, 92.0, 0),
                pins={"1": "ADE_VP", "2": "ADE_VN"}),
    # --- Headers ---------------------------------------------------------
    "J5": dict(lib="Connector_Generic", sym="Conn_01x08",
               fp="Connector_Molex:Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical.kicad_mod",
               value="DISPLAY", at=(31.0, 115.0, 0),
               # LCDWIKI 4.0" MSP4020/MSP4021 (ST7796S, 480x320): pin order
               # VCC/GND/CS/RESET/DC/SDI(MOSI)/SCK/LED matches 1-8 exactly.
               # VCC accepts 3.3-5V per the module's own manual, and every
               # reference wiring diagram in it (incl. 3.3V-logic STM32
               # boards) ties VCC to 5V while driving CS/RESET/DC/MOSI/SCK
               # directly from 3.3V GPIOs with no level shifter - so +5V
               # here needs no other board change. Moving off +3V3 also
               # takes the backlight/panel current off the AMS1117 (U2)
               # entirely rather than through its LDO drop.
               pins={"1": "+5V", "2": "GND", "3": "LCD_CS", "4": "LCD_RST",
                     "5": "LCD_DC", "6": "SPI_MOSI", "7": "SPI_SCLK",
                     "8": "LCD_BL"}),
    "C11": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10uF", at=(26.5, 110.5, 0),
                pins={"1": "+5V", "2": "GND"}),
    "J6": dict(lib="Connector_Generic", sym="Conn_01x06",
               fp="Connector_Molex:Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical.kicad_mod",
               value="NAV_SW", at=(53.0, 115.0, 0),
               pins={"1": "BTN_UP", "2": "BTN_DOWN", "3": "BTN_LEFT",
                     "4": "BTN_RIGHT", "5": "BTN_SEL", "6": "GND"}),
    "J7": dict(lib="Connector_Generic", sym="Conn_01x08",
               fp="Connector_Molex:Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical.kicad_mod",
               value="AUX", at=(70.5, 115.0, 0),
               pins={"1": "+3V3", "2": "GND", "3": "TXD0", "4": "RXD0",
                     # pin 6 carried the raw lid-switch input in rev A; the
                     # lid moved to its own terminal (J11) in Task 9, so
                     # this pin is unconnected until Task 11 re-points J7's
                     # pins 5-8 to I2C.
                     "5": "VENT", "6": None, "7": "AUX_A", "8": "AUX_B"}),
    # --- Mounting holes (grounded) --------------------------------------
    "H1": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(25.5, 25.0, 0), pins={"1": "GND"}),
    "H2": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(115.5, 25.0, 0), pins={"1": "GND"}),
    "H3": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(25.5, 115.0, 0), pins={"1": "GND"}),
    "H4": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(115.5, 115.0, 0), pins={"1": "GND"}),
}

# power flag symbols (schematic only): net -> flag
PWR_FLAG_NETS = ["GND", "+5V", "VBUS", "VIN", "VLED"]


def netlist():
    """net -> [(ref, pin), ...] (S1/SH shield aliases collapsed to S1)"""
    nets = {}
    for ref, c in COMPONENTS.items():
        for pin, net in c["pins"].items():
            if net is None or (ref, pin) == ("J1", "SH"):
                continue
            nets.setdefault(net, []).append((ref, pin))
    return nets


if __name__ == "__main__":
    nl = netlist()
    for net in sorted(nl):
        pins = nl[net]
        flag = "  !! single-pin" if len(pins) < 2 else ""
        print("%-10s %s%s" % (net, " ".join("%s.%s" % p for p in pins), flag))
