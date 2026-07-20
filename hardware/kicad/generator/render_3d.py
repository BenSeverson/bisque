"""Render the generated .kicad_pcb to 3D PNGs.

Parses the board file, builds a 3D scene (board slab with real drilled
holes, copper tracks/pads/vias, and stylized component bodies per package),
then renders it with three.js inside headless chromium (software WebGL).

Usage:
    python3 render_3d.py <board.kicad_pcb> <outdir> [chromium-binary]

Requires three.min.js next to this script (fetched by fetch-three.sh) and
a chromium headless binary (auto-detected under /opt/pw-browsers).
"""
import glob
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, num

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# triangle-soup helpers (three.js coords: x = kicad x, y = -kicad y, z = up)
# ---------------------------------------------------------------------------


class Buffers:
    def __init__(self):
        self.mats = {}

    def bucket(self, key):
        return self.mats.setdefault(key, [])

    def tri(self, key, a, b, c):
        self.bucket(key).extend([a[0], -a[1], a[2], b[0], -b[1], b[2],
                                 c[0], -c[1], c[2]])

    def quad(self, key, a, b, c, d):
        self.tri(key, a, b, c)
        self.tri(key, a, c, d)

    def box(self, key, cx, cy, z0, z1, w, h, rot=0.0):
        """Axis box (w along x, h along y before rot), kicad xy, z up."""
        ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))

        def pt(dx, dy, z):
            # kicad-frame rotation (visual CCW with y-down)
            return (cx + dx * ca + dy * sa, cy - dx * sa + dy * ca, z)

        hw, hh = w / 2.0, h / 2.0
        p = {}
        for iz, z in ((0, z0), (1, z1)):
            p[(0, iz)] = pt(-hw, -hh, z)
            p[(1, iz)] = pt(hw, -hh, z)
            p[(2, iz)] = pt(hw, hh, z)
            p[(3, iz)] = pt(-hw, hh, z)
        self.quad(key, p[(0, 1)], p[(1, 1)], p[(2, 1)], p[(3, 1)])   # top
        self.quad(key, p[(3, 0)], p[(2, 0)], p[(1, 0)], p[(0, 0)])   # bottom
        for i in range(4):
            j = (i + 1) % 4
            self.quad(key, p[(i, 0)], p[(j, 0)], p[(j, 1)], p[(i, 1)])

    def cyl(self, key, cx, cy, z0, z1, r, seg=20, r2=None):
        r2 = r if r2 is None else r2
        pts0, pts1 = [], []
        for k in range(seg):
            a = 2 * math.pi * k / seg
            pts0.append((cx + r * math.cos(a), cy + r * math.sin(a), z0))
            pts1.append((cx + r2 * math.cos(a), cy + r2 * math.sin(a), z1))
        for k in range(seg):
            j = (k + 1) % seg
            self.quad(key, pts0[k], pts0[j], pts1[j], pts1[k])
        ctr0, ctr1 = (cx, cy, z0), (cx, cy, z1)
        for k in range(seg):
            j = (k + 1) % seg
            self.tri(key, ctr1, pts1[k], pts1[j])
            self.tri(key, ctr0, pts0[j], pts0[k])

    def seg(self, key, x1, y1, x2, y2, w, z0, z1):
        """Track segment as a flat capsule-ish quad (rect only, cheap)."""
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L < 1e-9:
            self.cyl(key, x1, y1, z0, z1, w / 2, seg=8)
            return
        nx, ny = -dy / L * w / 2, dx / L * w / 2
        ex, ey = dx / L * w / 2, dy / L * w / 2   # end extension (poor man's cap)
        a = (x1 - ex + nx, y1 - ey + ny, z1)
        b = (x2 + ex + nx, y2 + ey + ny, z1)
        c = (x2 + ex - nx, y2 + ey - ny, z1)
        d = (x1 - ex - nx, y1 - ey - ny, z1)
        self.quad(key, a, b, c, d)


