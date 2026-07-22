"""Extract needed symbols (flattening `extends`) and report pin/pad geometry."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from sexp import parse, find, find_all, Sym, num

BASE = os.path.dirname(os.path.abspath(__file__))
SYMDIR = os.path.join(BASE, "sym")
FPDIR = os.path.join(BASE, "fp")

WANT = [
    ("RF_Module", "ESP32-S3-WROOM-1"),
    ("Regulator_Linear", "AMS1117-3.3"),
    ("Sensor_Temperature", "MAX31855KASA"),
    ("Device", "R"),
    ("Device", "C"),
    ("Device", "D_Schottky"),
    ("Device", "D"),
    ("Device", "LED"),
    ("Device", "Buzzer"),
    ("Device", "Q_NMOS_GSD"),
    ("Connector", "USB_C_Receptacle_USB2.0_16P"),
    ("Connector_Generic", "Conn_01x06"),
    ("Connector_Generic", "Conn_01x08"),
    ("Connector_Generic", "Screw_Terminal_01x02"),
    ("Switch", "SW_Push"),
    ("power", "GND"),
    ("power", "+3V3"),
    ("power", "+5V"),
    ("power", "PWR_FLAG"),
    ("Power_Protection", "USBLC6-2SC6"),
    ("LED", "WS2812B"),
    ("Mechanical", "MountingHole_Pad"),
]

_libcache = {}


def load_lib(name):
    if name not in _libcache:
        with open(os.path.join(SYMDIR, name + ".kicad_sym")) as f:
            _libcache[name] = parse(f.read())[0]
    return _libcache[name]


def get_symbol(lib, name):
    root = load_lib(lib)
    for s in find_all(root, "symbol"):
        if s[1] == name:
            return s
    raise KeyError("%s not in %s" % (name, lib))


def flatten(lib, name):
    """Resolve `extends` chains: parent body + child properties, renamed units."""
    sym = get_symbol(lib, name)
    ext = find(sym, "extends")
    if not ext:
        return sym
    parent = flatten(lib, str(ext[1]))
    out = [Sym("symbol"), name]
    child_props = {p[1]: p for p in find_all(sym, "property")}
    parent_props = {p[1]: p for p in find_all(parent, "property")}
    merged = dict(parent_props)
    merged.update(child_props)
    order = list(parent_props)
    for k in child_props:
        if k not in order:
            order.append(k)
    for x in parent:
        if not isinstance(x, list):
            continue
        head = str(x[0]) if isinstance(x[0], Sym) else None
        if head == "property":
            continue
        if head == "symbol":
            # unit: rename ParentName_a_b -> ChildName_a_b
            unit = [list(y) if isinstance(y, list) else y for y in x]
            uname = unit[1]
            suffix = uname[len(str(parent[1])):]
            unit[1] = name + suffix
            out.append(unit)
            continue
        out.append(x)
    # insert properties after the header flags (pin_numbers etc.)
    props = [merged[k] for k in order]
    insert_at = 2
    for i, x in enumerate(out[2:], start=2):
        if isinstance(x, list) and str(x[0]) in ("pin_numbers", "pin_names",
                                                 "exclude_from_sim", "in_bom",
                                                 "on_board"):
            insert_at = i + 1
    out[insert_at:insert_at] = props
    return out


def pins_of(sym):
    out = []
    for unit in find_all(sym, "symbol"):
        for p in find_all(unit, "pin"):
            at = find(p, "at")
            nm = find(p, "name")
            no = find(p, "number")
            out.append((str(no[1]), str(nm[1]), num(at[1]), num(at[2]),
                        num(at[3]), str(p[1]), str(p[2])))
    return out


def pads_of(path):
    with open(path) as f:
        fp = parse(f.read())[0]
    out = []
    for p in find_all(fp, "pad"):
        at = find(p, "at")
        size = find(p, "size")
        out.append((str(p[1]), str(p[2]), str(p[3]), num(at[1]), num(at[2]),
                    num(at[3]) if len(at) > 3 else 0.0,
                    num(size[1]), num(size[2])))
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "sym"):
        for lib, name in WANT:
            try:
                s = flatten(lib, name)
            except KeyError as e:
                print("MISSING", lib, name, e)
                continue
            ps = pins_of(s)
            print("== %s:%s  (%d pins)" % (lib, name, len(ps)))
            for no, nm, x, y, a, etype, style in sorted(
                    ps, key=lambda t: (len(t[0]), t[0])):
                print("   pin %-4s %-12s at (%6.2f,%6.2f) rot %3.0f  %s" %
                      (no, nm, x, y, a, etype))
    if which in ("all", "fp"):
        for f in sorted(os.listdir(FPDIR)):
            pads = pads_of(os.path.join(FPDIR, f))
            print("## %s  (%d pads)" % (f, len(pads)))
            for no, kind, shape, x, y, a, w, h in pads:
                print("   pad %-4s %-8s %-10s at (%7.2f,%7.2f) rot %3.0f size %.2fx%.2f"
                      % (no, kind, shape, x, y, a, w, h))
