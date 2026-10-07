# Board-owns-layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `bisque-controller.kicad_sch` and `bisque-controller.kicad_pcb` the sources of truth, with the generator reduced to a schematic→board sync, idempotent derived layers, on-demand routing and the existing checkers.

**Architecture:** A committed, stamped netlist exported by `kicad-cli` is the interface between the two files. `sync_board.py` applies it to the live board the way KiCad's "Update PCB from Schematic" does, then regenerates only the items it owns (kept in a `generated` PCB group) and respects every locked item. `route.py` routes named or unconnected nets over the live board with Freerouting or the in-house A*, treating existing copper as fixed. `gen_sch.py` runs once more to emit a hierarchical seed, then it and `design.py` are deleted.

**Tech Stack:** KiCad 10.0.6 (`pcbnew` Python, `kicad-cli`), Python 3 standard library for everything portable, Freerouting 2.3.0 jar + Java, GNU make.

**Spec:** `docs/superpowers/specs/2026-10-06-board-owns-layout-design.md`

## Global Constraints

- KiCad 10+ only; `pcbnew` scripts run under the KiCad Python found by the Makefile's `find_kpy`; portable checkers run under plain `python3` with the standard library and `generator/sexp.py` only.
- Every portable checker stays in `pcb-check-portable` and must not import `pcbnew`, call `kicad-cli`, or read KiCad's footprint libraries.
- No electrical change: the seed board and schematic carry the same refs, pins and nets as `main` at `d3abdca`.
- Locked items (`IsLocked()`) are never moved, deleted or re-placed by the sync or either router.
- The board file leaves every tool in KiCad's own item order (`resort_to_kicad_order`).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `hardware/kicad/PCB-REVIEW-2026-10-05.md`, `SCHEMATIC-REVIEW-2026-10-05.md` and `review-2026-10-05/` are untracked user files: never `git add -A`.

## Review Focus

1. A schematic edit that renames a net on a routed pad: the sync must re-net the pad and report the copper now on a dead net, not delete it. (Task 6, idempotence test includes a renamed net on a scratch copy.)
2. A footprint the user locked and then changed in the schematic: swapped in place, still locked, position unchanged. (Task 6.)
3. A user-authored silk text with the same string as a generated legend ("GND"): never deleted, because membership in the `generated` group, not the text, decides ownership. (Task 6.)
4. `make pcb-route` on a board with zero unconnected items must exit 0 and change nothing. (Task 8.)
5. A sub-sheet file renamed by hand: `check_netlist_fresh.py` must still find every sheet through the root's `Sheetfile` properties rather than a glob, or a stale sheet goes unhashed. (Task 1.)

---

### Task 1: Netlist as the interface

**Files:**
- Create: `hardware/kicad/generator/netlist.py`
- Create: `hardware/kicad/generator/check_netlist_fresh.py`
- Modify: `Makefile` (new `pcb-netlist` target; add the fresh check to `pcb-check-portable`)
- Generated, committed: `hardware/kicad/bisque-controller.net`, `hardware/kicad/bisque-controller.net.stamp`

**Interfaces:**
- Produces: `netlist.load(path) -> Netlist` with `.comps: {ref: Comp}` (`Comp` is a dict `{"value", "footprint", "fields": {name: value}, "dnp": bool, "pins": {num: net}}`), `.nets: {net: set((ref, pin))}`, `.sheets: [path]`.
- Produces: `netlist.export(sch_path, out_path)` (runs `kicad-cli sch export netlist --format kicadsexpr`), `netlist.sheet_files(root_sch) -> [abs paths]` (root plus every `(sheet … (property "Sheetfile" …))` recursively), `netlist.stamp(root_sch) -> hex`.

- [ ] **Step 1: Write `netlist.py`**

