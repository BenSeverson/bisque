"""Render the generated .kicad_pcb to SVG (then PNG via chromium) for review."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, num

SCALE = 14  # px per mm


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(src, dst_svg):
    doc = parse(open(src).read())[0]
    xs, ys = [], []
    edges = []
    for g in find_all(doc, "gr_line"):
        lay = find(g, "layer")
        if str(lay[1]) == "Edge.Cuts":
            s, e = find(g, "start"), find(g, "end")
            edges.append((num(s[1]), num(s[2]), num(e[1]), num(e[2])))
            xs += [num(s[1]), num(e[1])]
            ys += [num(s[2]), num(e[2])]
    x0, y0, x1, y1 = min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3
    W, H = (x1 - x0) * SCALE, (y1 - y0) * SCALE

    def X(x):
        return (x - x0) * SCALE

    def Y(y):
        return (y - y0) * SCALE

    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d"><rect width="%d" height="%d" fill="#101418"/>'
           % (W, H, W, H, W, H)]

    # board
    out.append('<rect x="%f" y="%f" width="%f" height="%f" fill="#1b3a1b" stroke="#c9b23c" stroke-width="2"/>'
               % (X(min(xs)), Y(min(ys)), (max(xs) - min(xs)) * SCALE, (max(ys) - min(ys)) * SCALE))

    fcol, bcol = "#c0392b", "#2471a3"
    # B.Cu segments first, then F
    segs = {0: [], 1: []}
    for s in find_all(doc, "segment"):
        st, en, w = find(s, "start"), find(s, "end"), find(s, "width")
        lay = 0 if str(find(s, "layer")[1]) == "F.Cu" else 1
        segs[lay].append((num(st[1]), num(st[2]), num(en[1]), num(en[2]), num(w[1])))
    for lay, col, op in ((1, bcol, 0.9), (0, fcol, 0.85)):
        for (ax, ay, bx, by, w) in segs[lay]:
            out.append('<line x1="%f" y1="%f" x2="%f" y2="%f" stroke="%s" '
                       'stroke-width="%f" stroke-linecap="round" opacity="%s"/>'
                       % (X(ax), Y(ay), X(bx), Y(by), col, w * SCALE, op))
    # footprint pads
    for fp in find_all(doc, "footprint"):
        at = find(fp, "at")
        fx, fy = num(at[1]), num(at[2])
        frot = num(at[3]) if len(at) > 3 else 0.0
        ref = ""
        for pr in find_all(fp, "property"):
            if pr[1] == "Reference":
                ref = pr[2]
        for ft in find_all(fp, "fp_text"):
            if str(ft[1]) == "reference":
                ref = str(ft[2])
        for p in find_all(fp, "pad"):
            pat = find(p, "at")
            lx, ly = num(pat[1]), num(pat[2])
            pa = (num(pat[3]) if len(pat) > 3 else 0.0) - frot
            a = math.radians(frot)
            c, sn = round(math.cos(a)), round(math.sin(a))
            gx = fx + lx * c + ly * sn
            gy = fy - lx * sn + ly * c
            size = find(p, "size")
            w, h = num(size[1]), num(size[2])
            if abs(((pa + frot) % 180) - 90) < 1:
                w, h = h, w
            kind = str(p[2])
            col = "#d4ac0d" if kind.startswith("thru") else "#e67e22"
            if kind == "np_thru_hole":
                col = "#7f8c8d"
            netn = find(p, "net")
            netname = (netn[2] if len(netn) > 2 else netn[1]) if netn else ""
            out.append('<rect x="%f" y="%f" width="%f" height="%f" fill="%s" opacity="0.9">'
                       '<title>%s.%s %s</title></rect>'
                       % (X(gx - w / 2), Y(gy - h / 2), w * SCALE, h * SCALE, col,
                          esc(str(ref)), esc(str(p[1])), esc(str(netname))))
        # ref label at footprint origin
        out.append('<text x="%f" y="%f" fill="#ecf0f1" font-size="11" text-anchor="middle">%s</text>'
                   % (X(fx), Y(fy) - 4, esc(str(ref))))
    # vias
    for v in find_all(doc, "via"):
        at = find(v, "at")
        sz = find(v, "size")
        free = find(v, "free")
        col = "#27ae60" if free else "#8e44ad"
        out.append('<circle cx="%f" cy="%f" r="%f" fill="%s"/>'
                   % (X(num(at[1])), Y(num(at[2])), num(sz[1]) / 2 * SCALE, col))
    # keepout marker (from module: hardcode display only)
    out.append('</svg>')
    open(dst_svg, "w").write("\n".join(out))
    print("wrote", dst_svg)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
