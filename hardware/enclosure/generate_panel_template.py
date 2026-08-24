#!/usr/bin/env python3
"""1:1 drill/cutout templates for the enclosure door (SVG, mm units).

Emits one template per door revision next to this script:

  door-template.svg        rev 1 -- 5-way nav switch, covered display window
  door-template-touch.svg  rev 2 -- touch only, no buttons, exposed glass

Each carries the door outline of the baseline 16 x 12 x 6 in box
(305 x 406 mm), the display cutout, the display module mounting holes, the
controller PCB's 90 x 90 mm M3 grid, and (rev 1 only) the 5-button nav
cross -- with center crosshairs, dimension labels, and a 100 mm calibration
ruler so a print can be verified unscaled before drilling.

The two revisions differ in more than the missing holes: rev 2's cutout is
sized to the display's ACTIVE AREA rather than oversized for a window,
because a resistive touch panel has to be reachable through it. See
README.md "Revision 2" for why that leaves only ~3 mm of gasket land.

Stdlib only. Every dimension is a module-level constant; the display module
hole positions are nominal (clone MSP4021 modules vary) and are labelled
VERIFY on the drawing -- measure the module in hand, adjust
DISPLAY_HOLE_INSET / DISPLAY_HOLE_DIA, and re-run.
"""

from __future__ import annotations

import os

# --- Door (16 x 12 x 6 in wall-mount box, mounted 406 mm tall) -----------
DOOR_W = 305.0
DOOR_H = 406.0
CENTER_X = DOOR_W / 2  # everything is centered horizontally

# --- Display module (LCDWIKI MSP4021, landscape) -------------------------
DISPLAY_PCB_W = 108.04
DISPLAY_PCB_H = 61.74
DISPLAY_ACTIVE_W = 83.52
DISPLAY_ACTIVE_H = 55.68
DISPLAY_HOLE_INSET = 2.5
DISPLAY_HOLE_DIA = 3.2

# rev 1 window: oversized, reveals the active area behind a bonded
# polycarbonate pane with ~1 mm of margin.
WINDOW_W = 86.0
WINDOW_H = 58.0
WINDOW_CY = 110.0

# rev 2 cutout: the active area plus 0.5 mm all round, no more -- the steel
# has to keep a sealing land on a module whose glass nearly fills its PCB.
TOUCH_CUT_W = DISPLAY_ACTIVE_W + 1.0   # 84.52
TOUCH_CUT_H = DISPLAY_ACTIVE_H + 1.0   # 56.68
TOUCH_CY = 120.0

# --- Nav cross (rev 1 only: five 12 mm panel-mount momentary buttons) ----
NAV_CY = 190.0
NAV_PITCH = 24.0
NAV_HOLE_DIA = 12.2

# --- Controller PCB (100 x 100 mm, M3 grid 90 x 90 mm) -------------------
PCB_SIZE = 100.0
PCB_HOLE_GRID = 90.0
PCB_CY = 290.0
PCB_CY_TOUCH = 280.0
PCB_HOLE_DIA = 3.2

CROSS = 4.0  # crosshair half-length
HERE = os.path.dirname(os.path.abspath(__file__))


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


def door_outline() -> list[str]:
    return [
        f'<rect x="0" y="0" width="{DOOR_W}" height="{DOOR_H}" '
        'fill="none" stroke-dasharray="6 3"/>',
        label(CENTER_X, 12, f"DOOR OUTLINE {DOOR_W:.0f} x {DOOR_H:.0f} mm (reference)"),
    ]


def display_block(cut_w: float, cut_h: float, cy: float, cut_note: str,
                  note_above_module: bool = False) -> list[str]:
    """Cutout, module outline, and the four nominal module M3 holes.

    note_above_module lifts the cut note clear of the module outline, which
    rev 2 needs: its cutout stops ~2.5 mm short of the module edge, so a
    note placed just above the cutout prints straight through the outline.
    """
    e = []
    cx0, cy0 = CENTER_X - cut_w / 2, cy - cut_h / 2
    e.append(f'<rect x="{cx0:.2f}" y="{cy0:.2f}" width="{cut_w}" height="{cut_h}"/>')
    e.append(crosshair(CENTER_X, cy))
    note_y = (cy - DISPLAY_PCB_H / 2 - 4) if note_above_module else (cy - cut_h / 2 - 3)
    e.append(label(CENTER_X, note_y, cut_note))
    mx, my = CENTER_X - DISPLAY_PCB_W / 2, cy - DISPLAY_PCB_H / 2
    e.append(
        f'<rect x="{mx:.2f}" y="{my:.2f}" width="{DISPLAY_PCB_W}" '
        f'height="{DISPLAY_PCB_H}" fill="none" stroke-dasharray="2 2"/>'
    )
    for sx in (-1, 1):
        for sy in (-1, 1):
            e.append(hole(CENTER_X + sx * (DISPLAY_PCB_W / 2 - DISPLAY_HOLE_INSET),
                          cy + sy * (DISPLAY_PCB_H / 2 - DISPLAY_HOLE_INSET),
                          DISPLAY_HOLE_DIA))
    e.append(label(CENTER_X, my + DISPLAY_PCB_H + 6,
                   f"display module holes M3 -- VERIFY against your module before drilling"))
    return e


