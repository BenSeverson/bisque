#!/usr/bin/env python3
"""Route what you ask for, over the live board, leaving everything else alone.

    route.py [--nets A,B] [--router freerouting|inhouse] [--jar X] board.kicad_pcb

Targets are the nets named with --nets, or - with none - every net that
has unconnected items (read from KiCad's own DRC). Named nets first have
their UNLOCKED copper ripped up. Every track and via not on a target net
is fixed for the duration of the run: neither router may move it, and the
board file keeps every uuid and lock it had.

inhouse (default): router.py's A* over a model built from the board - pads
with their nets, existing copper as fixed obstacles - routing only the
targets. About ten seconds a net. Signal nets only: a GND pad is already
joined by the outer pours' thermal spokes, and a new +3V3 pad wants one via
to the In2.Cu plane, which is a two-second job in the GUI.

freerouting (--router freerouting, EXPERIMENTAL): the board goes out as a
Specctra DSN with every non-target net in a `frozen` class that Freerouting
is told to ignore (-inc); the session comes back into a SCRATCH copy and
only the target nets' copper is lifted from it onto the real board, so
untouched copper is identical by construction. On this board Freerouting
reads the fixed copper as hundreds of violations and spends four minutes a
pass without converging (2026-10-06, v2.3.0); it is kept as a backend for
boards it handles, not as the default. Needs ~/freerouting*.jar or
$FREEROUTING_JAR.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import wx
    _app = wx.App(False)
except ImportError:
    pass
import pcbnew

import router as R
from gen_pcb import ROUTE_ORDER, SIG_W, PLANE_NETS, FID_KEEPOUT, FANOUT
from kicad_build import V, MM, LAYER, resort_to_kicad_order, read_project, restore_project

FROZEN_CLASS = "frozen"
_REMOVED = []


def find_jar(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("FREEROUTING_JAR")
    if env and os.path.isfile(env):
        return env
    cands = sorted(glob.glob(os.path.expanduser("~/freerouting*.jar")), reverse=True)
    return cands[0] if cands else None


# ------------------------------------------------------------------ targets
def unconnected_nets(board_path):
    """Nets with unconnected items, per kicad-cli's DRC."""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.splitext(os.path.basename(board_path))[0]
        for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
            src = os.path.splitext(board_path)[0] + ext
            if os.path.exists(src):
                shutil.copy(src, os.path.join(tmp, base + ext))
        rpt = os.path.join(tmp, "drc.rpt")
        subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "-o", rpt,
                        os.path.join(tmp, base + ".kicad_pcb")],
                       check=True, capture_output=True)
        text = open(rpt).read()
    nets = set()
    i = text.find("[unconnected_items]")
    while i >= 0:
        j = text.find("\n[", i + 1)
        block = text[i:j if j > 0 else len(text)]
        for m in re.finditer(r"@\([^)]*\): [^\n]*?\[([^\]]+)\]", block):
            nets.add(m.group(1))
        i = text.find("[unconnected_items]", i + 1)
    return sorted(n for n in nets if n and n != "<no net>")


def _pad_hits(board, pt, net):
    """The pad at point `pt` on `net`, or None."""
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net and pad.GetBoundingBox().Contains(pt):
                return fp, pad
    return None


def is_fanout_stub(board, t):
    """A track leaving a fine-pitch pad straight out of its own row.

    gen_pcb.FANOUT names the parts whose pads are finer than the in-house
    router's grid; the only way onto such a pad is the short escape the old
    build drew for it, and ripping that up strands the pad. The stub counts
    as part of the pad: it survives a rip-up and the routers treat its far
    end as the terminal.
    """
    if t.Type() != pcbnew.PCB_TRACE_T:
        return False
    net = t.GetNetname()
    for pt in (t.GetStart(), t.GetEnd()):
        hit = _pad_hits(board, pt, net)
        if hit and hit[0].GetReference() in FANOUT:
            return True
    return False


def rip_up(board, nets, keep_stubs=True):
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() in nets and not t.IsLocked():
            if keep_stubs and is_fanout_stub(board, t):
                continue
            board.Remove(t)
            _REMOVED.append(t)
            n += 1
    return n


