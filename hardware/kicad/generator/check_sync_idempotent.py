#!/usr/bin/env python3
"""Prove sync_board.py is a fixed point of its own output, and respects locks.

The sync re-derives the silk it owns from where the parts are, and must leave
everything a person authored alone. Three things are asserted on scratch
copies of the committed project, and all three cost one sync run each:

  1. idempotence - sync twice, the second output is byte-identical;
  2. a user's board text outside the `generated` group survives, even one
     whose string matches a generated legend ("GND");
  3. a LOCKED footprint whose schematic footprint changed is swapped in
     place: still locked, same position, same rotation, new footprint.

Replaces check_fast_path.py, whose byte-identity claim belonged to a
pipeline that rebuilt the board from nothing.

Usage: <kicad-python> check_sync_idempotent.py board.kicad_pcb
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SYNC = os.path.join(HERE, "sync_board.py")


def run_sync(cwd, board):
    p = subprocess.run([sys.executable, SYNC, board], cwd=cwd,
                       capture_output=True, text=True)
    if p.returncode != 0:
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
        sys.exit("sync_board.py failed in %s" % cwd)
    return p.stdout


def scratch(src_dir, base, tmp, synced=False):
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".net", ".net.stamp"):
        f = os.path.join(src_dir, base + ext)
        if os.path.exists(f):
            shutil.copy(f, os.path.join(tmp, base + ext))
    # No schematic in the scratch dir: sync_board.py then skips the
    # freshness check and reads the .net as handed to it, which is what lets
    # scenario 3 edit the netlist copy.
    b = os.path.join(tmp, base + ".kicad_pcb")
    if synced:
        # Scenarios 2 and 3 are about a board the sync already owns. On a
        # board that has never been synced the first run adopts EVERY silk
        # text as generated (the one-time migration off the old generator),
        # which is the opposite of what those scenarios test.
        run_sync(tmp, b)
    return b


def main(board_path):
    board_path = os.path.abspath(board_path)
    src_dir, fname = os.path.split(board_path)
    base = os.path.splitext(fname)[0]
    sys.path.insert(0, HERE)
    import board as B

    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp)
        run_sync(tmp, b)
        first = open(b, "rb").read()
        run_sync(tmp, b)
        second = open(b, "rb").read()
        if first != second:
            sys.exit("SYNC IDEMPOTENT: FAIL - the second sync changed the board")
        print("  1. second sync byte-identical (%d bytes)" % len(second))

    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        text = open(b).read()
        marker = ('\t(gr_text "GND"\n\t\t(at 30 30 0)\n\t\t(layer "F.SilkS")\n'
                  '\t\t(uuid "00000000-0000-4000-8000-00000000c0de")\n'
                  '\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n'
                  '\t\t\t\t(thickness 0.16)\n\t\t\t)\n\t\t)\n\t)\n')
        i = text.rfind("\n\t(segment")
        text = text[:i + 1] + marker + text[i + 1:]
        open(b, "w").write(text)
        run_sync(tmp, b)
        bd = B.load(b)
        mine = [t for t in bd.texts if t["uuid"] == "00000000-0000-4000-8000-00000000c0de"]
        if len(mine) != 1 or (mine[0]["x"], mine[0]["y"]) != (30.0, 30.0):
            sys.exit("SYNC IDEMPOTENT: FAIL - a user text outside the generated "
                     "group was deleted or moved")
        gnd = [t for t in bd.texts if t["text"] == "GND"]
        print("  2. user text 'GND' outside the group survived (%d GND texts on "
              "the board)" % len(gnd))

    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        net = os.path.join(tmp, base + ".net")
        ref, old_fp, new_fp = "C30", "C_0805_2012Metric", "C_0603_1608Metric"
        before = B.load(b).fps[ref]
        text = open(b).read()
        # lock C30 by hand
        key = '(property "Reference" "%s"' % ref
        i = text.index(key)
        j = text.rfind("\t(footprint ", 0, i)
        k = text.index("\n", j)
        text = text[:k + 1] + "\t\t(locked yes)\n" + text[k + 1:]
        open(b, "w").write(text)
        ntext = open(net).read()
        i = ntext.index('(ref "%s")' % ref)
        j = ntext.index(old_fp, i)
        ntext = ntext[:j] + new_fp + ntext[j + len(old_fp):]
        j = ntext.index(old_fp, i)          # the Footprint field, too
        ntext = ntext[:j] + new_fp + ntext[j + len(old_fp):]
        open(net, "w").write(ntext)
        out = run_sync(tmp, b)
        after = B.load(b).fps[ref]
        ok = (after["fpname"] == new_fp and after["locked"]
              and abs(after["x"] - before["x"]) < 1e-6
              and abs(after["y"] - before["y"]) < 1e-6
              and abs(after["rot"] - before["rot"]) < 1e-6
              and "~ %s now %s" % (ref, new_fp) in out)
        if not ok:
            sys.exit("SYNC IDEMPOTENT: FAIL - locked %s was not swapped in place "
                     "(%s, locked=%s, at %.3f,%.3f)" % (ref, after["fpname"],
                                                       after["locked"], after["x"], after["y"]))
        print("  3. locked %s swapped %s -> %s in place, still locked"
              % (ref, old_fp, new_fp))
    print("SYNC IDEMPOTENT: PASS")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
