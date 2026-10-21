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


def run_sync(cwd, board, extra=()):
    p = subprocess.run([sys.executable, SYNC] + list(extra) + [board], cwd=cwd,
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
    import re
    import pcbnew
    base_net = os.path.join(src_dir, base + ".net")

    def comp_block(text, ref):
        i = text.index('(ref "%s")' % ref)
        j = text.rfind("\n\t\t(comp", 0, i)
        depth, k = 0, j + 1
        while True:
            c = text[k]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        return j + 1, k + 1

    # 4. a part added in the schematic is added to the board, parked east of
    #    the outline, and the sync still succeeds.
    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        net = os.path.join(tmp, base + ".net")
        t = open(net).read()
        i, j = comp_block(t, "C30")
        blk = t[i:j].replace('(ref "C30")', '(ref "C999")')
        t = t[:j] + "\n" + blk + t[j:]
        open(net, "w").write(t)
        out = run_sync(tmp, b)
        bd = B.load(b)
        if "C999" not in bd.fps or bd.fps["C999"]["x"] <= bd.edge[2]:
            sys.exit("SYNC IDEMPOTENT: FAIL - added part C999 is not parked east of the board")
        if "+ C999" not in out:
            sys.exit("SYNC IDEMPOTENT: FAIL - the sync did not report adding C999")
        print("  4. added C999 is parked east of the outline (%.1f, %.1f)"
              % (bd.fps["C999"]["x"], bd.fps["C999"]["y"]))

    # 5. a renamed net re-nets its pads, keeps its copper and reports no
    #    copper as dead (the DRC pass propagates the new net onto it).
    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        net = os.path.join(tmp, base + ".net")
        t = open(net).read().replace('(name "/ct/ADE_CS")', '(name "/ct/ADE_CSX")')
        open(net, "w").write(t)
        before = sum(1 for x in B.load(b).tracks + B.load(b).vias if x["net"] == "ADE_CS")
        out = run_sync(tmp, b)
        bd = B.load(b)
        after = sum(1 for x in bd.tracks + bd.vias if x["net"] == "ADE_CSX")
        pads = [r for r, f in bd.fps.items() if "ADE_CSX" in f["pads"].values()]
        if not pads or after != before or "ADE_CS" in bd.nets:
            sys.exit("SYNC IDEMPOTENT: FAIL - renamed net: pads %s, copper %d -> %d"
                     % (pads, before, after))
        if "!!" in out and "ADE_CS" in out:
            sys.exit("SYNC IDEMPOTENT: FAIL - copper that followed the rename was reported dead")
        print("  5. ADE_CS -> ADE_CSX: %d pad(s) re-netted, %d copper item(s) followed, none reported dead"
              % (len(pads), after))

    # 6. a netlist pin the footprint has no pad for is a loud failure, not
    #    a connection that silently never reaches the board.
    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        net = os.path.join(tmp, base + ".net")
        t = open(net).read()
        i = t.index('(name "GND")')
        k = t.index("(node", i)
        t = t[:k] + '(node\n\t\t\t\t(ref "R44")\n\t\t\t\t(pin "7")\n\t\t\t)\n\t\t\t' + t[k:]
        open(net, "w").write(t)
        p = subprocess.run([sys.executable, SYNC, b], cwd=tmp, capture_output=True, text=True)
        if p.returncode == 0 or "R44" not in (p.stdout + p.stderr) or "7" not in (p.stdout + p.stderr):
            sys.exit("SYNC IDEMPOTENT: FAIL - R44 pin 7 (no such pad) did not fail the sync")
        print("  6. a netlist pin with no pad (R44.7) fails the sync by name")

    # 7. a board with no `generated` group is refused unless the one-time
    #    adoption is asked for explicitly: adopting means deleting every
    #    unlocked silk text, which must never happen by accident.
    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        board = pcbnew.LoadBoard(b)
        for g in list(board.Groups()):
            if g.GetName() == "generated":
                board.Remove(g)
        pcbnew.SaveBoard(b, board, True)
        p = subprocess.run([sys.executable, SYNC, b], cwd=tmp, capture_output=True, text=True)
        if p.returncode == 0 or "adopt" not in (p.stdout + p.stderr):
            sys.exit("SYNC IDEMPOTENT: FAIL - a board without the generated group was synced "
                     "without --adopt-legacy")
        run_sync(tmp, b, extra=["--adopt-legacy"])
        print("  7. no generated group: refused; --adopt-legacy re-creates it")

    # 8. a rule area the user drew is not the USB keepout and survives.
    with tempfile.TemporaryDirectory() as tmp:
        b = scratch(src_dir, base, tmp, synced=True)
        board = pcbnew.LoadBoard(b)
        ka = pcbnew.ZONE(board)
        ls = pcbnew.LSET()
        ls.addLayer(pcbnew.F_Cu)
        ka.SetLayerSet(ls)
        ka.SetIsRuleArea(True)
        ka.SetDoNotAllowZoneFills(True)
        ol = ka.Outline()
        ol.NewOutline()
        for (x, y) in [(30, 30), (34, 30), (34, 34), (30, 34)]:
            ol.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        ka.SetUuid(pcbnew.KIID("00000000-0000-4000-8000-00000000beef"))
        board.Add(ka)
        pcbnew.SaveBoard(b, board, True)
        run_sync(tmp, b)
        if "00000000-0000-4000-8000-00000000beef" not in open(b).read():
            sys.exit("SYNC IDEMPOTENT: FAIL - a user-drawn rule area was deleted by the sync")
        print("  8. a user-drawn rule area survives the sync")

    # 9. two sheet-local nets with the same short name are two nets; the
    #    netlist reader must refuse rather than merge them onto one board net.
    with tempfile.TemporaryDirectory() as tmp:
        import netlist as NL
        t = open(base_net).read()
        t = t.replace('(name "/ct/ADE_CS")', '(name "/ct/FB")', 1).replace('(name "SPI_MISO")', '(name "/power/FB")', 1)
        pth = os.path.join(tmp, "x.net")
        open(pth, "w").write(t)
        try:
            NL.load(pth)
            merged = True
        except SystemExit as e:
            merged = "FB" not in str(e)
        if merged:
            sys.exit("SYNC IDEMPOTENT: FAIL - /ct/FB and /power/FB were merged into one net")
        print("  9. sheet-local nets sharing a short name are refused by netlist.load()")
    print("SYNC IDEMPOTENT: PASS")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "bisque-controller.kicad_pcb")