```python
"""The schematic's exported netlist, parsed. Standard library + sexp.py only.

This is the interface between the schematic and the board. It is committed
(bisque-controller.net) so the portable checkers can read connectivity in CI
without kicad-cli, and stamped against the schematic files so a stale copy
fails rather than passes.
"""
import hashlib, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexp import parse, find, find_all

PIN_RENAME = {("J1", "SH"): "S1"}   # KiCad 10 renamed the USB-C shield pin


class Netlist:
    def __init__(self):
        self.comps, self.nets, self.sheets = {}, {}, []


def load(path):
    doc = parse(open(path).read())[0]
    nl = Netlist()
    for c in find_all(find(doc, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        if ref.startswith("#"):
            continue
        fields = {}
        fs = find(c, "fields")
        for fld in (find_all(fs, "field") if fs else []):
            fields[str(find(fld, "name")[1])] = str(fld[-1]) if len(fld) > 2 else ""
        for p in find_all(c, "property"):
            fields.setdefault(str(find(p, "name")[1]), str(find(p, "value")[1]))
        fpn = find(c, "footprint")
        nl.comps[ref] = {"value": str(find(c, "value")[1]),
                         "footprint": str(fpn[1]) if fpn and len(fpn) > 1 else "",
                         "fields": fields, "dnp": fields.get("dnp") == "yes" or bool(find(c, "dnp")),
                         "pins": {}}
    for n in find_all(find(doc, "nets"), "net"):
        name = str(find(n, "name")[1]).split("/")[-1]
        if name.startswith("unconnected-"):
            continue
        for node in find_all(n, "node"):
            ref = str(find(node, "ref")[1])
            if ref.startswith("#") or ref not in nl.comps:
                continue
            pin = PIN_RENAME.get((ref, str(find(node, "pin")[1])), str(find(node, "pin")[1]))
            nl.nets.setdefault(name, set()).add((ref, pin))
            nl.comps[ref]["pins"][pin] = name
    nl.nets = {k: v for k, v in nl.nets.items() if v}
    return nl


def sheet_files(root):
    seen, todo = [], [os.path.abspath(root)]
    while todo:
        p = todo.pop(0)
        if p in seen:
            continue
        seen.append(p)
        doc = parse(open(p).read())[0]
        for sh in find_all(doc, "sheet"):
            for prop in find_all(sh, "property"):
                if str(prop[1]) == "Sheetfile":
                    todo.append(os.path.join(os.path.dirname(p), str(prop[2])))
    return seen


def stamp(root):
    h = hashlib.sha256()
    for p in sheet_files(root):
        h.update(os.path.basename(p).encode()); h.update(open(p, "rb").read())
    return h.hexdigest()


def export(sch, out):
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format",
                    "kicadsexpr", "-o", out, sch], check=True, capture_output=True)
    with open(out + ".stamp", "w") as fh:
        fh.write(stamp(sch) + "\n")


if __name__ == "__main__":
    export(sys.argv[1], sys.argv[2])
    nl = load(sys.argv[2])
    print("%s: %d components, %d nets" % (sys.argv[2], len(nl.comps), len(nl.nets)))
```

Check how DNP appears in the export (`kicad-cli` writes `(property (name "dnp") …)` or a `dnp` field) by grepping the exported file for J13 and adjust the `dnp` line to whatever is actually there.

- [ ] **Step 2: Verify against design.py while it still exists**

Run from `hardware/kicad`:
```bash
python3 generator/netlist.py bisque-controller.kicad_sch bisque-controller.net && python3 - <<'EOF'
import sys; sys.path.insert(0, "generator")
import netlist, design
nl = netlist.load("bisque-controller.net")
want = {n: set(p) for n, p in design.netlist().items()}
assert nl.nets == want, [n for n in set(want) | set(nl.nets) if want.get(n) != nl.nets.get(n)]
for ref, c in design.COMPONENTS.items():
    assert nl.comps[ref]["footprint"] == c["fp"], ref
    assert nl.comps[ref]["value"] == c["value"], ref
assert nl.comps["J13"]["dnp"]
print("netlist == design.py")
EOF
```
Expected: `netlist == design.py`.

- [ ] **Step 3: Write `check_netlist_fresh.py`** (portable): read `bisque-controller.net.stamp`, compute `netlist.stamp(root)`, exit 1 with `run: make pcb-netlist` if they differ or the file is missing.

- [ ] **Step 4: Makefile**: add
```make
pcb-netlist:  ## Export + stamp hardware/kicad/bisque-controller.net from the schematic
	cd $(KICAD_DIR) && python3 generator/netlist.py bisque-controller.kicad_sch bisque-controller.net
```
and `python3 generator/check_netlist_fresh.py bisque-controller.kicad_sch bisque-controller.net` as the first line of `pcb-check-portable`.

- [ ] **Step 5: Commit** `netlist.py`, `check_netlist_fresh.py`, the Makefile, `bisque-controller.net`, `.net.stamp`.

---

### Task 2: Portable board reader

**Files:**
- Create: `hardware/kicad/generator/board.py`

