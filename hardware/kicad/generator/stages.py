"""Per-stage snapshots of the board and schematic as the generators build them.

Every run of `gen_sch.py` and `kicad_build.py` drops the intermediate file it
holds at each stage into a sibling `stages/` directory of the artefact being
built - `hardware/kicad/stages/`, which is gitignored. Nothing reads them; they
exist so that "the silk placer put this label somewhere daft" or "the router
left this net open" can be opened in KiCad at the stage it happened rather than
inferred from the finished board, where six later stages have written over the
evidence.

Names are numbered so `ls` reads in pipeline order, and each writer clears only
its own numbers on the way in (`reset()`), because `make pcb-build` runs the two
generators as separate processes into the same directory - a writer that wiped
the whole directory would take the other's output with it.

Board snapshots go through `pcbnew.SaveBoard(..., aSkipSettings=True)`. The skip
is not an optimisation: without it, saving attaches and writes the board's
PROJECT, which is exactly the side effect `kicad_build.main()` already has to
undo once (see `read_project`/`restore_project` there). A stage snapshot is a
debugging convenience and must not be able to perturb the artefact - so it
writes the `.kicad_pcb` and nothing else, and the project files a stage board
needs in order to open with the right net classes and DRC rules are copied in
at the end of the run by `attach_projects()`.

`pcbnew` is imported lazily, inside the one function that needs it: gen_sch.py
runs under plain `python3` and importing this module must not require a KiCad
Python.
"""
import glob
import os
import shutil

DIRNAME = "stages"

# Copied alongside each stage BOARD, under the board's own basename, so KiCad
# binds them to it. The .kicad_prl is deliberately not copied: it is per-user
# GUI state, and a stale one only re-hides layers.
PROJECT_SUFFIXES = (".kicad_pro", ".kicad_dru")


def dir_for(ref_path):
    """The stages directory beside `ref_path`, created if need be."""
    d = os.path.join(os.path.dirname(os.path.abspath(ref_path)), DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def reset(ref_path, pattern):
    """Drop this writer's stages from a previous run.

    Stale files are worse than absent ones here: a stage that stops being
    emitted (a `--no-route` run, which skips routing and zones) would otherwise
    leave the previous full build's copy sitting in sequence, looking current.
    """
    d = dir_for(ref_path)
    for p in glob.glob(os.path.join(d, pattern)):
        os.remove(p)
    return d


def board(b, ref_path, name):
    """Snapshot an in-memory BOARD without disturbing it."""
    import pcbnew
    dst = os.path.join(dir_for(ref_path), name)
    was = b.GetFileName()
    try:
        pcbnew.SaveBoard(dst, b, aSkipSettings=True)
    finally:
        b.SetFileName(was)
    return dst


def copy(src, ref_path, name):
    """Snapshot a file already on disk."""
    dst = os.path.join(dir_for(ref_path), name)
    shutil.copyfile(src, dst)
    return dst


def write(text, ref_path, name):
    """Snapshot text a generator is about to write elsewhere."""
    dst = os.path.join(dir_for(ref_path), name)
    with open(dst, "w") as fh:
        fh.write(text)
    return dst


def attach_projects(ref_path, pattern="*.kicad_pcb"):
    """Give every stage board the project files KiCad binds by basename.

    Run at the END of a build, from the finished project: a stage board opened
    without one gets KiCad's defaults, which means no net classes and no custom
    DRC rules - so the board that was saved mid-route reports violations the
    real one does not, which is the opposite of a debugging aid.
    """
    d = dir_for(ref_path)
    stem = os.path.splitext(os.path.abspath(ref_path))[0]
    n = 0
    for pcb in sorted(glob.glob(os.path.join(d, pattern))):
        for suf in PROJECT_SUFFIXES:
            src = stem + suf
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.splitext(pcb)[0] + suf)
                n += 1
    return n
