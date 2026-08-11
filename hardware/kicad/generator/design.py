"""Bisque kiln controller PCB — single source of truth.

Components, pin->net connectivity, and PCB placement. Both the schematic and
board generators derive everything from these tables, so the two files can
never disagree on connectivity.

Pin GPIO mapping mirrors main/Kconfig.projbuild defaults (the firmware's
source of truth):
  SPI: MOSI=11 MISO=13 SCLK=12 | TC CS=10 | SSR=17
  LCD: CS=8 DC=9 RST=46 BL=3   | WS2812=48 | ALARM=7
  BTN: UP=4 DOWN=5 SEL=1 LEFT=6 RIGHT=2
  Touch (Task 11): CS=? IRQ=? — dedicated GPIOs; T_CLK/T_DIN/T_DO are the
    shared SPI2 bus (SPI_SCLK/SPI_MOSI/SPI_MISO) through series resistors.
  I2C (Task 11): SDA/SCL — shared bus, pulled up on-board, broken out on
    both J7 (0.1") and J14 (Qwiic/STEMMA QT).
  J11: IN1(lid)=4 IN2(gas flow)=2 IN3(spare)=1

J7's pins 5-8 carried VENT/(unconnected)/AUX_A/AUX_B through Task 10, all
either dangling single-pin nets or declared-but-undriven — nothing on this
board actually sourced them (the real VENT output is AUX1, wired to the
ULN2003 aux bank, U6). Task 11 re-points J7 5-8 to I2C_SDA/I2C_SCL/+3V3/GND,
retiring the AUX_A/AUX_B nets for good and giving the I2C bus a 0.1" header
alongside the Qwiic connector (J14). IN1/IN2/IN3 (Task 9) land on their own
terminal, J11, not J7 - rev A's lid switch was the only occupant of J7.6 and
has moved there. Note that an enabled-but-unwired IN1 (lid) reads open and
holds the SSR off - it needs a switch, a jumper to GND, or -1. The full
as-built map, the constraints behind it, and the planned expansion live in
docs/pin-assignments.md — keep that table in sync with this one.
"""

# --- board outline (mm, page coords) ---
# 125 x 100 mm - spec 6.3 rung 2. Rev B did not route at 100 x 100 even with
# every passive on 0603 (rung 1): the ADE7953 block, which has to hold a QFN-28
# plus a crystal, eight decoupling capacitors, four strapping parts and a
# ten-part CT front-end between the module's escape corridor and the board
# edge, was still ~10 nets short. The extra 25 mm all goes to that column. This
# leaves JLCPCB's <=100x100 promo tier: bare boards go from ~$2-4 to ~$10-15
# for 5 pieces. See the task 14 report for the DRC counts at each rung.
BX0, BY0, BX1, BY1 = 20.0, 20.0, 145.0, 120.0   # 125 x 100 mm

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

# Chip passives are 0603, not rev A's 0805 (spec 6.3 rung 1). Rev B put 2.7x
# rev A's part count on 1.25x the area; at 0805 the board could not be routed -
# see the task 14 report for the DRC numbers at each rung. 0603 and 0805 are
# both JLCPCB *Basic* sizes, so this costs no feeder fee and no assembly tier;
# it only obliges the BOM (gen_jlc.py, task 15) to pick 0603 LCSC parts. The
# 22 uF/25 V bulk capacitors stay 1206 - that value/voltage is not a Basic part
# in 0603, and neither sits in a congested area.
R0603 = ("Resistor_SMD:R_0603_1608Metric", "R_0603_1608Metric.kicad_mod")
C0603 = ("Capacitor_SMD:C_0603_1608Metric", "C_0603_1608Metric.kicad_mod")
C1206 = ("Capacitor_SMD:C_1206_3216Metric", "C_1206_3216Metric.kicad_mod")
SMA = ("Diode_SMD:D_SMA", "D_SMA.kicad_mod")
SOT23 = ("Package_TO_SOT_SMD:SOT-23", "SOT-23.kicad_mod")
LED0603 = ("LED_SMD:LED_0603_1608Metric", "LED_0603_1608Metric.kicad_mod")
TBLOCK = ("TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
          "TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal.kicad_mod")

