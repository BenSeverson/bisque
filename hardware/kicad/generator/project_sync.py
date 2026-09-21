"""The schematic's root uuid, and keeping the .kicad_pro in step with it.

Split out of gen_sch.py for one reason: gen_sch.py runs the schematic fuse
planner at import time (`fuse_plan()` at module level, ~52 s on a contested
plan), and kicad_build.py imported the module only to call sync_project() -
so every board build, `--no-route` fast path and router probe paid for a
schematic plan it never used, on top of the one gen_sch.py's own run had
just computed. This module imports nothing but the standard library.
"""
import json
import os
import uuid

NS = uuid.UUID("7c9b1f5e-4a4b-4d1a-9c33-bisque00pcb0".replace("bisque00pcb0", "1234567890ab"))
ROOT = str(uuid.uuid5(NS, "root-sheet"))
PROJECT = "bisque-controller"


def sync_project(sch_path):
    """Point the .kicad_pro's root-sheet entry at the schematic we just wrote.

    KiCad records the root sheet under `schematic.top_level_sheets`, and it
    writes that block itself the first time anything touches the project -
    which means the working tree grows an unexplained diff after a regen that
    nobody asked for. Worse, *what* it writes depends on who wrote it: the GUI
    knows the schematic's real root uuid, while `kicad-cli pcb` fills
    all-zeros because the PCB tooling never loads a schematic and has no uuid
    to record. Two tools, two answers, and the file flips between them.

    So it is derived here instead, from the same ROOT constant the schematic's
    own `(uuid ...)` comes from. Whoever opens the project next finds the
    entry already correct and leaves it alone - verified: kicad-cli only ever
    *adds* the block when it is missing, and preserves a populated one.

    The rewrite is a whole-file json round-trip, which is safe because KiCad's
    own writer emits plain 2-space-indented JSON: reading and re-dumping the
    untouched file reproduces it byte for byte, so this cannot churn
    formatting the way a hand-rolled patch would.
    """
    pro = os.path.splitext(sch_path)[0] + ".kicad_pro"
    if not os.path.exists(pro):
        return None                      # nothing to keep in step with
    with open(pro) as fh:
        doc = json.load(fh)
    want = [{"filename": os.path.basename(sch_path),
             "name": os.path.splitext(os.path.basename(sch_path))[0],
             "uuid": ROOT}]
    if doc.get("schematic", {}).get("top_level_sheets") == want:
        return False
    doc.setdefault("schematic", {})["top_level_sheets"] = want
    with open(pro, "w") as fh:
        fh.write(json.dumps(doc, indent=2) + "\n")
    return True
