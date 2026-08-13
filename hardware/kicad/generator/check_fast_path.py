#!/usr/bin/env python3
"""Prove `kicad_build.py --no-route` cannot diverge from a full rebuild.

The fast path exists so that a silkscreen, 3D-model or title-block change
costs ~100 s instead of ~421 s. That is only worth having if its output is
the output a full build would have produced: a fast path that can drift lets
someone sign off silk against a board the fab will never receive. So the
invariant is byte-identity, and this script demonstrates it rather than
asserting it.

Three boards are built in scratch directories, and all three must come out
byte-identical:

  full      a complete rebuild from design.py, routing and all
  fast      --no-route over a copy of `full`
  fast'     --no-route over a copy of `full` whose cosmetics have been
            deliberately vandalised first - every reference designator
            shifted and resized, every board text moved, the title block
            overwritten, U1's 3D model flung off the board

`fast'` is the one that matters. `fast` alone would only show the fast path
is a fixed point of its own output; `fast'` shows the loaded board's
cosmetic state cannot leak into the result, which is the property that makes
"re-derive" honest. It is also the regression test for the specific bug the
design avoids by deleting and re-adding footprints rather than editing them:
a placer re-run over its own previous output does not see the same inputs a
fresh build gives it.

The committed board is compared too, so a stale checkout is reported as
such instead of being silently used as the reference.

Costs one full build (~7 minutes). Not part of `make pcb-check`; run it via
`make pcb-cosmetic-verify` when the build pipeline changes.

Usage: <kicad-python> check_fast_path.py [reference.kicad_pcb]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD_DIR = os.path.dirname(HERE)
BUILD = os.path.join(HERE, "kicad_build.py")
BOARD = "bisque-controller.kicad_pcb"
PROJECT = "bisque-controller.kicad_pro"


def run(args, cwd):
    """One kicad_build.py invocation. Returns wall-clock seconds."""
    t0 = time.time()
    p = subprocess.run([sys.executable, BUILD] + args, cwd=cwd,
                       capture_output=True, text=True)
    dt = time.time() - t0
    if p.returncode != 0:
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
        sys.exit("kicad_build.py %s failed (rc=%d)" % (" ".join(args),
                                                       p.returncode))
    return dt


def workdir(root, name, seed=None):
    """A scratch directory holding a board to build in.

    The .kicad_pro is copied alongside because kicad-cli attaches a project
    to the board it loads; building beside a different one is a needless
    difference between this harness and a real `make pcb-build`.
    """
    d = os.path.join(root, name)
    os.makedirs(d)
    src = os.path.join(KICAD_DIR, PROJECT)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(d, PROJECT))
    if seed:
        shutil.copy(seed, os.path.join(d, BOARD))
    return d


def vandalise(path):
    """Wreck every cosmetic the fast path claims to re-derive.

    Nothing here touches copper, placement or connectivity, so
    `verify_reusable()` still accepts the board - which is the point: this is
    a board the fast path considers reusable and whose cosmetics are all
    wrong. If any of it survives into the output, the fast path is preserving
    rather than deriving.
    """
    import pcbnew
    board = pcbnew.LoadBoard(path)
    tb = pcbnew.TITLE_BLOCK()
    tb.SetTitle("WRONG TITLE")
    tb.SetRevision("Z")
    tb.SetDate("1999-01-01")
    tb.SetCompany("Nobody")
    tb.SetComment(0, "stale comment that must not survive")
    board.SetTitleBlock(tb)

    dx, dy = pcbnew.FromMM(3.7), pcbnew.FromMM(-2.9)
    for fp in board.GetFootprints():
        t = fp.Reference()
        p = t.GetPosition()
        t.SetPosition(pcbnew.VECTOR2I(p.x + dx, p.y + dy))
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.7), pcbnew.FromMM(1.7)))
        t.SetTextThickness(pcbnew.FromMM(0.3))
        for it in fp.GraphicalItems():
            if it.GetLayer() == pcbnew.F_SilkS and hasattr(it, "GetText"):
                q = it.GetPosition()
                it.SetPosition(pcbnew.VECTOR2I(q.x - dx, q.y - dy))
        # Models() hands back copies, so the list is rebuilt to change one -
        # the same dance MODEL_OFFSET does in kicad_build.py.
        old = [(m.m_Filename, m.m_Scale, m.m_Rotation) for m in fp.Models()]
        if old:
            fp.Models().clear()
            for fname, scale, rot in old:
                nm = pcbnew.FP_3DMODEL()
                nm.m_Filename = fname
                nm.m_Scale = scale
                nm.m_Rotation = rot
                nm.m_Offset = pcbnew.VECTOR3D(42.0, -42.0, 13.0)
                fp.Models().push_back(nm)

    for d in board.GetDrawings():
        if hasattr(d, "GetText") and d.GetLayer() == pcbnew.F_SilkS:
            q = d.GetPosition()
            d.SetPosition(pcbnew.VECTOR2I(q.x + dx, q.y + dy))
    pcbnew.SaveBoard(path, board)


def main(argv):
    reference = os.path.abspath(argv[0]) if argv else os.path.join(KICAD_DIR,
                                                                  BOARD)
    root = tempfile.mkdtemp(prefix="bisque-fastpath-")
    fails = []

    def expect(ok, label):
        print("  %-52s %s" % (label, "ok" if ok else "FAIL"))
        if not ok:
            fails.append(label)

    print("check_fast_path: building in %s" % root)

    d_full = workdir(root, "full")
    t_full = run([BOARD], d_full)
    full = os.path.join(d_full, BOARD)
    print("  full rebuild                                       %6.1f s" % t_full)

    d_fast = workdir(root, "fast", seed=full)
    t_fast = run(["--no-route", BOARD], d_fast)
    fast = os.path.join(d_fast, BOARD)
    print("  --no-route over that board                         %6.1f s" % t_fast)

    d_vand = workdir(root, "fast-vandalised", seed=full)
    vand = os.path.join(d_vand, BOARD)
    vandalise(vand)
    dirty = open(vand, "rb").read() != open(full, "rb").read()
    t_vand = run(["--no-route", BOARD], d_vand)
    print("  --no-route over a vandalised board                 %6.1f s" % t_vand)

    a = open(full, "rb").read()
    b = open(fast, "rb").read()
    c = open(vand, "rb").read()

    expect(dirty, "vandalised board really differed going in")
    expect(a == b, "--no-route output == full rebuild, byte for byte")
    expect(a == c, "--no-route re-derives cosmetics it did not build")
    expect(os.path.exists(reference), "reference board exists")
    if os.path.exists(reference):
        expect(a == open(reference, "rb").read(),
               "committed board is what a full build produces")

    print("  speedup %.1fx (%.0f s -> %.0f s)"
          % (t_full / t_fast if t_fast else 0, t_full, t_fast))
    print("  -> %s" % ("PASS" if not fails else "FAIL"))
    if fails:
        print("  scratch boards kept for inspection: %s" % root)
        return 1
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