**Interfaces:**
- Produces: `board.load(path) -> Board` with `.fps: {ref: Fp}` (`Fp` dict: `{"fpid": "Lib:Name", "x", "y", "rot", "layer", "value", "locked": bool, "dnp": bool, "pads": {num: net_or_None}, "uuid"}`), `.edge: (x0, y0, x1, y1)` from Edge.Cuts, `.tracks: [(net, layer, x1,y1,x2,y2,w, locked)]`, `.vias: [(net, x, y, locked)]`, `.nets: set`.

- [ ] **Step 1: Write `board.py`** with `sexp.parse`. Footprint position is `(at x y [rot])`; layer is `(layer "F.Cu")`; `(locked yes)` may appear as a bare `locked` symbol or an `(attr …)` — handle both (`"locked" in [str(a) for a in node]` or `find(node, "locked")`). Pads: `(pad "1" … (net 3 "GND"))`. Edge: min/max over `gr_line`/`gr_rect` on `Edge.Cuts`. Value from `(property "Value" "…")`.

- [ ] **Step 2: Verify against pcbnew and design.py**

```bash
"$KPY" - <<'EOF'
import sys; sys.path.insert(0, "generator"); import pcbnew, board, design
bd = board.load("bisque-controller.kicad_pcb"); b = pcbnew.LoadBoard("bisque-controller.kicad_pcb")
for fp in b.GetFootprints():
    r = fp.GetReference(); f = bd.fps[r]
    assert abs(f["x"] - pcbnew.ToMM(fp.GetPosition().x)) < 1e-6 and abs(f["rot"] - fp.GetOrientationDegrees()) < 1e-6, r
    for pad in fp.Pads():
        assert f["pads"].get(str(pad.GetNumber())) == (pad.GetNetname() or None), (r, pad.GetNumber())
assert bd.edge == (design.BX0, design.BY0, design.BX1, design.BY1), bd.edge
print("board.py agrees with pcbnew")
EOF
```

- [ ] **Step 3: Commit.**

---

### Task 3: Lock the hand-seeded copper on the committed board

**Files:**
- Create: `hardware/kicad/generator/lock_seeds.py` (one-shot, deleted in Task 9)
- Modify: `hardware/kicad/bisque-controller.kicad_pcb`

- [ ] **Step 1:** Under `$KPY`, load the board; lock every track and via whose net is in `gen_pcb.USB_DIFF_PAIR`, every segment that coincides (both endpoints within 0.01 mm) with a segment of `gen_pcb.USB_SEEDS`, `ADE_I2C_SEEDS`, `MUX_SEEDS`, and every via at a `MANUAL_VIAS` / `STITCH_VIAS` position. `t.SetLocked(True)`. Save with `pcbnew.SaveBoard`, then `kicad_build.resort_to_kicad_order(path)`.
- [ ] **Step 2:** `git diff --stat` must show only `(locked yes)` additions; `make pcb-check` green.
- [ ] **Step 3: Commit** `hardware: lock the hand-seeded copper so no router can take it`.

---

### Task 4: Hierarchical schematic seed

**Files:**
- Modify: `hardware/kicad/generator/gen_sch.py` (SHEETS table, per-sheet layout, root sheet emission)
- Modify: `check_sch_bounds.py`, `check_sch_layout.py`, `check_sch_uuids.py`, `check_mpn.py`, `check_netlist.py` to walk `netlist.sheet_files(root)`
- Generated, committed: `hardware/kicad/bisque-controller.kicad_sch` plus `hardware/kicad/sheets/<name>.kicad_sch` ×7

**Interfaces:**
- `SHEETS = [(filename, title, [group indices into GROUPS])]` in gen_sch.py.