MATS = {
    "track_top":   dict(color=0x2e8b3d, metalness=0.1, roughness=0.7),
    "track_bot":   dict(color=0x2e8b3d, metalness=0.1, roughness=0.7),
    "gold":        dict(color=0xcfa93f, metalness=0.45, roughness=0.45),
    "hole_dark":   dict(color=0x14100c, metalness=0.2, roughness=0.9),
    "black":       dict(color=0x1d1d20, metalness=0.1, roughness=0.75),
    "ic_black":    dict(color=0x2a2a2e, metalness=0.15, roughness=0.55),
    "silver":      dict(color=0xb4b9c2, metalness=0.45, roughness=0.35),
    "tan":         dict(color=0xc09a62, metalness=0.05, roughness=0.8),
    "white":       dict(color=0xe9e9e6, metalness=0.0, roughness=0.85),
    "green_term":  dict(color=0x4aab52, metalness=0.05, roughness=0.8),
    "esp_pcb":     dict(color=0x16265c, metalness=0.1, roughness=0.7),
    "led_green":   dict(color=0x53c05e, metalness=0.1, roughness=0.4),
    "led_amber":   dict(color=0xe0a020, metalness=0.1, roughness=0.4),
    "led_lens":    dict(color=0xcfd4d6, metalness=0.3, roughness=0.25),
    "band_white":  dict(color=0xdddddd, metalness=0.0, roughness=0.8),
    "buzzer":      dict(color=0x111114, metalness=0.1, roughness=0.6),
}

TOP = 1.6      # board top z
CU = 0.04      # copper/track height above surface


def rot_xy(lx, ly, rot):
    a = math.radians(rot)
    c, s = round(math.cos(a)), round(math.sin(a))
    return (lx * c + ly * s, -lx * s + ly * c)


def build_scene(src):
    doc = parse(open(src).read())[0]
    B = Buffers()

    # --- board outline + holes ---
    xs, ys = [], []
    for g in find_all(doc, "gr_line"):
        if str(find(g, "layer")[1]) == "Edge.Cuts":
            s, e = find(g, "start"), find(g, "end")
            xs += [num(s[1]), num(e[1])]
            ys += [num(s[2]), num(e[2])]
    bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
    holes = []   # (x, y, r) real drills through the slab

    # --- tracks & vias ---
    for s in find_all(doc, "segment"):
        st, en = find(s, "start"), find(s, "end")
        w = num(find(s, "width")[1])
        top = str(find(s, "layer")[1]) == "F.Cu"
        if top:
            B.seg("track_top", num(st[1]), num(st[2]), num(en[1]), num(en[2]),
                  w, TOP, TOP + 0.02)
        else:
            B.seg("track_bot", num(st[1]), num(st[2]), num(en[1]), num(en[2]),
                  w, 0.0, -0.02)
    for v in find_all(doc, "via"):
        at = find(v, "at")
        x, y = num(at[1]), num(at[2])
        r = num(find(v, "size")[1]) / 2
        B.cyl("gold", x, y, -0.02, TOP + 0.02, r, seg=12)
        B.cyl("hole_dark", x, y, TOP + 0.021, TOP + 0.03,
              num(find(v, "drill")[1]) / 2, seg=10)

    # --- footprints: pads + bodies ---
    for fp in find_all(doc, "footprint"):
        name = str(fp[1])
        at = find(fp, "at")
        fx, fy = num(at[1]), num(at[2])
        frot = num(at[3]) if len(at) > 3 else 0.0
        props = {p[1]: str(p[2]) for p in find_all(fp, "property")}
        value = props.get("Value", "")
        npads = []
        for p in find_all(fp, "pad"):
            lay = find(p, "layers")
            laystr = " ".join(str(e) for e in lay[1:]) if lay else ""
            kind = str(p[2])
            pat = find(p, "at")
            lx, ly = num(pat[1]), num(pat[2])
            pa = num(pat[3]) if len(pat) > 3 else 0.0
            gx, gy = rot_xy(lx, ly, frot)
            gx += fx
            gy += fy
            size = find(p, "size")
            w, h = num(size[1]), num(size[2])
            if abs((pa % 180) - 90) < 1:
                w, h = h, w
            drill = find(p, "drill")
            if kind in ("thru_hole", "np_thru_hole") and drill:
                dr = num(drill[1]) / 2
                holes.append((gx, gy, dr))
            if kind == "np_thru_hole" and drill:
                B.cyl("hole_dark", gx, gy, TOP - 0.01, TOP + 0.02,
                      num(drill[1]) / 2, seg=12)
            if "Cu" not in laystr:
                continue
            npads.append((str(p[1]), gx, gy))
            shape = str(p[3])
            if kind == "thru_hole":
                r = max(w, h) / 2
                B.cyl("gold", gx, gy, TOP, TOP + 0.03, r, seg=16)
                B.cyl("gold", gx, gy, -0.03, 0.0, r, seg=16)
                if drill:
                    dr = num(drill[1]) / 2
                    B.cyl("hole_dark", gx, gy, TOP + 0.031, TOP + 0.04, dr, seg=14)
                    B.cyl("hole_dark", gx, gy, -0.04, -0.031, dr, seg=14)
            elif kind == "smd":
                if shape == "circle":
                    B.cyl("gold", gx, gy, TOP, TOP + 0.03, w / 2, seg=12)
                else:
                    B.box("gold", gx, gy, TOP, TOP + 0.03, w, h)
        body(B, name, value, fx, fy, frot, npads)

    # thru-hole pins (gold posts) for headers is handled in body()

    scene = {
        "board": {"x0": bx0, "y0": by0, "x1": bx1, "y1": by1,
                  "thickness": TOP,
                  "holes": [[h[0], h[1], h[2]] for h in holes]},
        "materials": {k: MATS[k] for k in B.mats if k in MATS},
        "buffers": {k: [round(v, 3) for v in vals] for k, vals in B.mats.items()},
    }
    return scene


