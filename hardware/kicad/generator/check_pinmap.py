#!/usr/bin/env python3
"""Assert design.py's U1 pin map agrees with main/Kconfig.projbuild defaults.

The GPIO assignment lives in three files that must agree and have drifted apart
before (see docs/pin-assignments.md). Kconfig is the firmware's source of truth;
design.py is the board's. This checks them against each other so a re-map that
updates one and forgets the other fails loudly instead of reaching a fab house.

Module pin number -> GPIO for ESP32-S3-WROOM-1 / -1U (identical pinout).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from design import COMPONENTS

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KCONFIG = os.path.join(REPO, "main", "Kconfig.projbuild")

# U1 module pin -> GPIO number. From the ESP32-S3-WROOM-1 datasheet pad list;
# the 1U is identical. Pins carrying power, EN or GND are absent.
MODULE_PIN_GPIO = {
    4: 4, 5: 5, 6: 6, 7: 7, 8: 15, 9: 16, 10: 17, 11: 18, 12: 8,
    13: 19, 14: 20, 15: 3, 16: 46, 17: 9, 18: 10, 19: 11, 20: 12,
    21: 13, 22: 14, 23: 21, 24: 47, 25: 48, 26: 45, 27: 0,
    28: 35, 29: 36, 30: 37, 31: 38, 32: 39, 33: 40, 34: 41, 35: 42,
    36: 44, 37: 43, 38: 2, 39: 1,
}

# net name -> Kconfig symbol that must hold that GPIO.
NET_KCONFIG = {
    "SPI_MOSI": "KILN_PIN_SPI_MOSI",
    "SPI_MISO": "KILN_PIN_SPI_MISO",
    "SPI_SCLK": "KILN_PIN_SPI_SCLK",
    "TC1_CS": "KILN_PIN_TC1_CS",
    "TC2_CS": "KILN_PIN_TC2_CS",
    "SSR1_CTRL": "KILN_PIN_SSR1",
    "SSR2_CTRL": "KILN_PIN_SSR2",
    "LCD_CS": "KILN_PIN_LCD_CS",
    "LCD_DC": "KILN_PIN_LCD_DC",
    "LCD_RST": "KILN_PIN_LCD_RST",
    "LCD_BL": "KILN_PIN_LCD_BL",
    "LED_DATA": "KILN_PIN_STATUS_LED",
    "ALARM": "KILN_PIN_ALARM",
    "AUX1": "KILN_PIN_VENT",
    "AUX2": "KILN_PIN_AUX2",
    "AUX3": "KILN_PIN_AUX3",
    "IN1": "KILN_PIN_LID_SWITCH",
    "IN2": "KILN_PIN_IN_GASFLOW",
    "IN3": "KILN_PIN_IN_SPARE",
    "I2C_SDA": "KILN_PIN_I2C_SDA",
    "I2C_SCL": "KILN_PIN_I2C_SCL",
    "T_CS": "KILN_PIN_TOUCH_CS",
    "T_IRQ": "KILN_PIN_TOUCH_IRQ",
    "WDT_KICK": "KILN_PIN_WDT_KICK",
    "BTN_UP": "KILN_PIN_BTN_UP",
    "BTN_DOWN": "KILN_PIN_BTN_DOWN",
    "BTN_LEFT": "KILN_PIN_BTN_LEFT",
    "BTN_RIGHT": "KILN_PIN_BTN_RIGHT",
    "BTN_SEL": "KILN_PIN_BTN_SELECT",
}


def kconfig_defaults(path):
    """{symbol: int default} for every `config X` / `default N` int option."""
    out, sym = {}, None
    for line in open(path):
        m = re.match(r"\s*config\s+(\w+)\s*$", line)
        if m:
            sym = m.group(1)
            continue
        m = re.match(r"\s*default\s+(-?\d+)\s*$", line)
        if m and sym:
            out.setdefault(sym, int(m.group(1)))
    return out


def board_gpios():
    """{net: gpio} for every U1 pin that carries a mapped signal."""
    out = {}
    for pin, net in COMPONENTS["U1"]["pins"].items():
        if net is None:
            continue
        gpio = MODULE_PIN_GPIO.get(int(pin))
        if gpio is not None:
            out[net] = gpio
    return out


def main():
    defaults = kconfig_defaults(KCONFIG)
    board = board_gpios()
    errors = []

    for net, sym in NET_KCONFIG.items():
        on_board = board.get(net)
        in_kconfig = defaults.get(sym)
        if on_board is None:
            errors.append("net %s is in NET_KCONFIG but not on U1 in design.py" % net)
        elif in_kconfig is None:
            errors.append("%s has no integer default in Kconfig.projbuild" % sym)
        elif on_board != in_kconfig:
            errors.append("%s: Kconfig says GPIO %d, design.py wires net %s to GPIO %d"
                          % (sym, in_kconfig, net, on_board))

    unmapped = sorted(set(board) - set(NET_KCONFIG) - {"IO0", "TXD0", "RXD0"})
    if unmapped:
        errors.append("U1 nets with no Kconfig symbol: %s" % ", ".join(unmapped))

    if errors:
        for e in errors:
            print("FAIL: %s" % e)
        return 1
    print("check_pinmap: %d GPIO assignments agree between Kconfig and design.py"
          % len(NET_KCONFIG))
    return 0


if __name__ == "__main__":
    sys.exit(main())