- [ ] **Step 1: Define SHEETS**
```python
SHEETS = [
    ("power",        "Power input and 24 V -> 5 V buck",          [0, 1]),
    ("mcu",          "ESP32-S3, USB, reset, status LED, headers, bus damping", [2, 3, 4, 5, 6, 15]),
    ("thermocouples","Thermocouple front-ends (MAX31856 x2)",      [7, 8]),
    ("ssr",          "SSR drive and hardware watchdog",            [9, 10]),
    ("io",           "Aux outputs, buzzer, protected inputs",      [11, 12, 13]),
    ("ct",           "CT current sensing (ADE7953)",               [14]),
    ("test",         "Test points, mounting, fiducials, power flags", [16, 17]),
]
assert sorted(i for _, _, ix in SHEETS for i in ix) == list(range(len(GROUPS)))
```
- [ ] **Step 2: Per-sheet layout.** `build_layout(symcache, groups)` takes the subset; paper per sub-sheet is A3 with `X0/Y0/X1/Y1` set to its usable box and `N_COLS = 2`; keep the notes column only on the root. The fuse planner is unchanged (it fuses within a group).
- [ ] **Step 3: Emission.** `main()` returns `{filename: text}`. Each sub-sheet has its own derived uuid `uid("sheet", name)`; symbol `instances` paths become `"/%s/%s" % (ROOT, sheet_uuid)`; `sheet_instances` on each file lists its page. The root sheet holds the title block, the notes text, and one `(sheet (at x y) (size 60 30) … (property "Sheetname" title) (property "Sheetfile" "sheets/<name>.kicad_sch") (uuid …))` per entry laid out in a 2-column grid on A3, with no sheet pins (nets cross by global label). Write every file, run `kicad-cli sch upgrade --force` on the root (it recurses).
- [ ] **Step 4: Checkers walk sheets.** Each `check_sch_*.py` and `check_mpn.py` loops over `netlist.sheet_files(root)` and reports per file; `check_sch_uuids.py` compares every file after the upgrade round trip.
- [ ] **Step 5: Verify** `make pcb-netlist` then rerun Task 1 Step 2's comparison (netlist identical to design.py). `make pcb-check-portable` green. Open `kicad-cli sch export pdf` output and eyeball that every sheet renders.
- [ ] **Step 6: Commit** the generator change and the seven+one schematic files.

---

### Task 5: Legend derivation reads the board

**Files:**
- Modify: `hardware/kicad/generator/gen_pcb.py` — `pad_geometry`, `pad_centres`, `fp_body_box`, `_free_span`, `block_legend`, `_pin_legends`, the TP loop and the module-level `SILK` assembly become `silk_table(bd)` taking a `board.Board`; `BX0..BY1` become `bd.edge`.

**Interfaces:**
- Produces: `gen_pcb.silk_table(bd) -> (SILK list, LEGEND_OWNER dict, TP_LABEL_TEXTS set)`; `gen_pcb.fp_body_box_at(fpf, x, y, rot)`, `gen_pcb.pad_centres_at(fpf, x, y, rot)`.

- [ ] **Step 1:** Replace `comp["at"]` / `COMPONENTS[ref]` reads inside the legend code with the `bd.fps[ref]` dict (`fpf` is `fpid.split(":")[1] + ".kicad_mod"`). Keep `PIN_LEGENDS`, `BLOCK_LEGENDS`, `BLOCK_LEGEND_NAME`, `TP_*`, `_TITLE_TEXTS`, `SILK_GRAPHICS` as the authored intent.
- [ ] **Step 2:** Prove identity: `silk_table(board.load("bisque-controller.kicad_pcb"))[0] == SILK_old` (keep the old module-level list under a temporary name for this one comparison, then delete it).
- [ ] **Step 3: Commit.**

---

### Task 6: `sync_board.py`

**Files:**
- Create: `hardware/kicad/generator/sync_board.py`
- Modify: `kicad_build.py` — keep `load_footprint`, `MODEL_FIXUP` application (extract to `apply_model_fixups(fp, ref)`), `widen_fp_silk`, `add_zones` (now "ensure zones"), `apply_layer_types`, `read_project`/`restore_project`, `resort_to_kicad_order`, `verify_dru_loaded`, `plane_islands`, `summarize`; delete `build_board`, `strip_derived`, `verify_reusable`, `route_board`, `build_copper`, `add_copper`, `main`.
- Modify: `silk.py` — `collect_labels` skips `item.IsLocked()` texts and files them as obstacles.
- Create: `hardware/kicad/generator/check_sync_idempotent.py`
- Modify: `Makefile` — `pcb-sync`; remove `pcb-build`, `pcb-cosmetic`, `pcb-cosmetic-verify`; `pcb` = `pcb-sync pcb-fab` then check, render.

**Interfaces:**
- `sync_board.sync(board_path, net_path) -> Report` (dict of lists: `added`, `removed`, `swapped`, `renetted`, `dead_copper`, `unconnected`).
- Generated-group name: `GENERATED_GROUP = "generated"`.

