"""Bisque kiln controller PCB — single source of truth.

Components, pin->net connectivity, and PCB placement. Both the schematic and
board generators derive everything from these tables, so the two files can
never disagree on connectivity.

Pin GPIO mapping mirrors main/Kconfig.projbuild defaults (the firmware's
source of truth):
  SPI: MOSI=11 MISO=13 SCLK=12 | TC CS=10 | SSR=17
  LCD: CS=8 DC=9 RST=46 BL=3   | WS2812=48 | ALARM=7
  BTN: UP=4 DOWN=5 SEL=1 LEFT=6 RIGHT=2
"""

# --- board outline (mm, page coords) ---
BX0, BY0, BX1, BY1 = 20.0, 20.0, 120.0, 100.0   # 100 x 80 mm

# net name -> netclass ("signal" default)
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
               fp="RF_Module:ESP32-S3-WROOM-1", fpf="ESP32-S3-WROOM-1.kicad_mod",
               value="ESP32-S3-WROOM-1-N16R8", at=(88.0, 33.0, 0),
               pins={"1": "GND", "2": "+3V3", "3": "EN", "4": "BTN_UP",
                     "5": "BTN_DOWN", "6": "BTN_LEFT", "7": "ALARM",
                     "8": "AUX_A", "9": "AUX_B", "10": "SSR_CTRL",
                     "11": None, "12": "LCD_CS", "13": "USB_DN",
                     "14": "USB_DP", "15": "LCD_BL", "16": "LCD_RST",
                     "17": "LCD_DC", "18": "TC_CS", "19": "SPI_MOSI",
                     "20": "SPI_SCLK", "21": "SPI_MISO", "22": "VENT",
                     "23": "LID_SW", "24": None, "25": "LED_DATA",
                     "26": None, "27": "IO0", "28": None, "29": None,
                     "30": None, "31": None, "32": None, "33": None,
                     "34": None, "35": None, "36": "RXD0", "37": "TXD0",
                     "38": "BTN_RIGHT", "39": "BTN_SEL", "40": "GND",
                     "41": "GND"}),
    # --- Power -----------------------------------------------------------
    "J2": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="5V_IN", at=(27.0, 33.0, 270),
               pins={"1": "VIN", "2": "GND"}),
    "D1": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS34", at=(38.0, 28.0, 180),
               pins={"1": "+5V", "2": "VIN"}),
    "D2": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS34", at=(95.5, 86.0, 270),
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
    "C5": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="1uF", at=(68.0, 28.7, 0),
               pins={"1": "EN", "2": "GND"}),
    "R2": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(103.4, 35.0, 270),
               pins={"1": "+3V3", "2": "IO0"}),
    "SW1": dict(lib="Switch", sym="SW_Push",
                fp="Button_Switch_THT:SW_PUSH_6mm", fpf="SW_PUSH_6mm.kicad_mod",
                value="RESET", at=(55.0, 22.5, 0),
                pins={"1": "EN", "2": "GND"}),
    "SW2": dict(lib="Switch", sym="SW_Push",
                fp="Button_Switch_THT:SW_PUSH_6mm", fpf="SW_PUSH_6mm.kicad_mod",
                value="BOOT", at=(101.0, 47.0, 0),
                pins={"1": "IO0", "2": "GND"}),
    # --- USB -------------------------------------------------------------
    "J1": dict(lib="Connector", sym="USB_C_Receptacle_USB2.0_16P",
               fp="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
               fpf="USB_C_Receptacle_HRO_TYPE-C-31-M-12.kicad_mod",
               value="USB-C", at=(89.0, 95.6, 0),
               pins={"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
                     "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
                     "A5": "CC1", "B5": "CC2",
                     "A6": "USB_DP", "B6": "USB_DP",
                     "A7": "USB_DN", "B7": "USB_DN",
                     "A8": None, "B8": None, "S1": "GND"}),
    "R4": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="5.1k", at=(84.0, 88.0, 90),
               pins={"1": "CC1", "2": "GND"}),
    "R5": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="5.1k", at=(96.5, 97.9, 0),
               pins={"1": "CC2", "2": "GND"}),
    "U4": dict(lib="Power_Protection", sym="USBLC6-2SC6",
               fp="Package_TO_SOT_SMD:SOT-23-6", fpf="SOT-23-6.kicad_mod",
               value="USBLC6-2SC6", at=(89.0, 82.0, 90),
               pins={"1": "USB_DN", "6": "USB_DN",
                     "3": "USB_DP", "4": "USB_DP",
                     "5": "VBUS", "2": "GND"}),
    # --- Thermocouple ----------------------------------------------------
    "U3": dict(lib="Sensor_Temperature", sym="MAX31855KASA",
               fp="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
               fpf="SOIC-8_3.9x4.9mm_P1.27mm.kicad_mod",
               value="MAX31855KASA+", at=(104.5, 62.0, 90),
               pins={"1": "GND", "2": "GND", "3": "TC_P", "4": "+3V3",
                     "5": "SPI_SCLK", "6": "TC_CS", "7": "SPI_MISO",
                     "8": None}),
    "J3": dict(lib="Connector", sym="Screw_Terminal_01x02",
               fp=TBLOCK[0], fpf=TBLOCK[1], value="TC_K", at=(114.0, 65.0, 90),
               pins={"1": "TC_P", "2": "GND"}),
    "C8": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="100nF", at=(100.3, 62.0, 90),
               pins={"1": "+3V3", "2": "GND"}),
    "C9": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
               value="10nF", at=(105.3, 67.5, 0),
               pins={"1": "TC_P", "2": "GND"}),
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
                value="active 5V", at=(38.0, 78.0, 0),
                pins={"1": "+5V", "2": "BUZZ_K"}),
    "D4": dict(lib="Device", sym="D", fp="Diode_SMD:D_SOD-123",
               fpf="D_SOD-123.kicad_mod", value="1N4148W", at=(49.5, 84.0, 0),
               pins={"1": "+5V", "2": "BUZZ_K"}),
    "Q2": dict(lib="Transistor_FET", sym="AO3400A", fp=SOT23[0], fpf=SOT23[1],
               value="AO3400A", at=(58.0, 80.0, 0),
               pins={"1": "BUZZ_GATE", "2": "GND", "3": "BUZZ_K"}),
    "R11": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
                value="100R", at=(58.8, 74.0, 0),
                pins={"1": "ALARM", "2": "BUZZ_GATE"}),
    "R8": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="10k", at=(62.0, 77.5, 90),
               pins={"1": "BUZZ_GATE", "2": "GND"}),
    # --- WS2812B status LED ---------------------------------------------
    "LED1": dict(lib="LED", sym="WS2812B",
                 fp="LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm",
                 fpf="LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm.kicad_mod",
                 value="WS2812B", at=(75.0, 86.0, 0),
                 pins={"1": "VLED", "2": None, "3": "GND", "4": "WS_DIN"}),
    "R3": dict(lib="Device", sym="R", fp=R0805[0], fpf=R0805[1],
               value="330R", at=(82.0, 84.35, 180),
               pins={"1": "LED_DATA", "2": "WS_DIN"}),
    "D3": dict(lib="Device", sym="D_Schottky", fp=SMA[0], fpf=SMA[1],
               value="SS14", at=(72.55, 79.5, 90),
               pins={"1": "VLED", "2": "+5V"}),
    "C10": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="100nF", at=(69.0, 81.5, 0),
                pins={"1": "VLED", "2": "GND"}),
    # --- Headers ---------------------------------------------------------
    "J5": dict(lib="Connector_Generic", sym="Conn_01x08",
               fp="Connector_Molex:Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical.kicad_mod",
               value="DISPLAY", at=(24.5, 95.0, 0),
               pins={"1": "+3V3", "2": "GND", "3": "LCD_CS", "4": "LCD_RST",
                     "5": "LCD_DC", "6": "SPI_MOSI", "7": "SPI_SCLK",
                     "8": "LCD_BL"}),
    "C12": dict(lib="Device", sym="C", fp=C0805[0], fpf=C0805[1],
                value="10uF", at=(26.5, 90.5, 0),
                pins={"1": "+3V3", "2": "GND"}),
    "J6": dict(lib="Connector_Generic", sym="Conn_01x06",
               fp="Connector_Molex:Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-06A_1x06_P2.54mm_Vertical.kicad_mod",
               value="NAV_SW", at=(46.0, 95.0, 0),
               pins={"1": "BTN_UP", "2": "BTN_DOWN", "3": "BTN_LEFT",
                     "4": "BTN_RIGHT", "5": "BTN_SEL", "6": "GND"}),
    "J7": dict(lib="Connector_Generic", sym="Conn_01x08",
               fp="Connector_Molex:Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical",
               fpf="Molex_KK-254_AE-6410-08A_1x08_P2.54mm_Vertical.kicad_mod",
               value="AUX", at=(64.0, 95.0, 0),
               pins={"1": "+3V3", "2": "GND", "3": "TXD0", "4": "RXD0",
                     "5": "VENT", "6": "LID_SW", "7": "AUX_A", "8": "AUX_B"}),
    # --- Mounting holes (grounded) --------------------------------------
    "H1": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(24.5, 24.5, 0), pins={"1": "GND"}),
    "H2": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(115.5, 24.5, 0), pins={"1": "GND"}),
    "H3": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(24.5, 68.0, 0), pins={"1": "GND"}),
    "H4": dict(lib="Mechanical", sym="MountingHole_Pad",
               fp="MountingHole:MountingHole_3.2mm_M3_Pad_Via",
               fpf="MountingHole_3.2mm_M3_Pad_Via.kicad_mod",
               value="M3", at=(115.5, 95.5, 0), pins={"1": "GND"}),
}

# power flag symbols (schematic only): net -> flag
PWR_FLAG_NETS = ["GND", "+5V", "VBUS", "VIN", "VLED"]


def netlist():
    """net -> [(ref, pin), ...]"""
    nets = {}
    for ref, c in COMPONENTS.items():
        for pin, net in c["pins"].items():
            if net is None:
                continue
            nets.setdefault(net, []).append((ref, pin))
    return nets


if __name__ == "__main__":
    nl = netlist()
    for net in sorted(nl):
        pins = nl[net]
        flag = "  !! single-pin" if len(pins) < 2 else ""
        print("%-10s %s%s" % (net, " ".join("%s.%s" % p for p in pins), flag))
