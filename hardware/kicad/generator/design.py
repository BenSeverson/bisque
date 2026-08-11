"""Bisque kiln controller PCB — single source of truth.

Components, pin->net connectivity, and PCB placement. Both the schematic and
board generators derive everything from these tables, so the two files can
never disagree on connectivity.

Pin GPIO mapping mirrors main/Kconfig.projbuild defaults (the firmware's
source of truth):
  SPI: MOSI=11 MISO=13 SCLK=12 | TC CS=10 | SSR=17
  LCD: CS=8 DC=9 RST=46 BL=3   | WS2812=48 | ALARM=7
  BTN: UP=4 DOWN=5 SEL=1 LEFT=6 RIGHT=2
  J7:  VENT=14 LID_SW=21 AUX_A=15 AUX_B=16 | TXD0/RXD0 console

All four J7 signal nets are real copper here. VENT and LID_SW default to those
GPIOs in Kconfig to match this board; AUX_A/AUX_B are declared but not yet
driven by any code. Note that an enabled-but-unwired LID_SW reads open and
holds the SSR off — it needs a switch, a jumper to GND, or -1. The full
as-built map, the constraints behind it, and the planned expansion live in
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
    # --- SSR output ------------------------------------------------------
    "J4": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="SSR", at=(27.0, 55.0, 270),
               pins={"1": "+5V", "2": "SSR_OUT"}),
    "R6": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="100R", at=(46.0, 53.0, 180),
               pins={"1": "SSR_CTRL", "2": "SSR_GATE"}),
    "R7": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(41.0, 52.0, 90),
               pins={"1": "SSR_GATE", "2": "GND"}),
    "Q1": dict(lib="Transistor_FET", sym="AO3400A", fp=SOT23[0], fpf=SOT23[1],
               value="AO3400A", at=(42.0, 57.0, 0),
               pins={"1": "SSR_GATE", "2": "GND", "3": "SSR_OUT"}),
    "LED3": dict(lib="Device", sym="LED", fp=LED0805[0], fpf=LED0805[1],
                 value="amber", at=(33.0, 50.0, 270),
                 pins={"1": "LEDS_K", "2": "+5V"}),
    "R10": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="680R", at=(36.5, 50.0, 90),
                pins={"1": "SSR_OUT", "2": "LEDS_K"}),
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
    # --- Lid/door switch input conditioning -------------------------------
    # LID_SW (IO21) is the one GPIO input whose cable leaves the enclosure
    # and runs to a hot kiln lid, alongside the SSR output and mains wiring.
    # The nav switch (J6) is a short internal run and stays bare, but a
    # false "lid open" here cuts a firing, so the entry point gets an RC:
    #   J7.6 -> R12 (1k series) -> LID_SW -> U1.23,  R13 10k to +3V3,
    #   C12 100nF to GND.
    # R13 replaces the ESP32's weak ~45k internal pull-up with a stiff 10k,
    # so an open switch holds the node high against far more leakage and
    # capacitive pickup. R12 limits fault/ESD current into the pin, and C12
    # sees R12||R13 (~0.9k) with the switch closed - a ~1.8 kHz corner
    # (~90us), rising to ~160 Hz (10k x 100nF) with it open. Fast enough to
    # leave mechanical bounce to the firmware, which samples at 500 ms;
    # slow enough to swallow EMI transients.
    # Closed-switch level is 3.3V x 1k/11k = 0.30V, well under the ESP32's
    # 0.25 x VDD (0.83V) V_IL. No discrete TVS: the only one on the board is
    # the USBLC6 (U4), which is there for USB2.0's low-capacitance
    # requirement; the other externally-exposed nets (TC_P at J3, the nav
    # switch at J6) rely on an RC plus the pin's own clamp diodes, and a TVS
    # would add a unique Extended part ($3 feeder fee) for one input.
    #
    # Placement: R12 and C12 sit in the free band between LED1 and J7 so the
    # shunt is right where the cable enters. R13 is 6 mm further north, on
    # the +3V3 B.Cu trunk that runs diagonally down to J7.1 - it is a DC
    # pull-up, so its position is electrically irrelevant, and putting it
    # beside C12 forced a 0.7 mm-wide +3V3 spur across the F.Cu pour above
    # J7.1/J7.2, which starved J7.2's thermal relief (DRC error).
    "R12": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="1k", at=(87.3, 107.6, 180),
                pins={"1": "LID_IN", "2": "LID_SW"}),
    "R13": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="10k", at=(83.5, 101.5, 0),
                pins={"1": "+3V3", "2": "LID_SW"}),
    "C12": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(83.8, 107.6, 0),
                pins={"1": "LID_SW", "2": "GND"}),
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
                     # pin 6 is the raw lid-switch input: it reaches U1.23
                     # (LID_SW) through the R12/R13/C12 filter above, not
                     # directly. Wire a dry contact between J7.6 and J7.2
                     # (GND); closed = lid shut.
                     "5": "VENT", "6": "LID_IN", "7": "AUX_A", "8": "AUX_B"}),
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
