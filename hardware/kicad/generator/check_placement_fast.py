"""Analytic courtyard-overlap check straight from design.py, no board build.

kicad_build.py is the only thing that can place parts, and it routes as it
goes (~340 s). This reads design.py's COMPONENTS table, pulls each part's
F.CrtYd extent from its .kicad_mod, and reports overlaps in seconds - so a
placement can be iterated before paying for a route.
"""
import re, sys, math, importlib.util, glob, os

FPDIRS = ["/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"]

def load_design():
    spec = importlib.util.spec_from_file_location("design", "generator/design.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

_cache = {}
def courtyard(fp):
    """(w, h) of the footprint's F.CrtYd bbox in mm, from the library file."""
    if fp in _cache: return _cache[fp]
    lib, name = fp.split(":", 1)
    path = None
    for d in FPDIRS:
        p = os.path.join(d, lib + ".pretty", name + ".kicad_mod")
        if os.path.exists(p): path = p; break
    if not path:
        hits = [p for d in FPDIRS for p in glob.glob(os.path.join(d, "*.pretty", name + ".kicad_mod"))]
        path = hits[0] if hits else None
    if not path:
        _cache[fp] = None; return None
    s = open(path).read()
    xs, ys = [], []
    # Walk balanced (fp_*) blocks and keep the ones whose layer is F.CrtYd.
    for m in re.finditer(r'\(fp_(?:line|poly|rect|circle|arc)\b', s):
        i = m.start(); depth = 0; j = i
        while j < len(s):
            if s[j] == '(': depth += 1
            elif s[j] == ')':
                depth -= 1
                if depth == 0: break
            j += 1
        blk = s[i:j+1]
        if '"F.CrtYd"' not in blk: continue
        for mm in re.finditer(r'\((?:start|end|center|mid|xy)\s+(-?[\d.]+)\s+(-?[\d.]+)\)', blk):
            xs.append(float(mm.group(1))); ys.append(float(mm.group(2)))
    if not xs:
        _cache[fp] = None; return None
    _cache[fp] = (min(xs), min(ys), max(xs), max(ys))
    return _cache[fp]

def bbox(ref, d):
    cy = courtyard(d["fp"])
    if cy is None: return None
    x0, y0, x1, y1 = cy
    x, y, rot = d["at"]
    # Rotate all four corners rather than special-casing 90 deg: a 180 deg
    # rotation NEGATES an asymmetric courtyard, and treating it as identity
    # put J1's box 1.1 mm off and invented a J8 overlap.
    a = math.radians(-rot); ca, sa = math.cos(a), math.sin(a)
    pts = [(px * ca - py * sa, px * sa + py * ca)
           for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    rx0 = min(p[0] for p in pts); rx1 = max(p[0] for p in pts)
    ry0 = min(p[1] for p in pts); ry1 = max(p[1] for p in pts)
    return (x + rx0, y + ry0, x + rx1, y + ry1)

def main():
    m = load_design()
    boxes = {}
    missing = []
    for ref, d in m.COMPONENTS.items():
        b = bbox(ref, d)
        if b is None: missing.append((ref, d["fp"])); continue
        boxes[ref] = b
    BX0, BY0, BX1, BY1 = m.BX0, m.BY0, m.BX1, m.BY1
    bad = 0
    refs = sorted(boxes)
    for i, a in enumerate(refs):
        ax0, ay0, ax1, ay1 = boxes[a]
        if ax0 < BX0 or ay0 < BY0 or ax1 > BX1 or ay1 > BY1:
            print("OFF-BOARD %-6s x %7.2f..%7.2f y %7.2f..%7.2f" % (a, ax0, ax1, ay0, ay1)); bad += 1
        for b in refs[i+1:]:
            bx0, by0, bx1, by1 = boxes[b]
            ox = min(ax1, bx1) - max(ax0, bx0); oy = min(ay1, by1) - max(ay0, by0)
            if ox > 1e-6 and oy > 1e-6:
                print("OVERLAP %-6s / %-6s  %.2f x %.2f mm" % (a, b, ox, oy)); bad += 1
    if missing:
        print("\nno F.CrtYd found (not checked): " + ", ".join("%s(%s)" % t for t in missing))
    print("\n%d parts checked, %d problem(s)" % (len(boxes), bad))
    return 1 if bad else 0

sys.exit(main())