- [ ] **Step 1: Sync core**
```python
def sync(out, net_path):
    nl = netlist.load(net_path)
    board = pcbnew.LoadBoard(out)
    rep = {k: [] for k in ("added", "removed", "swapped", "renetted", "dead_copper")}
    have = {fp.GetReference(): fp for fp in board.GetFootprints()}
    nets = {}
    def net(name):
        if name not in nets:
            n = board.FindNet(name)
            if n is None:
                n = pcbnew.NETINFO_ITEM(board, name); board.Add(n)
            nets[name] = n
        return nets[name]
    park_y = pcbnew.ToMM(board.GetBoardEdgesBoundingBox().GetTop())
    bx1 = pcbnew.ToMM(board.GetBoardEdgesBoundingBox().GetRight())
    for ref in sorted(set(have) - set(nl.comps)):
        board.Remove(have[ref]); _REMOVED.append(have.pop(ref)); rep["removed"].append(ref)
    for ref, c in nl.comps.items():
        lib, name = c["footprint"].split(":", 1)
        fp = have.get(ref)
        if fp is not None and str(fp.GetFPID().GetUniStringLibItemName()) != name:
            new = load_footprint(lib, name)
            new.SetPosition(fp.GetPosition()); new.SetOrientation(fp.GetOrientation())
            new.SetLayer(fp.GetLayer()); new.SetLocked(fp.IsLocked())
            new.SetUuid(fp.m_Uuid)
            board.Remove(fp); _REMOVED.append(fp); board.Add(new); fp = new
            rep["swapped"].append(ref)
        elif fp is None:
            fp = load_footprint(lib, name)
            fp.SetPosition(V(bx1 + 8.0, park_y + 5.0 * len(rep["added"])))
            fp.SetUuid(pcbnew.KIID(str(uuid.uuid5(NS, "fp:" + ref))))
            board.Add(fp); rep["added"].append(ref)
        fp.SetReference(ref); fp.SetValue(c["value"]); fp.SetDNP(c["dnp"])
        for pad in fp.Pads():
            want = c["pins"].get(str(pad.GetNumber()))
            if (pad.GetNetname() or None) != want:
                rep["renetted"].append((ref, str(pad.GetNumber()), pad.GetNetname(), want))
            pad.SetNet(net(want) if want else None)
            upsize_drill(pad); full_zone_connection(ref, pad)
        apply_model_fixups(fp, ref); style_reference(fp, ref)
    live = set(nl.nets)
    for t in board.GetTracks():
        if t.GetNetname() and t.GetNetname() not in live:
            rep["dead_copper"].append((t.GetNetname(), pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)))
    regenerate_group(board); ensure_zones(board, net); apply_layer_types(board); set_title_block(board)
    return board, rep
```
`KIID` constructor from string: verify `pcbnew.KIID("…")` accepts a uuid string; if not, set uuids afterwards by a scoped text pass (`canonicalize.identity` restricted to `footprint` nodes whose reference is in `rep["added"]`).

- [ ] **Step 2: Generated group.** `regenerate_group(board)`: find `PCB_GROUP` named `generated`; collect its items; for each unlocked member `board.Remove` (keep the proxies in `_REMOVED`); then recreate the outline (only if no Edge.Cuts exists), every `silk_table(bd)` text not already present as a locked member (match on text + lock axis owner), the `SILK_GRAPHICS` polys, add all to the group; set each new item's uuid to `uuid5(NS, "silk:" + text + ":" + anchor)`. Then `silk.place(board, anchors)` over the unlocked ones.
- [ ] **Step 3: silk.py locks.** In `collect_labels`, `if item.IsLocked(): continue`; in `_Obstacles.__init__`, file locked board texts and locked footprint references as silk obstacles.
- [ ] **Step 4: main()**: `sync` → `pcbnew.SaveBoard` (bracketed by `read_project`/`restore_project`) → `apply_stackup` → `kicad-cli pcb drc --refill-zones --save-board …` → `resort_to_kicad_order` → `sync_project`/`sync_netclasses` → print the report plus `summarize(rpt)` and `board.GetConnectivity().GetUnconnectedCount(True)`.
- [ ] **Step 5: Idempotence checker.** Copy board + project + dru to a temp dir, run `sync_board.py` twice, assert bytes equal after the second; also run once over a copy where a `GND` user text was added outside the group and assert it survives; and over a copy where `C30`'s footprint id was edited in the netlist copy to `C_0603_1608Metric` and `C30` locked, assert it is swapped, still locked, same position.
- [ ] **Step 6: Run on the real board.** `make pcb-sync`; diff must be only: the `generated` group block, uuids of generated texts, and whatever reordering the group causes. Zero DRC errors, zero unconnected.
- [ ] **Step 7: Commit** generator + board + Makefile.

---

### Task 7: Checkers and fab outputs read netlist + board