# -------------------------------------------------------------- freerouting
def _freeze_classes(dsn_text, targets):
    """Move every non-target net into a `frozen` class Freerouting ignores."""
    out, pos = [], 0
    for m in re.finditer(r"\(class\s+(\S+)", dsn_text):
        start = m.start()
        # matching close paren of this (class ...) block
        depth, k = 0, start
        while True:
            c = dsn_text[k]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        block = dsn_text[start:k + 1]
        head_end = block.find("(", 1)
        head = block[:head_end]
        body = block[head_end:-1]
        name, nets = head.split()[1], head.split()[2:]
        keep = [n for n in nets if n in targets]
        freeze = [n for n in nets if n not in targets]
        rebuilt = ""
        if keep:
            rebuilt += "(class %s %s\n%s)" % (name, " ".join(keep), body)
        if freeze:
            rebuilt += "\n    (class %s_%s %s\n%s)" % (FROZEN_CLASS, name, " ".join(freeze), body)
        out.append(dsn_text[pos:start])
        out.append(rebuilt)
        pos = k + 1
    out.append(dsn_text[pos:])
    return "".join(out)


def route_freerouting(board, board_path, targets, jar, passes=20):
    tmp = tempfile.mkdtemp(prefix="route-")
    dsn, ses = os.path.join(tmp, "board.dsn"), os.path.join(tmp, "board.ses")
    # Fixed for the export only: the real board's locks are never changed.
    was = {t.m_Uuid.AsString(): t.IsLocked() for t in board.GetTracks()}
    for t in board.GetTracks():
        if t.GetNetname() not in targets:
            t.SetLocked(True)
    assert pcbnew.ExportSpecctraDSN(board, dsn), "DSN export failed"
    for t in board.GetTracks():
        t.SetLocked(was[t.m_Uuid.AsString()])
    text = _freeze_classes(open(dsn).read(), set(targets))
    frozen = sorted(set(re.findall(r"\(class (%s_\S+)" % FROZEN_CLASS, text)))
    open(dsn, "w").write(text)
    cmd = ["java", "-jar", jar, "--gui.enabled=false",
           "--usage_and_diagnostic_data.disable_analytics=true",
           "-de", dsn, "-do", ses, "-mp", str(passes), "-dct", "0", "-l", "en"]
    if frozen:
        cmd += ["-inc", ",".join(frozen)]
    print("  freerouting: %d target net(s), %d class(es) frozen" % (len(targets), len(frozen)))
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    log = os.path.join(tmp, "freerouting.log")
    open(log, "w").write(p.stdout + p.stderr)
    if p.returncode != 0 or not os.path.exists(ses):
        sys.exit("freerouting failed (rc %d) - log: %s" % (p.returncode, log))
    for line in p.stdout.splitlines():
        if "Auto-routing stage completed" in line or "unrouted" in line.lower():
            print("  " + line.split("INFO", 1)[-1].strip())
    print("  freerouting finished in %.0f s" % (time.time() - t0))
    # Import into a scratch copy; lift only the targets' copper onto the board.
    scratch = pcbnew.LoadBoard(board_path)
    rip_up(scratch, set(targets))
    if not pcbnew.ImportSpecctraSES(scratch, ses):
        sys.exit("SES import failed - session: %s" % ses)
    nets = {}
    added = 0
    for t in scratch.GetTracks():
        n = t.GetNetname()
        if n not in targets:
            continue
        if n not in nets:
            nets[n] = board.FindNet(n)
        if t.Type() == pcbnew.PCB_VIA_T:
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(t.GetPosition())
            v.SetViaType(t.GetViaType())
            v.SetDrill(t.GetDrill())
            v.SetWidth(t.GetWidth())
            v.SetLayerPair(t.TopLayer(), t.BottomLayer())
            v.SetNet(nets[n])
            board.Add(v)
        elif t.Type() == pcbnew.PCB_TRACE_T:
            s = pcbnew.PCB_TRACK(board)
            s.SetStart(t.GetStart())
            s.SetEnd(t.GetEnd())
            s.SetWidth(t.GetWidth())
            s.SetLayer(t.GetLayer())
            s.SetNet(nets[n])
            board.Add(s)
        else:
            continue
        added += 1
    shutil.rmtree(tmp, ignore_errors=True)
    return added