def body(B, fpname, value, fx, fy, frot, pads):
    def box(lx, ly, z0, z1, w, h, key, extra_rot=0.0):
        gx, gy = rot_xy(lx, ly, frot)
        B.box(key, fx + gx, fy + gy, z0, z1, w, h, rot=frot + extra_rot)

    def cyl(lx, ly, z0, z1, r, key, seg=20):
        gx, gy = rot_xy(lx, ly, frot)
        B.cyl(key, fx + gx, fy + gy, z0, z1, r, seg=seg)

    T = TOP
    if "ESP32-S3-WROOM-1" in fpname:
        # module PCB slab, shield can, antenna meander
        box(0, -0.25, T, T + 0.8, 18, 25.0, "esp_pcb")
        box(0, 2.85, T + 0.8, T + 3.1, 17.0, 17.8, "silver")
        for k in range(6):
            box(-6.5 + k * 2.6, -10.0, T + 0.8, T + 0.95, 1.0, 4.6, "gold")
        box(0, -12.0, T + 0.8, T + 0.95, 14.0, 0.9, "gold")
    elif "SOIC-8" in fpname:
        box(0, 0, T + 0.1, T + 1.6, 3.9, 4.9, "ic_black")
    elif "SOT-223" in fpname:
        box(0.4, 0, T + 0.05, T + 1.7, 4.2, 3.6, "ic_black")
    elif "SOT-23-6" in fpname or ("SOT-23" in fpname):
        box(0, 0, T + 0.05, T + 1.15, 1.7, 3.0, "ic_black") \
            if "SOT-23-6" in fpname else \
            box(0, 0, T + 0.05, T + 1.15, 1.4, 3.0, "ic_black")
    elif "R_0805" in fpname:
        box(0, 0, T + 0.05, T + 0.55, 2.0, 1.25, "black")
        box(-0.85, 0, T + 0.05, T + 0.58, 0.35, 1.25, "silver")
        box(0.85, 0, T + 0.05, T + 0.58, 0.35, 1.25, "silver")
    elif "C_0805" in fpname or "C_1206" in fpname:
        L, W, H = (3.2, 1.6, 1.1) if "1206" in fpname else (2.0, 1.25, 0.85)
        box(0, 0, T + 0.05, T + H, L, W, "tan")
        box(-L / 2 + 0.2, 0, T + 0.05, T + H + 0.02, 0.4, W, "silver")
        box(L / 2 - 0.2, 0, T + 0.05, T + H + 0.02, 0.4, W, "silver")
    elif "LED_WS2812B" in fpname:
        box(0, 0, T + 0.05, T + 1.6, 5.0, 5.0, "white")
        cyl(0, 0, T + 1.6, T + 1.7, 1.9, "led_lens")
    elif "LED_0805" in fpname:
        key = "led_amber" if "amber" in value else "led_green"
        box(0, 0, T + 0.05, T + 0.7, 2.0, 1.25, key)
    elif "D_SMA" in fpname:
        box(0, 0, T + 0.05, T + 1.1, 4.3, 2.6, "ic_black")
        box(-1.4, 0, T + 1.1, T + 1.12, 0.7, 2.6, "band_white")
        box(-2.35, 0, T + 0.05, T + 0.3, 0.5, 1.5, "silver")
        box(2.35, 0, T + 0.05, T + 0.3, 0.5, 1.5, "silver")
    elif "D_SOD-123" in fpname:
        box(0, 0, T + 0.05, T + 1.0, 2.7, 1.6, "ic_black")
        box(-0.85, 0, T + 1.0, T + 1.02, 0.5, 1.6, "band_white")
    elif "TerminalBlock" in fpname:
        box(2.54, -0.3, T, T + 10.2, 10.2, 9.8, "green_term")
        for (pn, gx, gy) in pads:
            B.cyl("hole_dark", gx, gy - 0 + 0, T + 10.2, T + 10.28, 1.5, seg=14)
    elif "PinHeader" in fpname:
        if pads:
            xs = [p[1] for p in pads]
            ys = [p[2] for p in pads]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            L = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) + 2.54
            ang = 0.0 if abs(max(ys) - min(ys)) < 0.1 else 90.0
            B.box("black", cx, cy, T, T + 2.5, L, 2.54, rot=ang)
            for (pn, gx, gy) in pads:
                B.box("gold", gx, gy, T + 2.5, T + 8.5, 0.64, 0.64)
    elif "SW_PUSH_6mm" in fpname:
        box(3.25, 2.25, T, T + 3.5, 6.2, 6.2, "silver")
        cyl(3.25, 2.25, T + 3.5, T + 4.3, 1.7, "black")
    elif "Buzzer" in fpname:
        cyl(3.8, 0, T, T + 9.5, 6.0, "buzzer", seg=28)
        cyl(3.8, 0, T + 9.5, T + 9.52, 1.0, "hole_dark", seg=12)
    elif "USB_C_Receptacle" in fpname:
        box(0, 0.15, T, T + 3.2, 9.0, 7.6, "silver")
        box(0, 4.05, T + 0.55, T + 2.75, 7.6, 0.4, "hole_dark")
    elif "MountingHole" in fpname:
        pass


