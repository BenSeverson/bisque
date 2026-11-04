#!/usr/bin/env python3
"""Read-only routing inventory for the 2026-11-03 review.

Run from any directory. CSV lengths sum all segments of a net, including
branches; they are not point-to-point propagation lengths. The optional PNG
requires Pillow. No design, fabrication, or assembly file is modified.
"""
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "generator"))
import board
from sexp import find, find_all, num, parse


def inventory():
    path = ROOT / "bisque-controller.kicad_pcb"
    bd = board.load(path)
    doc = parse(path.read_text())[0]
    pads = []
    for fp in find_all(doc, "footprint"):
        ref = board._prop(fp, "Reference")
        at = find(fp, "at")
        angle = math.radians(-num(at[3]) if len(at) > 3 else 0)
        for pad in find_all(fp, "pad"):
            pos = find(pad, "at")
            x, y = num(pos[1]), num(pos[2])
            pads.append({
                "ref": ref, "pin": str(pad[1]), "net": board._net_name(pad),
                "x": num(at[1]) + x * math.cos(angle) - y * math.sin(angle),
                "y": num(at[2]) + x * math.sin(angle) + y * math.cos(angle),
            })
    rows = collections.defaultdict(lambda: {"length_mm": 0., "vias": 0,
                                            "segments": 0, "layers": set()})
    for track in bd.tracks:
        row = rows[track["net"]]
        row["length_mm"] += math.hypot(track["x2"] - track["x1"],
                                       track["y2"] - track["y1"])
        row["segments"] += 1
        row["layers"].add(track["layer"])
    for via in bd.vias:
        rows[via["net"]]["vias"] += 1
    with (HERE / "net-metrics.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["net", "summed_track_length_mm", "standalone_vias",
                         "segments", "layers"])
        for net, row in sorted(rows.items()):
            writer.writerow([net, round(row["length_mm"], 3), row["vias"],
                             row["segments"], " / ".join(sorted(row["layers"]))])
    summary = {
        "board_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "edge_mm": bd.edge, "footprints": len(bd.fps),
        "track_segments": len(bd.tracks), "summed_track_length_mm":
            round(sum(row["length_mm"] for row in rows.values()), 3),
        "standalone_vias": len(bd.vias),
        "vias_by_net": dict(collections.Counter(v["net"] for v in bd.vias)),
        "via_sizes_mm": dict(collections.Counter(
            "%g/%g" % (num(find(v, "size")[1]), num(find(v, "drill")[1]))
            for v in find_all(doc, "via"))),
        "footprints_by_layer": dict(collections.Counter(
            f["layer"] for f in bd.fps.values())),
        "note": "Standalone vias exclude drilled footprint pads, including U1 EP holes.",
    }
    (HERE / "inventory.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return bd, pads


def plot(bd, pads):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1500, 850), "white")
    draw = ImageDraw.Draw(image)
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    try:
        font = ImageFont.truetype(font_path, 19)
        small = ImageFont.truetype(font_path, 15)
        title = ImageFont.truetype(font_path, 25)
    except OSError:
        font = small = title = ImageFont.load_default()
    panels = [
        (30, (32, 83, 65, 103), "SSR2 optocoupler detour",
         {"SSR2_OC": "#c23a35"}),
        (770, (84, 66, 112, 95), "CT inputs and reference",
         {"CTB_F": "#c23a35", "CTA_FN": "#2268ac", "ADE_REF": "#8a4cb0"}),
    ]
    for offset, bounds, heading, selected in panels:
        x0, y0, x1, y1 = bounds
        scale = min(660 / (x1 - x0), 620 / (y1 - y0))
        def xy(x, y):
            return offset + 30 + (x - x0) * scale, 110 + (y - y0) * scale
        draw.text((offset, 22), heading, fill="#152532", font=title)
        draw.text((offset, 61), "Solid: F.Cu   Dashed: B.Cu   Circles: vias", fill="#52616b", font=small)
        for x in range(math.ceil(x0), math.floor(x1) + 1, 5):
            draw.line([xy(x, y0), xy(x, y1)], fill="#ededed")
            draw.text((xy(x, y0)[0], 86), str(x), fill="#87939b", font=small)
        for y in range(math.ceil(y0), math.floor(y1) + 1, 5):
            draw.line([xy(x0, y), xy(x1, y)], fill="#ededed")
        def visible(t):
            return all(x0 <= t[k] <= x1 for k in ("x1", "x2")) and all(
                y0 <= t[k] <= y1 for k in ("y1", "y2"))
        for track in bd.tracks:
            if visible(track):
                draw.line([xy(track["x1"], track["y1"]),
                           xy(track["x2"], track["y2"])], fill="#d9dfe2", width=2)
        for track in bd.tracks:
            if track["net"] not in selected or not visible(track):
                continue
            a = xy(track["x1"], track["y1"])
            b = xy(track["x2"], track["y2"])
            color = selected[track["net"]]
            if track["layer"] == "F.Cu":
                draw.line([a, b], fill=color, width=5)
            else:
                length = math.dist(a, b)
                for s in range(0, math.ceil(length), 13):
                    u, v = s / max(length, 1), min(s + 8, length) / max(length, 1)
                    draw.line([(a[0] + (b[0]-a[0])*u, a[1] + (b[1]-a[1])*u),
                               (a[0] + (b[0]-a[0])*v, a[1] + (b[1]-a[1])*v)],
                              fill=color, width=5)
        for via in bd.vias:
            if via["net"] in selected and x0 <= via["x"] <= x1 and y0 <= via["y"] <= y1:
                px, py = xy(via["x"], via["y"])
                draw.ellipse((px-6, py-6, px+6, py+6), fill="white",
                             outline=selected[via["net"]], width=3)
        for pad in pads:
            if pad["net"] in selected and x0 <= pad["x"] <= x1 and y0 <= pad["y"] <= y1:
                px, py = xy(pad["x"], pad["y"])
                draw.rectangle((px-5, py-5, px+5, py+5), fill=selected[pad["net"]])
                draw.text((px+8, py-19), pad["ref"]+"."+pad["pin"], fill="#152532", font=small,
                          stroke_width=2, stroke_fill="white")
        for i, (net, color) in enumerate(selected.items()):
            y = 755 + i * 26
            draw.line((offset+5, y+10, offset+35, y+10), fill=color, width=5)
            draw.text((offset+45, y), net, fill=color, font=font)
    image.save(HERE / "routing-hotspots.png")


if __name__ == "__main__":
    board_data, pad_data = inventory()
    try:
        plot(board_data, pad_data)
    except ImportError:
        print("Pillow unavailable; CSV and JSON written, PNG skipped.")