# ------------------------------------------------------------------ inhouse
def build_model(board, targets):
    """router.Router over the board: pads with nets, all copper fixed."""
    eb = board.GetBoardEdgesBoundingBox()
    r = R.Router(pcbnew.ToMM(eb.GetLeft()), pcbnew.ToMM(eb.GetTop()),
                 pcbnew.ToMM(eb.GetRight()), pcbnew.ToMM(eb.GetBottom()))
    pad_pos = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for z in fp.Zones():
            if z.GetIsRuleArea():
                bb = z.GetBoundingBox()
                r.add_keepout(pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
                              pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom()))
        if ref.startswith("FID"):
            cx, cy = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
            r.add_keepout(cx - FID_KEEPOUT, cy - FID_KEEPOUT, cx + FID_KEEPOUT, cy + FID_KEEPOUT)
        for pad in fp.Pads():
            ls = pad.GetLayerSet()
            on_f, on_b = ls.Contains(pcbnew.F_Cu), ls.Contains(pcbnew.B_Cu)
            if not (on_f or on_b):
                continue
            layers = tuple(l for l, on in ((0, on_f), (1, on_b)) if on)
            bb = pad.GetBoundingBox()
            cx, cy = pcbnew.ToMM(bb.GetCenter().x), pcbnew.ToMM(bb.GetCenter().y)
            w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
            num = str(pad.GetNumber())
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or num == "":
                net = None
            else:
                net = pad.GetNetname() or "__nc_%s_%s" % (ref, num)
            drill = drill_len = drill_ang = 0.0
            hole = None
            if pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                ds = pad.GetDrillSize()
                dw, dh = pcbnew.ToMM(ds.x), pcbnew.ToMM(ds.y)
                drill, drill_len = min(dw, dh), max(dw, dh)
                drill_ang = pad.GetOrientationDegrees() + (0.0 if dw >= dh else 90.0)
                hole = (pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y))
            r.add_pad(net, layers, cx, cy, w, h,
                      circle=pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE,
                      drill=drill, drill_len=drill_len, drill_ang=drill_ang, hole=hole)
            if num and net:
                pad_pos.setdefault((ref, num), []).append((cx, cy, layers, w * h))
    layer_of = {pcbnew.F_Cu: 0, pcbnew.B_Cu: 1}
    for t in board.GetTracks():
        n = t.GetNetname()
        if t.Type() == pcbnew.PCB_VIA_T:
            r.add_via(n, pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y),
                      record=False, fixed=True)
        elif t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() in layer_of:
            r.add_seg(n, layer_of[t.GetLayer()],
                      pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y),
                      pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y),
                      pcbnew.ToMM(t.GetWidth()), record=False, fixed=True)
    return r, pad_pos


def route_inhouse(board, targets):
    planes = [n for n in targets if n in PLANE_NETS]
    if planes:
        sys.exit("inhouse router does not route plane nets (%s): a GND pad is "
                 "joined by the outer pours, a +3V3 pad needs one via to In2.Cu - "
                 "place it in the GUI, or try --router freerouting"
                 % ", ".join(planes))
    r, pad_pos = build_model(board, targets)
    width = dict(ROUTE_ORDER)
    layer_of = {pcbnew.F_Cu: 0, pcbnew.B_Cu: 1}
    failed = []
    for net in targets:
        segs = [t for t in board.GetTracks()
                if t.GetNetname() == net and t.Type() == pcbnew.PCB_TRACE_T
                and t.GetLayer() in layer_of]
        terms = []
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname() != net:
                    continue
                spots = pad_pos.get((fp.GetReference(), str(pad.GetNumber())), [])
                # Copper already leaving this pad: follow it segment by
                # segment to its far end and route to THAT. The near end of
                # a fine-pitch escape is inside the fanout bundle and has no
                # free grid neighbour; the far end was placed to have one.
                stub = None
                bb = pad.GetBoundingBox()
                for t in segs:
                    if bb.Contains(t.GetStart()) and not bb.Contains(t.GetEnd()):
                        stub = (t.GetEnd(), t.GetLayer(), t)
                    elif bb.Contains(t.GetEnd()) and not bb.Contains(t.GetStart()):
                        stub = (t.GetStart(), t.GetLayer(), t)
                    if stub:
                        break
                used = set()
                while stub:
                    pt, lay, cur = stub
                    used.add(cur.m_Uuid.AsString())
                    nxt = None
                    for t in segs:
                        if t.m_Uuid.AsString() in used or t.GetLayer() != lay:
                            continue
                        if t.GetStart() == pt:
                            nxt = (t.GetEnd(), t.GetLayer(), t)
                        elif t.GetEnd() == pt:
                            nxt = (t.GetStart(), t.GetLayer(), t)
                        if nxt:
                            break
                    if nxt is None:
                        break
                    stub = nxt
                if stub:
                    # FIRST in the order: the router grows from terminal 0,
                    # and this one is on the copper `extra` seeds it with,
                    # so every later terminal is routed to one connected set
                    # rather than to whichever source happened to be nearer.
                    terms.append((pcbnew.ToMM(stub[0].x), pcbnew.ToMM(stub[0].y),
                                  (layer_of[stub[1]],), 0.0, -1))
                    continue
                for (cx, cy, layers, area) in spots:
                    terms.append((cx, cy, layers, area, 0 if fp.GetReference() == "U1" else 1))
        seen = {}
        for t in terms:
            seen.setdefault((round(t[0], 3), round(t[1], 3)), t)
        terms = [(t[0], t[1], t[2]) for t in sorted(seen.values(), key=lambda t: (t[4], -t[3]))]
        # Copper the net already has (kept stubs, locked seeds) is a source
        # the router may grow from, sampled along its length.
        extra = []
        for t in segs:
            a = (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y))
            b = (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y))
            d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            n = max(1, int(d / 0.4))
            for k in range(n + 1):
                f = k / float(n)
                extra.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f,
                              layer_of[t.GetLayer()]))
        try:
            r.route(net, terms, width.get(net, SIG_W), extra_srcs=extra)
            print("  routed %s" % net)
        except RuntimeError as e:
            print("  !! %s: %s" % (net, e))
            failed.append(net)
    r._memo = {}
    r._memo_net = None
    r.miter_corners()
    nets = {}
    for s in r.result_tracks:
        if s.fixed:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(V(s.x1, s.y1))
        t.SetEnd(V(s.x2, s.y2))
        t.SetWidth(MM(s.w))
        t.SetLayer(LAYER[s.layer])
        t.SetNet(nets.setdefault(s.net, board.FindNet(s.net)))
        board.Add(t)
    for (net, x, y, fixed) in r.result_vias:
        if fixed:
            continue
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(V(x, y))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetDrill(MM(R.VIA_DRILL))
        v.SetWidth(MM(R.VIA_DIA))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets.setdefault(net, board.FindNet(net)))
        board.Add(v)
    return failed