**Files:**
- Modify: `check_netlist.py` (netlist vs board: footprint id per ref, pad nets per pad; refs in one and not the other), `check_pinmap.py` (U1 pins from `netlist.load`), `check_mpn.py` (LCSC field from the netlist vs `gen_jlc.LCSC`), `gen_jlc.py` (refs/value/footprint from netlist; x/y/rot from `board.load`; `fpf` via the footprint name), `check_jlc_placement.py` (same), `check_placement.py` (from board positions), `check_placement_fast.py` (from board positions).
- Delete: `check_fast_path.py`, `check_canonical.py`, `canonicalize.py` (after confirming nothing else imports it).

- [ ] **Step 1–6:** one checker per step, each run green before moving on; `make pcb-fab` regenerates BOM/CPL byte-identically (diff must be empty).
- [ ] **Step 7: Commit.**

---

### Task 8: Routing on demand

**Files:**
- Create: `hardware/kicad/generator/route.py`
- Modify: `Makefile` (`pcb-route`)

**Interfaces:**
- CLI: `route.py [--nets A,B] [--router freerouting|inhouse] [--jar PATH] board.kicad_pcb`.

- [ ] **Step 1: Target selection.** Load board; `nets = --nets` or every net name with unconnected items (`board.GetConnectivity().GetUnconnectedCount`; use `connectivity.GetRatsnestForNet`/iterate `board.GetConnectivity().GetConnectedItems` — simplest robust path: run `kicad-cli pcb drc --severity-all -o tmp.rpt` and parse "unconnected items" lines for net names). Exit 0 with "nothing to route" if empty.
- [ ] **Step 2: Rip-up.** For `--nets`, remove every unlocked track/via on those nets.
- [ ] **Step 3: Freerouting.** `pcbnew.ExportSpecctraDSN(board, dsn)`; before export, mark every track not in `nets` as locked in the *scratch copy* only (Freerouting honours `(type fix)`/`protect` wiring the exporter emits for locked tracks — verify on the scratch copy below); run `java -jar JAR -de dsn -do ses -mp 20 -oit 0.5` (flags per `java -jar JAR --help`); `pcbnew.ImportSpecctraSES(board, ses)`; then assert every track that was locked before is still present with identical geometry, else abort with the counts.
- [ ] **Step 4: In-house.** Build `router.Router` from the board (adapt `kicad_build.build_router_model`: pad net from `pad.GetNetname()`, board extent from `GetBoardEdgesBoundingBox`); add every existing track/via as `fixed` copper; `gen_pcb.route_all(r, pad_pos, order=nets)`; `add_copper` only the new segments.
- [ ] **Step 5: Verify on a scratch copy:** rip `I2C_SDA`, route with each router, `kicad-cli pcb drc` → 0 errors, 0 unconnected; locked USB pair bytes unchanged.
- [ ] **Step 6: Makefile**
```make
pcb-route:  ## Route unconnected nets (or NETS=a,b) over the live board; ROUTER=freerouting|inhouse
	@$(find_kpy); cd $(KICAD_DIR) && "$$KPY" generator/route.py $(if $(NETS),--nets $(NETS),) $(if $(ROUTER),--router $(ROUTER),) bisque-controller.kicad_pcb
```
- [ ] **Step 7: Commit.**

---

### Task 9: Retire design.py and the generators

**Files:**
- Create: `hardware/kicad/DESIGN-NOTES.md` (harvest: every comment block in `design.py` longer than three lines that is not already in README or a GROUPS title, under the heading of the ref it sits beside)
- Delete: `design.py`, `gen_sch.py`, `floorplan.py`, `apply_floorplan.py`, `lock_seeds.py`, `inspect_libs.py` if only gen_sch used it, dead router-seeding code in `gen_pcb.py` not reached by `route.py`
- Modify: `.gitignore` (drop the floorplan.json line), `.github/workflows/build.yml` (pcb-check job: targets renamed)

- [ ] **Step 1:** `grep -rn "import design\|from design" generator/` must be empty before deleting.
- [ ] **Step 2:** `make pcb-check` green; `make pcb-netlist && make pcb-sync` is a no-op diff.
- [ ] **Step 3: Commit.**

---

### Task 10: Documentation

- [ ] **Step 1:** README: replace "Regenerating the files" through "Which path does your change need?" with the sync / route / check workflow, the lock convention, the `generated` group, and the Konnect/GUI editing channels.
- [ ] **Step 2:** CLAUDE.md hardware paragraph: rewrite as described in the spec §6.
- [ ] **Step 3:** Commit; final `make pcb` end to end.