COMPONENTS = {
    # --- MCU -------------------------------------------------------------
    "U1": dict(lib="RF_Module", sym="ESP32-S3-WROOM-1",
               fp="RF_Module:ESP32-S3-WROOM-1U", fpf="ESP32-S3-WROOM-1U.kicad_mod",
               value="ESP32-S3-WROOM-1U-N16R2", at=(70.0, 34.0, 0),
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
               fp=TBLOCK[0], fpf=TBLOCK[1], value="5V_IN", at=(26.0, 39.0, 270),
               pins={"1": "VIN", "2": "GND"}),
    "D1": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS34", at=(36.75, 45.6, 0),
               pins={"1": "+5V", "2": "VIN"}),
    "D2": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS34", at=(56.25, 35.3, 0),
               pins={"1": "+5V", "2": "VBUS"}),
    "U2": dict(lib="Regulator_Linear", sym="AMS1117-3.3",
               fp="Package_TO_SOT_SMD:SOT-223-3_TabPin2",
               fpf="SOT-223-3_TabPin2.kicad_mod",
               value="AMS1117-3.3", at=(36.6, 39.5, 0),
               pins={"1": "GND", "2": "+3V3", "3": "+5V"}),
    "C1": dict(lib="Device", sym="C", fp=C1206[0], fpf=C1206[1],
               value="22uF/25V", at=(44.0, 39.5, 0),
               pins={"1": "+5V", "2": "GND"}),
    "C2": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
               value="100nF", at=(42.25, 45.6, 0),
               pins={"1": "+5V", "2": "GND"}),
    "C3": dict(lib="Device", sym="C", fp=C1206[0], fpf=C1206[1],
               value="22uF/25V", at=(49.35, 39.5, 0),
               pins={"1": "+3V3", "2": "GND"}),
    "C4": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
               value="100nF", at=(53.65, 39.5, 0),
               pins={"1": "+3V3", "2": "GND"}),
    "LED2": dict(lib="Device", sym="LED", fp=LED0603[0], fpf=LED0603[1],
                 value="green", at=(55.5, 22.3, 0),
                 pins={"1": "LEDP_K", "2": "+3V3"}),
    "R9": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="1k", at=(55.5, 25.0, 0),
               pins={"1": "LEDP_K", "2": "GND"}),
    # decoupling at module
    "C6": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
               value="100nF", at=(58.6, 28.0, 90),
               pins={"1": "+3V3", "2": "GND"}),
    "C7": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
               value="10uF", at=(58.6, 23.8, 90),
               pins={"1": "+3V3", "2": "GND"}),
    # --- EN / BOOT -------------------------------------------------------
    "R1": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="10k", at=(56.0, 42.5, 0),
               pins={"1": "+3V3", "2": "EN"}),
    # Rotated 90 deg (not 0) so the GND pad faces the open pour below rather
    # than the sliver between C5, R1 and the module's left edge. At rot 0 that
    # sliver was too narrow to take a stitching via once vias were barred from
    # sitting inside pads (router.VIA_PAD_GAP), stranding this pad on F.Cu.
    "C5": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
               value="1uF", at=(52.0, 42.5, 0),
               pins={"1": "EN", "2": "GND"}),
    "R2": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="10k", at=(106.0, 22.5, 0),
               pins={"1": "+3V3", "2": "IO0"}),
    # SMD tactile switches, not the 6 mm THT part: XKB TS-1187A (LCSC
    # C318884) is a JLCPCB *Basic* part, so it carries no $3 feeder fee and
    # stays on the SMT line. The THT switches were one of five unique
    # Extended parts that existed only to force Standard assembly.
    "SW1": dict(lib="Switch", sym="SW_Push",
                fp="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
                fpf="SW_Push_1P1T_XKB_TS-1187A.kicad_mod",
                value="RESET", at=(36.5, 24.2, 0),
                pins={"1": "EN", "2": "GND"}),
    "SW2": dict(lib="Switch", sym="SW_Push",
                fp="Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
                fpf="SW_Push_1P1T_XKB_TS-1187A.kicad_mod",
                value="BOOT", at=(100.0, 25.0, 0),
                pins={"1": "IO0", "2": "GND"}),
    # --- USB -------------------------------------------------------------
    "J1": dict(lib="Connector", sym="USB_C_Receptacle_USB2.0_16P",
               fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
               fpf="USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod",
               value="USB-C", at=(48.0, 24.4, 180),
               pins={"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
                     "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
                     "A5": "CC1", "B5": "CC2",
                     "A6": "USB_DP", "B6": "USB_DP",
                     "A7": "USB_DN", "B7": "USB_DN",
                     "A8": None, "B8": None,
                     # shield pin: "S1" in KiCad <=9 libs, "SH" in KiCad 10
                     "S1": "GND", "SH": "GND"}),
    "R4": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="5.1k", at=(50.75, 34.4, 0),
               pins={"1": "CC1", "2": "GND"}),
    "R5": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="5.1k", at=(42.7, 34.4, 0),
               pins={"1": "CC2", "2": "GND"}),
    "U4": dict(lib="Power_Protection", sym="USBLC6-2SC6",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="USBLC6-2SC6", at=(46.75, 34.4, 0),
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
               value="MAX31856MUD+", at=(97.0, 37.8, 270),
               pins={"1": "GND", "2": "TC1_N", "3": "TC1_N_F",
                     "4": "TC1_P_F", "5": "+3V3", "6": None, "7": None,
                     "8": "+3V3", "9": "TC1_CS", "10": "SPI_SCLK",
                     "11": "SPI_MISO", "12": "SPI_MOSI", "13": None,
                     "14": "GND"}),
    "C13": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(90.0, 35.0, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "C14": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(90.0, 40.5, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "R14": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="100R 1%", at=(104.0, 37.5, 180),
                pins={"1": "TC1_P", "2": "TC1_P_F"}),
    "R15": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="100R 1%", at=(109.0, 37.5, 180),
                pins={"1": "TC1_N", "2": "TC1_N_F"}),
    "C15": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(114.0, 37.5, 0),
                pins={"1": "TC1_P_F", "2": "TC1_N_F"}),
    "C16": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="10nF", at=(119.0, 37.5, 0),
                pins={"1": "TC1_P_F", "2": "GND"}),
    "C17": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="10nF", at=(124.0, 37.5, 0),
                pins={"1": "TC1_N_F", "2": "GND"}),
    "J3": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="TC1_K", at=(139.0, 41.0, 90),
               pins={"1": "TC1_P", "2": "TC1_N"}),
    # --- Thermocouple channel 2 (load TC) - exact copy of channel 1 above,
    # 14mm south, TC2_* nets and TC2_CS. ---
    "U5": dict(lib="Sensor_Temperature", sym="MAX31856",
               fp="Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
               fpf="TSSOP-14_4.4x5mm_P0.65mm.kicad_mod",
               value="MAX31856MUD+", at=(97.0, 49.8, 90),
               pins={"1": "GND", "2": "TC2_N", "3": "TC2_N_F",
                     "4": "TC2_P_F", "5": "+3V3", "6": None, "7": None,
                     "8": "+3V3", "9": "TC2_CS", "10": "SPI_SCLK",
                     "11": "SPI_MISO", "12": "SPI_MOSI", "13": None,
                     "14": "GND"}),
    "C18": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(90.0, 47.5, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "C19": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(90.0, 53.0, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "R16": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="100R 1%", at=(104.0, 49.5, 180),
                pins={"1": "TC2_P", "2": "TC2_P_F"}),
    "R17": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="100R 1%", at=(109.0, 49.5, 180),
                pins={"1": "TC2_N", "2": "TC2_N_F"}),
    "C20": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(114.0, 49.5, 0),
                pins={"1": "TC2_P_F", "2": "TC2_N_F"}),
    "C21": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="10nF", at=(119.0, 49.5, 0),
                pins={"1": "TC2_P_F", "2": "GND"}),
    "C22": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="10nF", at=(124.0, 49.5, 0),
                pins={"1": "TC2_N_F", "2": "GND"}),
    "J8": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="TC2_K", at=(139.0, 53.0, 90),
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
               value="LTV-817S-TA1-C", at=(38.5, 78.0, 180),
               pins={"1": "SSR1_LED_A", "2": "SSR_EN",
                     "3": "SSR1_B", "4": "SSR1_A"}),
    "R6": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="220R", at=(49.0, 80.5, 180),
               pins={"1": "SSR1_CTRL", "2": "SSR1_LED_A"}),
    "R7": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="10k", at=(54.0, 80.5, 0),
               pins={"1": "SSR1_CTRL", "2": "GND"}),
    "LED3": dict(lib="Device", sym="LED", fp=LED0603[0], fpf=LED0603[1],
                 value="amber", at=(57.0, 76.0, 0),
                 pins={"1": "SSR1_IND_K", "2": "SSR1_IND_A"}),
    "R10": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="680R", at=(52.0, 76.25, 0),
                pins={"1": "SSR1_CTRL", "2": "SSR1_IND_A"}),
    "R18": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="0R", at=(57.0, 72.0, 0),
                pins={"1": "SSR1_IND_K", "2": "SSR_EN"}),
    "J4": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="SSR1", at=(26.0, 75.5, 270),
               pins={"1": "SSR1_A", "2": "SSR1_B"}),
    # --- SSR channel 2: exact copy of channel 1, 8mm south -----------------
    "U9": dict(lib="Isolator", sym="LTV-817",
               fp="Package_DIP:SMDIP-4_W9.53mm",
               fpf="SMDIP-4_W9.53mm.kicad_mod",
               value="LTV-817S-TA1-C", at=(38.5, 90.0, 180),
               pins={"1": "SSR2_LED_A", "2": "SSR_EN",
                     "3": "SSR2_B", "4": "SSR2_A"}),
    "R19": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="220R", at=(52.0, 92.5, 180),
                pins={"1": "SSR2_CTRL", "2": "SSR2_LED_A"}),
    "R20": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(57.0, 92.5, 0),
                pins={"1": "SSR2_CTRL", "2": "GND"}),
    "LED4": dict(lib="Device", sym="LED", fp=LED0603[0], fpf=LED0603[1],
                 value="amber", at=(54.0, 87.5, 0),
                 pins={"1": "SSR2_IND_K", "2": "SSR2_IND_A"}),
    "R21": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="680R", at=(49.0, 87.5, 0),
                pins={"1": "SSR2_CTRL", "2": "SSR2_IND_A"}),
    "R22": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="0R", at=(58.5, 87.5, 0),
                pins={"1": "SSR2_IND_K", "2": "SSR_EN"}),
    "J9": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="SSR2", at=(26.0, 88.0, 270),
               pins={"1": "SSR2_A", "2": "SSR2_B"}),
    # --- Hardware watchdog (Task 12) ---------------------------------------
    # WDT_KICK (U1.29, a firmware square wave) drives a diode charge pump;
    # the hold node keeps Q3 enhanced, and Q3's drain IS the SSR_EN net - the
    # shared return path for both opto LED cathodes and both indicator LED
    # cathodes (U8.2/R18.2/U9.2/R22.2). Stop kicking and the pump decays
    # below Q3's Vgs(th) in ~1s (R46*C39, see arithmetic below), dropping
    # both SSRs. This is the only interlock on this board that survives
    # firmware death - lid/over-temp/stale-TC are firmware-owned and die
    # with it. It is still only SUPPLEMENTARY: the real protection is a
    # mechanical over-temperature cutout in series with the element
    # contactor.
    #
    # A CHARGE PUMP NEEDS TRANSITIONS - that is the entire point. Firmware
    # wedged with WDT_KICK stuck high must fail exactly like firmware that
    # stopped toggling. C38 is a series (AC-coupling) cap, not a pull-up, so
    # a DC level at WDT_KICK (high OR low) delivers no net charge per cycle
    # and WDT_HOLD decays through R46 regardless of which level it stuck at.
    # A plain RC hold driven by a level would be defeated by a stuck-high
    # pin; this topology cannot be.
    #
    # Gates ONLY the heat outputs (SSR_EN). AUX1-3 (vent/purge/spare, via
    # U6/ULN2003) and the buzzer are on separate nets entirely - untouched by
    # Q3 - so a stalled controller can still open its vent.
    #
    # --- Parts: REV-B-NOTES.md SS8a overrides the brief -------------------
    # The brief specified two discrete SOD-123 singles (D6/D7). REV-B-NOTES
    # SS8a identifies the correct part as ONE BAT54S dual Schottky in a
    # single SOT-23 (LCSC C7420333, JLCPCB Extended-but-Preferred,
    # ~$0.011) - specifically the *series* pair: datasheet Table 2 "Pinning
    # information" gives pin1=A1, pin2=K2, pin3=K1;A2 (shared cathode/anode
    # junction). KiCad's own Diode:BAT54S library symbol matches exactly
    # (pin1 "A", pin2 "K", pin3 "COM"; description "dual schottky ... in
    # series") and already defaults to Footprint Package_TO_SOT_SMD:SOT-23.
    # BAT54C (common-cathode) and BAT54A (common-anode) are NOT this part -
    # neither gives a series pair, per the notes.
    #
    # The series pair's shared pin (COM, pin 3) IS the pump node: tying
    # pin1(A1) to GND and pin2(K2) to WDT_HOLD makes the two internal diodes
    # exactly the clamp diode (GND -> pump, conducts when the AC-coupled
    # node swings below GND) and the rectifier diode (pump -> hold cap,
    # conducts when the node swings above WDT_HOLD) that a diode-capacitor
    # charge pump needs - one part, no extra net.
    #
    # Designators: the brief's D6/D7/C33/C34/R41 collide with Task 10 (D6 =
    # CT TVS array, C33/C34 = ADE7953 decoupling) and Task 11 (R41 = touch
    # damping resistor). Confirmed free before use (next free at the time:
    # R46, C38, D7, Q3, SJ2 - see task report for the confirmation command).
    #
    # --- Values: brief's 100nF/1uF/1M were estimates; REV-B-NOTES.md SS8
    # verifies the diode Vf/gate-margin arithmetic but does not specify a
    # C38/C39/R46 sizing (no target kick frequency or hold-decay spec exists
    # yet). ASSUMPTION, flagged in the task report: kept at the brief's
    # values, which are reasonable for a multi-Hz-to-kHz kick square wave -
    # C38 100nF couples strongly at any plausible kick rate; R46 1M / C39
    # 1uF gives a ~1s RC decay (see below), fast enough that a wedged
    # firmware drops the SSRs well within a human's reaction time, slow
    # enough not to force an unreasonably fast kick task.
    #
    # Gate margin (REV-B-NOTES.md SS8d, at the ESP32's *guaranteed* V_OH
    # min of 0.8*VDD = 2.64V, not the optimistic 3.3V case, and BAT54S max
    # Vf @ 0.1mA = 240mV, the pump's actual current regime - NOT the 800mV
    # @ 100mA figure): V_gate = 2.64 - 2*0.240 = 2.16V against AO3400A
    # Vgs(th) max 1.45V -> margin = +0.71V. POSITIVE, so Q3 turns on; this
    # is not a blocker. BUT 2.16V is below the 2.5V point at which the
    # AO3400A's datasheet guarantees ANY Rds(on) (48mOhm max is only
    # specified at Vgs=2.5V/Id=3A). Do NOT size any load on this watchdog
    # gate assuming a guaranteed on-resistance in that worst-case corner -
    # it is a logic-level gate here (SSR_EN return path only, no significant
    # current), not a power switch, and that is what keeps this corner from
    # mattering. If a guaranteed 2.5V spec point in every corner is wanted,
    # a lower-Vf Schottky or a single-diode topology buys the ~0.35V needed
    # (REV-B-NOTES.md SS8, "corner worth knowing") - not changed here per
    # the task instructions; flagged in the report instead.
    #
    # Decay arithmetic: tau = R46 * C39 = 1MOhm * 1uF = 1.0s. WDT_HOLD decays
    # from its charged level toward 0V with that time constant once kicking
    # stops; it crosses Q3's worst-case Vgs(th) (1.45V, starting from the
    # ~2.16-2.98V range computed above) well under one tau, consistent with
    # the brief's ~0.5-1s figure.
    "C38": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(52.0, 49.5, 0),
                pins={"1": "WDT_KICK", "2": "WDT_PUMP"}),
    "D7": dict(lib="Diode", sym="BAT54S", fp=SOT23[0], fpf=SOT23[1],
               value="BAT54S", at=(57.0, 49.7, 0),
               pins={"1": "GND", "2": "WDT_HOLD", "3": "WDT_PUMP"}),
    "C39": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="1uF", at=(52.0, 53.5, 0),
                pins={"1": "WDT_HOLD", "2": "GND"}),
    "R46": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1M", at=(57.0, 53.5, 0),
                pins={"1": "WDT_HOLD", "2": "GND"}),
    "Q3": dict(lib="Transistor_FET", sym="AO3400A", fp=SOT23[0], fpf=SOT23[1],
               value="AO3400A", at=(52.0, 57.5, 0),
               pins={"1": "WDT_HOLD", "2": "GND", "3": "SSR_EN"}),
    # Bring-up defeat: shorts SSR_EN straight to GND (through Q3's own
    # source net), bypassing the watchdog gate entirely so the SSRs work
    # before the firmware kick task exists. Silkscreened "WDT DEFEAT" - see
    # gen_pcb.py SILK. MUST be removed (left open) in service - this is a
    # foot-gun by design, not a normal-operation jumper.
    "SJ2": dict(lib="Jumper", sym="SolderJumper_2_Open",
                fp="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
                fpf="SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm.kicad_mod",
                value="WDT_DEFEAT", at=(57.0, 57.5, 0),
                pins={"1": "SSR_EN", "2": "GND"}),
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
               value="ULN2003A", at=(39.0, 55.0, 180),
               pins={"1": "AUX1", "2": "AUX2", "3": "AUX3",
                     "4": None, "5": None, "6": None, "7": None,
                     "8": "GND", "9": "AUX_VP",
                     "10": None, "11": None, "12": None, "13": None,
                     "14": "AUX3_OUT", "15": "AUX2_OUT", "16": "AUX1_OUT"}),
    "R23": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(46.0, 61.0, 0),
                pins={"1": "AUX1", "2": "GND"}),
    "R24": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(46.0, 58.0, 0),
                pins={"1": "AUX2", "2": "GND"}),
    "R25": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(46.0, 54.5, 0),
                pins={"1": "AUX3", "2": "GND"}),
    # 4-position terminal: coil rail + three switched low sides.
    "J10": dict(lib="Connector", sym="Screw_Terminal_01x04",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                fpf="TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal.kicad_mod",
                value="AUX", at=(26.0, 52.0, 270),
                pins={"1": "AUX_VP", "2": "AUX1_OUT",
                      "3": "AUX2_OUT", "4": "AUX3_OUT"}),
    # Solder link: AUX_VP <- +5V for 5V relay coils. Open by default.
    "SJ1": dict(lib="Jumper", sym="SolderJumper_2_Open",
                fp="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
                fpf="SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm.kicad_mod",
                value="AUX_VP=5V", at=(46.0, 49.5, 0),
                pins={"1": "+5V", "2": "AUX_VP"}),
    # --- Buzzer ----------------------------------------------------------
    "BZ1": dict(lib="Device", sym="Buzzer",
                fp="Buzzer_Beeper:Buzzer_12x9.5RM7.6",
                fpf="Buzzer_12x9.5RM7.6.kicad_mod",
                value="active 5V", at=(41.0, 68.45, 0),
                pins={"1": "+5V", "2": "BUZZ_K"}),
    "D4": dict(lib="Device", sym="D", fp="Diode_SMD:D_SOD-123",
               fpf="D_SOD-123.kicad_mod", value="1N4148W", at=(65.0, 66.0, 0),
               pins={"1": "+5V", "2": "BUZZ_K"}),
    "Q2": dict(lib="Transistor_FET", sym="AO3400A", fp=SOT23[0], fpf=SOT23[1],
               value="AO3400A", at=(65.0, 70.0, 0),
               pins={"1": "BUZZ_GATE", "2": "GND", "3": "BUZZ_K"}),
    "R11": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="100R", at=(65.0, 74.0, 0),
                pins={"1": "ALARM", "2": "BUZZ_GATE"}),
    "R8": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="10k", at=(65.0, 78.0, 0),
               pins={"1": "BUZZ_GATE", "2": "GND"}),
    # --- WS2812B status LED ---------------------------------------------
    "LED1": dict(lib="LED", sym="WS2812B",
                 fp="LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
                 fpf="LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm.kicad_mod",
                 value="WS2812B", at=(97.7, 96.8, 0),
                 pins={"1": "VLED", "2": None, "3": "GND", "4": "WS_DIN"}),
    "R3": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
               value="330R", at=(91.0, 96.8, 0),
               pins={"1": "LED_DATA", "2": "WS_DIN"}),
    "D3": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS14", at=(105.15, 96.8, 0),
               pins={"1": "VLED", "2": "+5V"}),
    "C10": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(110.65, 96.5, 0),
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
    "R12": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(35.0, 111.0, 180),
                pins={"1": "IN1_RAW", "2": "IN1"}),
    "R13": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(40.0, 111.0, 0),
                pins={"1": "+3V3", "2": "IN1"}),
    "C12": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(45.0, 111.0, 0),
                pins={"1": "IN1", "2": "GND"}),
    "R26": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(50.0, 111.0, 180),
                pins={"1": "IN2_RAW", "2": "IN2"}),
    "R27": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(55.0, 111.0, 0),
                pins={"1": "+3V3", "2": "IN2"}),
    "C23": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(35.0, 115.0, 0),
                pins={"1": "IN2", "2": "GND"}),
    "R28": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(40.0, 115.0, 180),
                pins={"1": "IN3_RAW", "2": "IN3"}),
    "R29": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(45.0, 115.0, 0),
                pins={"1": "+3V3", "2": "IN3"}),
    "C24": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(50.0, 115.0, 0),
                pins={"1": "IN3", "2": "GND"}),
    # SRV05-4: 1 IO1, 2 VN(GND), 3 IO2, 4 IO3, 5 VP(+3V3), 6 IO4 (spare).
    "D5": dict(lib="Power_Protection", sym="SRV05-4",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="SRV05-4", at=(56.0, 115.0, 0),
               pins={"1": "IN1_RAW", "2": "GND", "3": "IN2_RAW",
                     "4": "IN3_RAW", "5": "+3V3", "6": None}),
    "J11": dict(lib="Connector", sym="Screw_Terminal_01x04",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                fpf="TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal.kicad_mod",
                value="INPUTS", at=(64.0, 114.0, 0),
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
               value="ADE7953ACPZ", at=(95.0, 72.0, 0),
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
               value="3.579545MHz", at=(113.0, 71.2, 0),
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
    "C25": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="30pF", at=(107.0, 65.5, 0),
                pins={"1": "ADE_CLKIN", "2": "GND"}),
    "C26": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="30pF", at=(119.0, 65.5, 0),
                pins={"1": "ADE_CLKOUT", "2": "GND"}),
    # ~RESET (pin 2): REV-B-NOTES.md SS4 - Figure 35's Test Circuit shows a
    # 10k pull-up to 3.3V with a 1uF cap to ground for a power-on reset
    # stretch (Figure 78's application circuit shows nothing on this pin -
    # it's application-dependent). Datasheet minimum low pulse is 10us; a
    # software reset and the datasheet's own reset interrupt are both
    # available if this network is omitted, but the stretch is cheap.
    "R30": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(104.0, 60.0, 0),
                pins={"1": "+3V3", "2": "ADE_RESET"}),
    "C37": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="1uF", at=(109.0, 60.0, 0),
                pins={"1": "ADE_RESET", "2": "GND"}),
    # SCLK / ~CS interface-select pull-ups - see the strapping note above.
    "R37": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(114.0, 60.0, 0),
                pins={"1": "+3V3", "2": "ADE_SCLK"}),
    "R38": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="10k", at=(119.0, 60.0, 0),
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
    "C27": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="4.7uF", at=(104.0, 75.8, 0),
                pins={"1": "ADE_VINTA", "2": "GND"}),
    "C28": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(109.0, 75.8, 0),
                pins={"1": "ADE_VINTA", "2": "GND"}),
    "C29": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="4.7uF", at=(88.2, 70.0, 0),
                pins={"1": "ADE_VINTD", "2": "GND"}),
    "C30": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(88.2, 73.5, 0),
                pins={"1": "ADE_VINTD", "2": "GND"}),
    "C33": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="4.7uF", at=(92.0, 79.5, 0),
                pins={"1": "ADE_REF", "2": "GND"}),
    "C34": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(97.5, 79.5, 0),
                pins={"1": "ADE_REF", "2": "GND"}),
    "C35": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="10uF", at=(114.0, 75.8, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "C36": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="100nF", at=(119.0, 75.8, 0),
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
    "R31": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="6R8", at=(95.0, 84.0, 0),
                pins={"1": "CTA_P", "2": "CTA_N"}),
    "R32": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(89.0, 84.0, 180),
                pins={"1": "CTA_P", "2": "CTA_F"}),
    "R33": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(100.25, 84.0, 0),
                pins={"1": "CTA_N", "2": "GND"}),
    "C31": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="33nF", at=(107.75, 84.0, 0),
                pins={"1": "CTA_F", "2": "GND"}),
    # Channel B - exact copy of channel A above, 6mm south.
    "R34": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="6R8", at=(95.0, 90.0, 0),
                pins={"1": "CTB_P", "2": "CTB_N"}),
    "R35": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(89.0, 90.0, 180),
                pins={"1": "CTB_P", "2": "CTB_F"}),
    "R36": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="1k", at=(101.0, 90.0, 0),
                pins={"1": "CTB_N", "2": "GND"}),
    "C32": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="33nF", at=(107.0, 90.0, 0),
                pins={"1": "CTB_F", "2": "GND"}),
    # Spec SS5.5's second SRV05-4 (the first, D5, covers the dry-contact
    # inputs). NOT on the thermocouple inputs - array leakage into a
    # ~40uV/degC source is an accuracy error, not protection. SRV05-4
    # pinout matches D5's: 1 IO1, 2 GND, 3 IO2, 4 IO3, 5 VP(+3V3), 6 IO4.
    "D6": dict(lib="Power_Protection", sym="SRV05-4",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="SRV05-4", at=(113.0, 84.0, 0),
               pins={"1": "CTA_P", "2": "GND", "3": "CTA_N",
                     "4": "CTB_P", "5": "+3V3", "6": "CTB_N"}),
    "J12": dict(lib="Connector", sym="Screw_Terminal_01x04",
                fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal",
                fpf="TerminalBlock_Phoenix_MKDS-1,5-4-5.08_1x04_P5.08mm_Horizontal.kicad_mod",
                value="CT", at=(139.0, 92.0, 90),
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
                value="AC_SENSE_DNP", at=(104.0, 80.5, 0),
                pins={"1": "ADE_VP", "2": "ADE_VN"}),
    # --- Headers ---------------------------------------------------------
    "J5": dict(lib="Connector_Generic", sym="Conn_01x14",
               fp="Connector_Molex:Molex_KK-254_AE-6410-14A_1x14_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-14A_1x14_P2.54mm_Vertical.kicad_mod",
               value="DISPLAY", at=(24.0, 104.0, 0),
               # LCDWIKI 4.0" MSP4021 (ST7796S + XPT2046 touch), grown from
               # rev A's 8-pin display-only header (Task 11). Pins 1-8 keep
               # rev A's assignment (see below); 9 is the panel's SDO (rev A
               # left it unwired - the firmware never read from the
               # display); 10-14 are the touch panel. The XPT2046 lives on
               # the display module, not this board - T_CLK/T_DIN/T_DO ARE
               # the shared SPI2 bus (SPI_SCLK/SPI_MOSI/SPI_MISO), so only
               # T_CS and T_IRQ cost new GPIOs (Task 3). R39-R43 damp a bus
               # that now multi-drops four devices (LCD, TC1, TC2, touch)
               # at 40 MHz.
               #
               # VCC accepts 3.3-5V per the module's own manual, and every
               # reference wiring diagram in it (incl. 3.3V-logic STM32
               # boards) ties VCC to 5V while driving CS/RESET/DC/MOSI/SCK
               # directly from 3.3V GPIOs with no level shifter - so +5V
               # here needs no other board change. Moving off +3V3 also
               # takes the backlight/panel current off the AMS1117 (U2)
               # entirely rather than through its LDO drop.
               pins={"1": "+5V", "2": "GND", "3": "LCD_CS", "4": "LCD_RST",
                     "5": "LCD_DC", "6": "SPI_MOSI", "7": "SPI_SCLK",
                     "8": "LCD_BL", "9": "SPI_MISO", "10": "T_CLK_R",
                     "11": "T_CS_R", "12": "T_DIN_R", "13": "T_DO_R",
                     "14": "T_IRQ_R"}),
    "C11": dict(lib="Device", sym="C", fp=C0603[0], fpf=C0603[1],
                value="10uF", at=(43.0, 96.65, 0),
                pins={"1": "+5V", "2": "GND"}),
    # --- Touch series damping (Task 11) -----------------------------------
    # T_CLK/T_DIN/T_DO are the shared SPI2 bus; T_CS/T_IRQ are dedicated
    # GPIOs (Task 3). All five get 33R series damping since the bus now
    # multi-drops four devices at 40 MHz.
    "R39": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="33", at=(47.0, 96.55, 0),
                pins={"1": "SPI_SCLK", "2": "T_CLK_R"}),
    "R40": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="33", at=(50.5, 96.5, 0),
                pins={"1": "T_CS", "2": "T_CS_R"}),
    "R41": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="33", at=(54.0, 96.5, 0),
                pins={"1": "SPI_MOSI", "2": "T_DIN_R"}),
    "R42": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="33", at=(57.5, 96.5, 0),
                pins={"1": "SPI_MISO", "2": "T_DO_R"}),
    "R43": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="33", at=(61.0, 96.5, 0),
                pins={"1": "T_IRQ", "2": "T_IRQ_R"}),
    "J6": dict(lib="Connector_Generic", sym="Conn_01x06",
               fp="Connector_Molex:Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical.kicad_mod",
               value="NAV_SW", at=(62.0, 104.0, 0),
               pins={"1": "BTN_UP", "2": "BTN_DOWN", "3": "BTN_LEFT",
                     "4": "BTN_RIGHT", "5": "BTN_SEL", "6": "GND"}),
    "J7": dict(lib="Connector_Generic", sym="Conn_01x08",
               fp="Connector_Molex:Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical.kicad_mod",
               value="AUX", at=(80.0, 104.0, 0),
               # pin 6 carried the raw lid-switch input in rev A; the lid
               # moved to its own terminal (J11) in Task 9. Pins 5-8 carried
               # VENT/(unconnected)/AUX_A/AUX_B through Task 10 - all
               # dangling single-pin nets, nothing on the board actually
               # drove them (the real VENT output is AUX1, on U6). Task 11
               # re-points 5-8 to I2C, giving the bus a 0.1" tap alongside
               # the Qwiic connector (J14) and finally retiring AUX_A/AUX_B.
               pins={"1": "+3V3", "2": "GND", "3": "TXD0", "4": "RXD0",
                     "5": "I2C_SDA", "6": "I2C_SCL", "7": "+3V3", "8": "GND"}),
    # --- I2C expansion (Task 11) ------------------------------------------
    "J14": dict(lib="Connector_Generic", sym="Conn_01x04",
                fp="Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
                fpf="JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal.kicad_mod",
                value="QWIIC", at=(84.9, 96.8, 0),
                pins={"1": "GND", "2": "+3V3", "3": "I2C_SDA", "4": "I2C_SCL"}),
    "R44": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="4.7k", at=(75.55, 96.5, 0),
                pins={"1": "+3V3", "2": "I2C_SDA"}),
    "R45": dict(lib="Device", sym="R", fp=R0603[0], fpf=R0603[1],
                value="4.7k", at=(79.05, 96.5, 0),
                pins={"1": "+3V3", "2": "I2C_SCL"}),
    # --- Mounting holes (grounded) --------------------------------------
    "H1": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(25.5, 25.0, 0), pins={"1": "GND"}),
    "H2": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(140.5, 25.0, 0), pins={"1": "GND"}),
    "H3": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(25.5, 115.0, 0), pins={"1": "GND"}),
    "H4": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(140.5, 115.0, 0), pins={"1": "GND"}),
    # --- Test points (bring-up) ------------------------------------------
    # 1 mm pads, no BOM cost, no assembly cost.
    "TP1": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(33.2, 28.6, 0),
                pins={"1": "+3V3"}),
    "TP2": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(36.5, 28.6, 0),
                pins={"1": "+5V"}),
    "TP3": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(39.8, 28.6, 0),
                pins={"1": "GND"}),
    "TP4": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(63.0, 57.0, 0),
                pins={"1": "SPI_MOSI"}),
    "TP5": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(68.0, 57.0, 0),
                pins={"1": "SPI_SCLK"}),
    "TP6": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(73.0, 57.0, 0),
                pins={"1": "SPI_MISO"}),
    "TP7": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(78.0, 57.0, 0),
                pins={"1": "I2C_SDA"}),
    "TP8": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(83.0, 61.5, 0),
                pins={"1": "I2C_SCL"}),
    "TP9": dict(lib="Connector", sym="TestPoint",
                fp="TestPoint:TestPoint_Pad_D1.0mm",
                fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                value="TP", at=(58.5, 80.5, 0),
                pins={"1": "SSR1_CTRL"}),
    "TP10": dict(lib="Connector", sym="TestPoint",
                 fp="TestPoint:TestPoint_Pad_D1.0mm",
                 fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                 value="TP", at=(44.5, 94.3, 0),
                 pins={"1": "SSR2_CTRL"}),
    "TP11": dict(lib="Connector", sym="TestPoint",
                 fp="TestPoint:TestPoint_Pad_D1.0mm",
                 fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                 value="TP", at=(113.0, 90.0, 0),
                 pins={"1": "CTA_P"}),
    "TP12": dict(lib="Connector", sym="TestPoint",
                 fp="TestPoint:TestPoint_Pad_D1.0mm",
                 fpf="TestPoint_Pad_D1.0mm.kicad_mod",
                 value="TP", at=(52.0, 60.7, 0),
                 pins={"1": "WDT_HOLD"}),
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