# --------------------------------------------------------------------- main
def main(argv):
    nets, router, jar, paths = None, None, None, []
    it = iter(argv)
    for a in it:
        if a == "--nets":
            nets = [n for n in next(it).split(",") if n]
        elif a == "--router":
            router = next(it)
        elif a == "--jar":
            jar = next(it)
        elif a.startswith("-"):
            sys.exit(__doc__)
        else:
            paths.append(a)
    out = os.path.abspath(paths[0] if paths else "bisque-controller.kicad_pcb")
    jar = find_jar(jar)
    if router is None:
        router = "inhouse"
    if router == "freerouting" and not jar:
        sys.exit("no Freerouting jar found: set FREEROUTING_JAR or pass --jar")
    if router == "freerouting":
        print("  freerouting backend is experimental on this board; see route.py")
    board = pcbnew.LoadBoard(out)
    if nets:
        known = {str(k) for k in board.GetNetsByName().keys()}
        bad = [n for n in nets if n not in known]
        if bad:
            sys.exit("no such net(s) on the board: %s" % ", ".join(bad))
        n = rip_up(board, set(nets))
        print("ripped up %d unlocked track(s)/via(s) on %s" % (n, ", ".join(nets)))
        targets = list(nets)
    else:
        targets = unconnected_nets(out)
        if not targets:
            print("nothing to route: no unconnected items")
            return
        print("unconnected: %s" % ", ".join(targets))
    before = sum(1 for _ in board.GetTracks())
    if router == "freerouting":
        route_freerouting(board, out, targets, jar)
        failed = []
    elif router == "inhouse":
        failed = route_inhouse(board, targets)
    else:
        sys.exit("unknown router %r" % router)
    after = sum(1 for _ in board.GetTracks())
    print("added %d track(s)/via(s)" % (after - before))
    project_before = read_project(out)
    board.SetFileName(out)
    pcbnew.SaveBoard(out, board)
    rpt = os.path.splitext(out)[0] + "-drc.rpt"
    subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones", "--save-board",
                    "--severity-all", "--all-track-errors", "-o", rpt, out],
                    check=True, capture_output=True)
    resort_to_kicad_order(out)
    restore_project(project_before)
    text = open(rpt).read()
    for n, what in re.findall(r"\*\* Found (\d+) (\w[\w ]*?) \*\*", text):
        print("  %s: %s" % (what.strip(), n))
    left = unconnected_nets(out)
    if left:
        print("  still unconnected: %s" % ", ".join(left))
    if failed or left:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
