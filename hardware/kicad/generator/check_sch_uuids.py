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

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def uuids(path):
    return set(UUID.findall(open(path).read()))


def main(sch):
    before = uuids(sch)
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, os.path.basename(sch))
        shutil.copy(sch, copy)
        # kicad-cli attaches a project to whatever it loads; hand it the real
        # one so the round-trip is the one a user would get, not a default.
        pro = os.path.splitext(sch)[0] + ".kicad_pro"
        if os.path.exists(pro):
            shutil.copy(pro, os.path.join(tmp, os.path.basename(pro)))
        subprocess.run(["kicad-cli", "sch", "upgrade", "--force", copy],
                       check=True, capture_output=True)
        after = uuids(copy)
    minted, lost = sorted(after - before), sorted(before - after)
    for u in minted:
        print("MINTED BY KICAD: %s" % u)
    for u in lost:
        print("DROPPED: %s" % u)
    print("%d uuids before, %d after; %d minted, %d dropped"
          % (len(before), len(after), len(minted), len(lost)))
    if minted or lost:
        sys.exit("SCH UUID ROUND-TRIP: FAIL - the generator must emit every "
                 "uuid KiCad expects, or a save will re-roll these")
    print("SCH UUID ROUND-TRIP: PASS")


if __name__ == "__main__":
    main(sys.argv[1])
