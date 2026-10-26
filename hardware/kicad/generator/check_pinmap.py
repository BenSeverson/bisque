#!/usr/bin/env python3
"""Assert the GPIO map agrees across the three places allowed to state it.

The schematic (via the committed netlist, bisque-controller.net) owns which
GPIO the board wires to each net; main/Kconfig.projbuild owns each pin's
firmware default; docs/pin-assignments.md §1 is the one table written for
people. Nothing else in the repo restates a GPIO number. This checks all three
against each other, so a re-map that updates one and forgets another fails
loudly instead of reaching a fab house - or a reader.

Module pin number -> GPIO for ESP32-S3-WROOM-1 / -1U (identical pinout).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import netlist as NL

NETLIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                       "bisque-controller.net")

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
KCONFIG = os.path.join(REPO, "main", "Kconfig.projbuild")
PIN_DOC = os.path.join(REPO, "docs", "pin-assignments.md")

# U1 module pin -> GPIO number. From the ESP32-S3-WROOM-1 datasheet pad list;
# the 1U is identical. Pins carrying power, EN or GND are absent.
MODULE_PIN_GPIO = {
    4: 4, 5: 5, 6: 6, 7: 7, 8: 15, 9: 16, 10: 17, 11: 18, 12: 8,
    13: 19, 14: 20, 15: 3, 16: 46, 17: 9, 18: 10, 19: 11, 20: 12,
    21: 13, 22: 14, 23: 21, 24: 47, 25: 48, 26: 45, 27: 0,
    28: 35, 29: 36, 30: 37, 31: 38, 32: 39, 33: 40, 34: 41, 35: 42,
    36: 44, 37: 43, 38: 2, 39: 1,
}

# Nets on U1 that are fixed-function and correctly have NO Kconfig pin symbol:
# the native USB peripheral (GPIO 19/20), the UART0 console (GPIO 43/44) and
# the BOOT strapping pin (GPIO 0). These must never count as unmapped.
NO_KCONFIG_SYMBOL = {"USB_DN", "USB_DP", "TXD0", "RXD0", "IO0"}

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
    "ADE_RESET": "KILN_PIN_ADE_RESET",
    "PWR_STATUS": "KILN_PIN_PWR_STATUS",
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


def u1_pins():
    """{module pin: net or None} for U1, from the committed netlist."""
    return {int(pin): net for pin, net in NL.load(NETLIST).comps["U1"]["pins"].items()}


def board_gpios():
    """{net: gpio} for every U1 pin that carries a mapped signal."""
    out = {}
    for pin, net in u1_pins().items():
        gpio = MODULE_PIN_GPIO.get(pin)
        if net is not None and gpio is not None:
            out[net] = gpio
    return out


def doc_rows(path):
    """[(gpio, module pin, net or None, kconfig symbol or None, line)] from the
    first table in docs/pin-assignments.md whose header starts `| GPIO | Module pin |`."""
    rows, in_table = [], False
    for line in open(path, encoding="utf-8"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not in_table:
            in_table = cells[:2] == ["GPIO", "Module pin"]
            continue
        if not line.startswith("|"):
            break
        if set(cells[0]) <= set("-: "):
            continue
        dash = lambda c: None if c in ("—", "-", "") else c.strip("`")
        rows.append((int(cells[0]), int(cells[1]), dash(cells[3]), dash(cells[5]),
                     line.rstrip()))
    return rows


def check_doc(path, pins):
    """Errors where docs/pin-assignments.md §1 disagrees with the netlist or NET_KCONFIG."""
    errors, seen = [], set()
    rows = doc_rows(path)
    if not rows:
        return ["%s: no `| GPIO | Module pin |` table found" % path]
    for gpio, mpin, net, sym, line in rows:
        where = "%s GPIO %d" % (os.path.basename(path), gpio)
        if MODULE_PIN_GPIO.get(mpin) != gpio:
            errors.append("%s: module pin %d is GPIO %s, not %d"
                          % (where, mpin, MODULE_PIN_GPIO.get(mpin), gpio))
        if pins.get(mpin) != net:
            errors.append("%s: table says net %s, the schematic wires U1 pin %d to %s"
                          % (where, net, mpin, pins.get(mpin)))
        want = NET_KCONFIG.get(net)
        if sym != want:
            errors.append("%s: table names Kconfig %s for net %s, expected %s"
                          % (where, sym, net, want))
        seen.add(mpin)
    missing = sorted(p for p, g in MODULE_PIN_GPIO.items() if p not in seen)
    if missing:
        errors.append("%s: no row for U1 pin(s) %s"
                      % (os.path.basename(path), ", ".join(map(str, missing))))
    return errors


def main():
    defaults = kconfig_defaults(KCONFIG)
    board = board_gpios()
    errors = []

    for net, sym in NET_KCONFIG.items():
        on_board = board.get(net)
        in_kconfig = defaults.get(sym)
        if on_board is None:
            errors.append("net %s is in NET_KCONFIG but not on U1 in the schematic" % net)
        elif in_kconfig is None:
            errors.append("%s has no integer default in Kconfig.projbuild" % sym)
        elif on_board != in_kconfig:
            errors.append("%s: Kconfig says GPIO %d, the schematic wires net %s to GPIO %d"
                          % (sym, in_kconfig, net, on_board))

    unmapped = sorted(set(board) - set(NET_KCONFIG) - NO_KCONFIG_SYMBOL)
    if unmapped:
        errors.append("U1 nets with no Kconfig symbol: %s" % ", ".join(unmapped))

    errors += check_doc(PIN_DOC, u1_pins())

    if errors:
        for e in errors:
            print("FAIL: %s" % e)
        return 1
    print("check_pinmap: %d GPIO assignments agree between Kconfig, the schematic "
          "and docs/pin-assignments.md" % len(NET_KCONFIG))
    return 0


if __name__ == "__main__":
    sys.exit(main())