def pcb_block(cy: float, note: str) -> list[str]:
    e = []
    px, py = CENTER_X - PCB_SIZE / 2, cy - PCB_SIZE / 2
    e.append(
        f'<rect x="{px:.2f}" y="{py:.2f}" width="{PCB_SIZE}" height="{PCB_SIZE}" '
        'fill="none" stroke-dasharray="2 2"/>'
    )
    for sx in (-1, 1):
        for sy in (-1, 1):
            e.append(hole(CENTER_X + sx * PCB_HOLE_GRID / 2,
                          cy + sy * PCB_HOLE_GRID / 2, PCB_HOLE_DIA))
    e.append(label(CENTER_X, cy,
                   f"controller PCB holes M3, {PCB_HOLE_GRID:.0f} x {PCB_HOLE_GRID:.0f} grid"))
    e.append(label(CENTER_X, cy + 6, note))
    return e


def ruler() -> list[str]:
    e = []
    ry = DOOR_H - 20
    e.append(f'<line x1="{CENTER_X - 50}" y1="{ry}" x2="{CENTER_X + 50}" y2="{ry}"/>')
    for tick in range(0, 101, 10):
        tx = CENTER_X - 50 + tick
        e.append(f'<line x1="{tx}" y1="{ry}" x2="{tx}" y2="{ry - 3}"/>')
    e.append(label(CENTER_X, ry + 6, "calibration: this ruler must measure exactly 100 mm"))
    return e


def build_rev1() -> list[str]:
    """Rev 1: nav switch plus a covered (non-touch) display window."""
    e = door_outline()
    e += display_block(WINDOW_W, WINDOW_H, WINDOW_CY,
                       f"CUT WINDOW {WINDOW_W:.0f} x {WINDOW_H:.0f}")
    for dx, dy, name in ((0, -1, "UP"), (0, 1, "DOWN"), (-1, 0, "LEFT"),
                         (1, 0, "RIGHT"), (0, 0, "SEL")):
        x, y = CENTER_X + dx * NAV_PITCH, NAV_CY + dy * NAV_PITCH
        e.append(hole(x, y, NAV_HOLE_DIA))
        e.append(label(x, y + NAV_HOLE_DIA / 2 + 5, name))
    e.append(label(CENTER_X + 2 * NAV_PITCH + 8, NAV_CY + 1.5,
                   f"5x {NAV_HOLE_DIA} mm", "start"))
    e += pcb_block(PCB_CY, "south edge (J5/J6) UP, USB-C down")
    e += ruler()
    return e


def build_rev2() -> list[str]:
    """Rev 2: touch only. No button holes, and the glass is exposed."""
    e = door_outline()
    e.append(label(CENTER_X, 20, "REV 2 -- TOUCH ONLY: no button holes on this door"))
    e += display_block(TOUCH_CUT_W, TOUCH_CUT_H, TOUCH_CY,
                       f"CUT {TOUCH_CUT_W:.1f} x {TOUCH_CUT_H:.1f} (active area)"
                       " -- deburr, glass is exposed",
                       note_above_module=True)
    # The gasket seats on the module PCB between the cutout and the module
    # edge; on this module that land is only ~2.5 mm top and bottom.
    land_y = (DISPLAY_PCB_H - TOUCH_CUT_H) / 2
    e.append(label(CENTER_X, TOUCH_CY - DISPLAY_PCB_H / 2 - 10,
                   f"gasket land only {land_y:.1f} mm top/bottom"
                   f" -- see README 'Revision 2'"))
    e += pcb_block(PCB_CY_TOUCH, "south edge (J5) UP, USB-C down; J6 unfitted")
    e += ruler()
    return e


VARIANTS = (
    ("door-template.svg", build_rev1),
    ("door-template-touch.svg", build_rev2),
)


def write(path: str, elements: list[str]) -> None:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{DOOR_W}mm" height="{DOOR_H}mm" '
        f'viewBox="0 0 {DOOR_W} {DOOR_H}">\n'
        '<g fill="none" stroke="black" stroke-width="0.3">\n'
        + "\n".join(elements)
        + "\n</g>\n</svg>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {path}")


def main() -> None:
    for name, build in VARIANTS:
        write(os.path.join(HERE, name), build())


if __name__ == "__main__":
    main()
