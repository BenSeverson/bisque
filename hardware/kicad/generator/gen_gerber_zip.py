#!/usr/bin/env python3
"""Pack gerbers/ into jlcpcb/gerbers.zip — the third file a fab order uploads.

JLCPCB's order form takes one zip of gerbers + drill, and its SMT step takes
BOM.csv + CPL.csv. Those three are the whole upload, so they live in one
directory rather than leaving the zip to be built by hand at order time — which
is how a stale layer set reaches a fab.

    python3 generator/gen_gerber_zip.py            # write jlcpcb/gerbers.zip
    python3 generator/gen_gerber_zip.py --check    # verify it matches gerbers/

The zip is **byte-reproducible** for a given zlib: every entry is stamped with
a fixed date, stored in sorted order with fixed permissions, and deflated at a
fixed level. `--check` compares the unpacked members rather than the archive
bytes, because a different zlib (zlib-ng on Fedora) deflates identically
ordered input to different bytes.
A zip that carried real mtimes would differ on every single rebuild of an
otherwise byte-identical board, which would make it noise in `git diff` and
useless as evidence that the fab package matches the board — the same property
canonicalize.py exists to give the board file itself.

Everything in gerbers/ goes in, flat, including the drill map and the .gbrjob:
the job file is what carries the stack-up to the fab (see gen_pcb.STACKUP), and
a package without it declares no dielectric heights or epsilon_r.
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.dirname(HERE)
GERBERS = os.path.join(KICAD, "gerbers")
ZIP = os.path.join(KICAD, "jlcpcb", "gerbers.zip")

# Fixed stamp for every entry. Zip's DOS date cannot encode 1970, and 1980-01-01
# is the epoch of that format — the conventional choice for reproducible zips.
EPOCH = (1980, 1, 1, 0, 0, 0)
SUFFIXES = (".gbr", ".gbl", ".gbo", ".gbp", ".gbs", ".gtl", ".gto", ".gtp",
            ".gts", ".g1", ".g2", ".gm1", ".gbrjob", ".drl")


def members():
    """-> sorted [(arcname, absolute path)] of everything a fab reads."""
    if not os.path.isdir(GERBERS):
        sys.exit("no gerbers/ — run `make pcb-fab` first")
    names = sorted(n for n in os.listdir(GERBERS)
                   if n.endswith(SUFFIXES) and
                   os.path.isfile(os.path.join(GERBERS, n)))
    if not names:
        sys.exit("gerbers/ has no gerber or drill files — run `make pcb-fab`")
    return [(n, os.path.join(GERBERS, n)) for n in names]


def build(dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for arcname, path in members():
            info = zipfile.ZipInfo(arcname, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16       # not the umask of whoever ran it
            info.create_system = 3                 # unix, so the value above is read
            with open(path, "rb") as fh:
                z.writestr(info, fh.read(), compresslevel=9)


def stale(path):
    """None if the zip at `path` holds exactly gerbers/, else the first reason.

    Compares what a fab unpacks - member names and order, each member's bytes,
    and the fixed stamp - not the archive bytes. Deflate output is not stable
    across zlib builds: Fedora's zlib-ng compresses the same input to
    different bytes than stock zlib, so a byte compare of a rebuild failed on
    any such machine while every member was identical.
    """
    want = members()
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if names != [arc for arc, _ in want]:
            return "member list differs"
        for info, (arc, src) in zip(infos, want):
            if info.date_time != EPOCH or info.external_attr != 0o644 << 16:
                return "%s: date or permissions differ" % arc
            with open(src, "rb") as fh:
                if z.read(info) != fh.read():
                    return "%s differs" % arc
    return None


def main(argv):
    checking = "--check" in argv
    if checking:
        if not os.path.exists(ZIP):
            print("check_gerber_zip: %s missing — run `make pcb-fab`"
                  % os.path.relpath(ZIP, KICAD))
            return 1
        why = stale(ZIP)
        if why:
            print("check_gerber_zip: %s does not match gerbers/ (%s) — it is "
                  "stale; run `make pcb-fab`" % (os.path.relpath(ZIP, KICAD), why))
            return 1
        with zipfile.ZipFile(ZIP) as z:
            print("check_gerber_zip: OK — %s matches gerbers/ (%d files)"
                  % (os.path.relpath(ZIP, KICAD), len(z.namelist())))
        return 0

    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    build(ZIP)
    with zipfile.ZipFile(ZIP) as z:
        total = sum(i.file_size for i in z.infolist())
        print("wrote %s — %d files, %d KB in, %d KB zipped"
              % (os.path.relpath(ZIP, KICAD), len(z.namelist()),
                 total // 1024, os.path.getsize(ZIP) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