HTML_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;overflow:hidden;background:#191c20}</style>
<script>%THREE%</script></head><body><script>
const SCENE = %SCENE%;
const VIEW = %VIEW%;
const W = %W%, H = %H%;
const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
renderer.setSize(W, H);
document.body.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x22262b);
const b = SCENE.board;
const cx = (b.x0+b.x1)/2, cy = -(b.y0+b.y1)/2;
// board slab with drilled holes
const shape = new THREE.Shape();
shape.moveTo(b.x0, -b.y0); shape.lineTo(b.x1, -b.y0);
shape.lineTo(b.x1, -b.y1); shape.lineTo(b.x0, -b.y1); shape.closePath();
for (const [hx, hy, hr] of b.holes) {
  const p = new THREE.Path();
  p.absarc(hx, -hy, hr, 0, Math.PI*2, true);
  shape.holes.push(p);
}
const boardGeo = new THREE.ExtrudeGeometry(shape, {depth: b.thickness, bevelEnabled: false});
const boardMat = new THREE.MeshStandardMaterial({color: 0x17612a, metalness: 0.1, roughness: 0.65});
const board = new THREE.Mesh(boardGeo, boardMat);
scene.add(board);
for (const [key, mat] of Object.entries(SCENE.materials)) {
  const arr = new Float32Array(SCENE.buffers[key]);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  g.computeVertexNormals();
  const m = new THREE.MeshStandardMaterial({color: mat.color,
    metalness: mat.metalness, roughness: mat.roughness, flatShading: true,
    side: THREE.DoubleSide});
  scene.add(new THREE.Mesh(g, m));
}
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a4030, 0.55));
const key1 = new THREE.DirectionalLight(0xffffff, 1.6);
key1.position.set(cx-80, cy-60, 160); scene.add(key1);
const key2 = new THREE.DirectionalLight(0xdfe8ff, 0.7);
key2.position.set(cx+120, cy+40, 60); scene.add(key2);
const under = new THREE.DirectionalLight(0xffffff, 1.5);
under.position.set(cx+30, cy-50, -140); scene.add(under);
const cam = new THREE.PerspectiveCamera(VIEW.fov||32, W/H, 1, 2000);
const az = VIEW.az*Math.PI/180, el = VIEW.el*Math.PI/180, d = VIEW.dist;
cam.position.set(cx + d*Math.cos(el)*Math.sin(az),
                 cy - d*Math.cos(el)*Math.cos(az),
                 d*Math.sin(el));
