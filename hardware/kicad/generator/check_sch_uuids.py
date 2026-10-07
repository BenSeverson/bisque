"""Round-trip uuid check: KiCad must not invent a uuid the generator didn't write.

gen_sch.py derives every uuid it emits from stable content (uuid5 of the part
key and pin number), so a regen of an unchanged design is byte-identical. That
guarantee only holds for items the generator actually gives a uuid to: KiCad
mints a fresh RANDOM v4 for anything it loads without one, and writes it back
on the first save. The result is a schematic that churns on every round-trip
for reasons nothing in the generator can see.

That is not hypothetical. A SCH_SYMBOL owns a SCH_PIN for every pin of the
LIBRARY symbol, not just the ones its own unit draws, so emitting the unit
view's pins left U10's two 74LVC1G123 units short 8 pin uuids between them -
silently, until KiCad was asked to save the file.

Usage: python3 check_sch_uuids.py <schematic.kicad_sch>
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def uuids(path):
    return set(UUID.findall(open(path).read()))


def main(sch):
    import netlist
    files = netlist.sheet_files(sch)
    base = os.path.dirname(os.path.abspath(sch))
    before = set()
    for f in files:
        before |= uuids(f)
    with tempfile.TemporaryDirectory() as tmp:
        # The whole sheet tree, in its own layout, so the root can find its
        # sub-sheets; kicad-cli attaches a project to whatever it loads, so
        # hand it the real one and the round-trip is the one a user gets.
        for f in files:
            rel = os.path.relpath(f, base)
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(f, dst)
        pro = os.path.splitext(sch)[0] + ".kicad_pro"
        if os.path.exists(pro):
            shutil.copy(pro, os.path.join(tmp, os.path.basename(pro)))
        after = set()
        for f in files:
            copy = os.path.join(tmp, os.path.relpath(f, base))
            subprocess.run(["kicad-cli", "sch", "upgrade", "--force", copy],
                           check=True, capture_output=True)
            after |= uuids(copy)
    minted, lost = sorted(after - before), sorted(before - after)
    for u in minted:
        print("MINTED BY KICAD: %s" % u)
    for u in lost:
        print("DROPPED: %s" % u)
    print("%d uuids before, %d after across %d sheet file(s); %d minted, %d dropped"
          % (len(before), len(after), len(files), len(minted), len(lost)))
    if minted or lost:
        sys.exit("SCH UUID ROUND-TRIP: FAIL - the generator must emit every "
                 "uuid KiCad expects, or a save will re-roll these")
    print("SCH UUID ROUND-TRIP: PASS")


if __name__ == "__main__":
    main(sys.argv[1])
