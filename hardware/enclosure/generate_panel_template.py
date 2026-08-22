#!/usr/bin/env python3
"""1:1 drill/cutout template for the enclosure door (SVG, mm units).

Emits ``door-template.svg`` next to this script: the door outline of the
baseline 16 x 12 x 6 in box (door 305 x 406 mm), the display window cutout,
the display module mounting holes, the 5-button nav cross, and the
controller PCB's 90 x 90 mm M3 grid, each with center crosshairs and a
dimension label. A 100 mm calibration ruler is drawn so a print can be
verified unscaled before drilling.

Stdlib only. Every dimension is a module-level constant; the display
module hole positions are nominal (clone MSP4021 modules vary) and are
labelled VERIFY on the drawing -- measure the module in hand, adjust
DISPLAY_HOLE_INSET / DISPLAY_HOLE_DIA, and re-run.
"""

from __future__ import annotations

import os

# --- Door (16 x 12 x 6 in wall-mount box, mounted 406 mm tall) -----------
DOOR_W = 305.0
DOOR_H = 406.0
CENTER_X = DOOR_W / 2  # everything is centered horizontally

# --- Display window (LCDWIKI MSP4021, landscape) -------------------------
# Active area 83.52 x 55.68 mm; the window reveals it with ~1 mm margin
# while staying inside the module glass.
WINDOW_W = 86.0
WINDOW_H = 58.0
WINDOW_CY = 110.0

# Module PCB is 108.04 x 61.74 mm (landscape). Nominal corner holes,
# inset from the PCB corners -- VERIFY against the physical module.
DISPLAY_PCB_W = 108.04
DISPLAY_PCB_H = 61.74
DISPLAY_HOLE_INSET = 2.5
DISPLAY_HOLE_DIA = 3.2

# --- Nav cross (five 12 mm panel-mount momentary buttons) ----------------
NAV_CY = 190.0
NAV_PITCH = 24.0
NAV_HOLE_DIA = 12.2

# --- Controller PCB (100 x 100 mm, M3 grid 90 x 90 mm) -------------------
PCB_SIZE = 100.0
PCB_HOLE_GRID = 90.0
PCB_CY = 290.0
PCB_HOLE_DIA = 3.2

CROSS = 4.0  # crosshair half-length
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "door-template.svg")


def crosshair(x: float, y: float) -> str:
    return (
        f'<line x1="{x - CROSS:.2f}" y1="{y:.2f}" x2="{x + CROSS:.2f}" y2="{y:.2f}"/>'
        f'<line x1="{x:.2f}" y1="{y - CROSS:.2f}" x2="{x:.2f}" y2="{y + CROSS:.2f}"/>'
    )


def hole(x: float, y: float, dia: float) -> str:
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{dia / 2:.2f}"/>' + crosshair(x, y)


def label(x: float, y: float, text: str, anchor: str = "middle") -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" fill="black" '
        f'stroke="none" font-size="4" font-family="sans-serif">{text}</text>'
    )


def main() -> None:
    e: list[str] = []

    # Door outline (reference only -- the door already exists).
    e.append(
        f'<rect x="0" y="0" width="{DOOR_W}" height="{DOOR_H}" '
        'fill="none" stroke-dasharray="6 3"/>'
    )
    e.append(label(CENTER_X, 12, f"DOOR OUTLINE {DOOR_W:.0f} x {DOOR_H:.0f} mm (reference)"))

    # Display window cutout + module outline + nominal module holes.
    wx, wy = CENTER_X - WINDOW_W / 2, WINDOW_CY - WINDOW_H / 2
    e.append(f'<rect x="{wx:.2f}" y="{wy:.2f}" width="{WINDOW_W}" height="{WINDOW_H}"/>')
    e.append(crosshair(CENTER_X, WINDOW_CY))
    e.append(label(CENTER_X, WINDOW_CY - WINDOW_H / 2 - 3,
                   f"CUT WINDOW {WINDOW_W:.0f} x {WINDOW_H:.0f}"))
    mx, my = CENTER_X - DISPLAY_PCB_W / 2, WINDOW_CY - DISPLAY_PCB_H / 2
    e.append(
        f'<rect x="{mx:.2f}" y="{my:.2f}" width="{DISPLAY_PCB_W}" '
        f'height="{DISPLAY_PCB_H}" fill="none" stroke-dasharray="2 2"/>'
    )
    for sx in (-1, 1):
        for sy in (-1, 1):
            e.append(hole(CENTER_X + sx * (DISPLAY_PCB_W / 2 - DISPLAY_HOLE_INSET),
                          WINDOW_CY + sy * (DISPLAY_PCB_H / 2 - DISPLAY_HOLE_INSET),
                          DISPLAY_HOLE_DIA))
    e.append(label(CENTER_X, my + DISPLAY_PCB_H + 6,
                   f"display module holes M3 -- VERIFY against your module before drilling"))

    # Nav cross.
    for dx, dy, name in ((0, -1, "UP"), (0, 1, "DOWN"), (-1, 0, "LEFT"),
                         (1, 0, "RIGHT"), (0, 0, "SEL")):
        x, y = CENTER_X + dx * NAV_PITCH, NAV_CY + dy * NAV_PITCH
        e.append(hole(x, y, NAV_HOLE_DIA))
        e.append(label(x, y + NAV_HOLE_DIA / 2 + 5, name))
    e.append(label(CENTER_X + 2 * NAV_PITCH + 8, NAV_CY + 1.5,
                   f"5x {NAV_HOLE_DIA} mm", "start"))

    # Controller PCB.
    px, py = CENTER_X - PCB_SIZE / 2, PCB_CY - PCB_SIZE / 2
    e.append(
        f'<rect x="{px:.2f}" y="{py:.2f}" width="{PCB_SIZE}" height="{PCB_SIZE}" '
        'fill="none" stroke-dasharray="2 2"/>'
    )
    for sx in (-1, 1):
        for sy in (-1, 1):
            e.append(hole(CENTER_X + sx * PCB_HOLE_GRID / 2,
                          PCB_CY + sy * PCB_HOLE_GRID / 2, PCB_HOLE_DIA))
    e.append(label(CENTER_X, PCB_CY,
                   f"controller PCB holes M3, {PCB_HOLE_GRID:.0f} x {PCB_HOLE_GRID:.0f} grid"))
    e.append(label(CENTER_X, PCB_CY + 6, "south edge (J5/J6) UP, USB-C down"))

    # Calibration ruler.
    ry = DOOR_H - 20
    e.append(f'<line x1="{CENTER_X - 50}" y1="{ry}" x2="{CENTER_X + 50}" y2="{ry}"/>')
    for tick in range(0, 101, 10):
        tx = CENTER_X - 50 + tick
        e.append(f'<line x1="{tx}" y1="{ry}" x2="{tx}" y2="{ry - 3}"/>')
    e.append(label(CENTER_X, ry + 6, "calibration: this ruler must measure exactly 100 mm"))

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{DOOR_W}mm" height="{DOOR_H}mm" '
        f'viewBox="0 0 {DOOR_W} {DOOR_H}">\n'
        '<g fill="none" stroke="black" stroke-width="0.3">\n'
        + "\n".join(e)
        + "\n</g>\n</svg>\n"
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