cam.up.set(0,0,1);
cam.lookAt(cx, cy, 0);
renderer.render(scene, cam);
document.title = 'RENDER_DONE';
</script></body></html>"""

VIEWS = {
    "iso":    dict(az=-32, el=38, dist=175, fov=30),
    "front":  dict(az=8, el=16, dist=185, fov=30),
    "top":    dict(az=0, el=82, dist=170, fov=30),
    "back":   dict(az=150, el=-42, dist=175, fov=30),
}


def find_chromium():
    for pat in ("/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
                "/opt/pw-browsers/chromium-*/chrome-linux/chrome"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return "chromium"


def main(src, outdir, chromium=None):
    chromium = chromium or find_chromium()
    threejs_path = os.path.join(HERE, "three.min.js")
    if not os.path.exists(threejs_path):
        sys.exit("three.min.js missing — run fetch-three.sh first")
    threejs = open(threejs_path).read()
    scene = build_scene(src)
    os.makedirs(outdir, exist_ok=True)
    W, H = 1600, 1200
    scene_json = json.dumps(scene)
    for view, cam in VIEWS.items():
        html = (HTML_TEMPLATE
                .replace("%THREE%", threejs)
                .replace("%SCENE%", scene_json)
                .replace("%VIEW%", json.dumps(cam))
                .replace("%W%", str(W)).replace("%H%", str(H)))
        hpath = os.path.join(outdir, "_render_%s.html" % view)
        open(hpath, "w").write(html)
        out = os.path.join(outdir, "board-3d-%s.png" % view)
        subprocess.run([chromium, "--headless", "--no-sandbox", "--disable-gpu",
                        "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                        "--hide-scrollbars",
                        "--window-size=%d,%d" % (W, H),
                        "--screenshot=%s" % out,
                        "file://" + os.path.abspath(hpath)],
                       check=True, capture_output=True)
        os.remove(hpath)
        print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".",
         sys.argv[3] if len(sys.argv) > 3 else None)
