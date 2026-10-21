# The KiCad files own the design; the generator becomes a sync

Date: 2026-10-06. Branch: `hw/board-owns-layout`.

## Problem

`hardware/kicad/generator/design.py` owns connectivity, BOM identity,
placement and (through `router.py`) routing, and both KiCad files are
rebuilt from it from nothing. Any edit made in the KiCad GUI, by an LLM
through Konnect, or by another router is destroyed on the next build.
Moving one capacitor means editing coordinate tuples, waiting for a full
re-route that re-rolls every net on the board, and hoping the router does
not strand one. The byte-identity machinery (`canonicalize.py`,
`check_fast_path.py`, `pcb-cosmetic-verify`) exists to prove that rebuild
is faithful. It was a goal of the pipeline, never of the product.

The product goals are the best PCB possible and a readable schematic that
follows industry convention. Both are reached by humans, LLMs and routers
editing the files incrementally, with review accumulating rather than
being thrown away.

## Decision

Invert the ownership. The two KiCad files become the sources of truth.
The generator becomes a one-way sync from the schematic into the board
plus a set of idempotent derived layers and the existing checkers.

| Thing | Owner after this change |
|---|---|
| Connectivity, values, footprints, LCSC/MPN fields, DNP | `bisque-controller.kicad_sch` and its sub-sheets (hand / LLM edited) |
| Placement, copper, hand-placed silk | `bisque-controller.kicad_pcb` (hand / LLM / router edited) |
| Per-terminal legends, block names, test-point labels, nameplate, stackup, net classes, zone outlines, 3D-model fixups, title block | code, applied idempotently by the sync |
| LCSC placement corrections, NOT_ASSEMBLED / HAND_SOLDER / DNP sets, Mouser alternates | `gen_jlc.py` tables (unchanged) |
| Module pin → GPIO map and the Kconfig cross-check | `check_pinmap.py`, now reading the netlist |

`design.py`, `gen_sch.py`, `floorplan.py`, `apply_floorplan.py`,
`check_fast_path.py`, `check_canonical.py`, `check_placement.py` and
`check_placement_fast.py` are deleted once the seed is committed. The
engineering rationale in `design.py`'s comments that is not already in
`README.md` or on the schematic is harvested into
`hardware/kicad/DESIGN-NOTES.md` first.

## Architecture

```
schematic (.kicad_sch tree)
    │  kicad-cli sch export netlist
    ▼
bisque-controller.net  ──── committed, stamped against the schematic hashes
    │
    ▼
sync_board.py  ──►  bisque-controller.kicad_pcb  ◄──  KiCad GUI / Konnect / route.py
    │                        │
    │  derived layers        │  kicad-cli pcb drc --refill-zones
    ▼                        ▼
checkers (make pcb-check)    fab outputs (make pcb-fab)
```

### 1. Netlist as the interface

`generator/netlist.py` (standard library only) parses the `kicadsexpr`
netlist into `{ref: {value, footprint, fields, dnp, pins: {num: net}}}`
and `{net: {(ref, pin)}}`, with the same normalisations `check_netlist.py`
applies today (drop `#` refs, drop `unconnected-*`, J1 `SH` → `S1`).

`make pcb-netlist` exports it to `hardware/kicad/bisque-controller.net`
and writes `bisque-controller.net.stamp` holding a SHA256 over every
`.kicad_sch` in the project. The netlist is committed so the portable CI
checkers can read it without `kicad-cli`; `check_netlist_fresh.py` fails
when the stamp no longer matches, exactly as the fixture manifest does
for the web tests.

### 2. `sync_board.py` replaces the board build

Semantics are KiCad's own "Update PCB from Schematic", by reference:

1. Load the board. Load the netlist.
2. **Refs in the netlist and not on the board**: load the footprint from
   the vendored `fp/` library and place it in a parking row outside the
   board edge (right of `BX1`, stacked), unlocked. A human then places it.
3. **Refs on the board and not in the netlist**: remove the footprint.
   Report any track or via left on a net that no longer exists; do not
   delete copper.
4. **Footprint changed**: swap in place, keeping position, rotation, layer
   and lock state. A locked footprint is still swapped (the lock is about
   position).
5. **Every ref**: set value, DNP, pad nets from the netlist. A pad with no
   netlist entry gets no net.
6. **Nets**: add missing. Nets no longer referenced are dropped by KiCad
   on save.
7. **Derived layers**, each idempotent and each skipping locked items:
   - Board texts and graphics the sync owns live in a `PCB_GROUP` named
     `generated`. The sync deletes the group's members and regenerates
     them from the board's actual footprint positions (legends follow the
     part). A member the user has locked is kept and not regenerated.
     Texts outside the group are the user's and are never touched.
   - Reference designators are re-placed by `silk.place()` unless locked.
     Locked designators and user texts are obstacles.
   - Stackup, copper layer types, net classes, title block, 3D-model
     fixups and NOT_ASSEMBLED model hiding are applied as today.
   - The four zones are created if missing and never re-outlined if
     present (the user may have reshaped them).
8. Save, `kicad-cli pcb drc --refill-zones --save-board`, then
   `resort_to_kicad_order()` so a GUI save stays a no-op diff.
9. Print a report: added / removed / swapped refs, net changes, copper on
   dead nets, DRC summary and the unconnected count.

**Uuids.** `canonicalize.py` is no longer run over the whole file. New
footprints get `uuid5(ref)` via `SetUuid`; items the sync creates in the
`generated` group get content-derived uuids the same way. Everything
else keeps the uuid the file gave it, so a hand edit to one track moves
one line in the diff.

**Idempotence proof.** `check_sync_idempotent.py` copies the board, runs
the sync twice and asserts the second run is byte-identical to the
first. It replaces `check_fast_path.py` in `make pcb-check`.

**Drift check.** `check_netlist.py` now diffs the netlist against the
*board* (footprint ids, pad nets) rather than against `design.py`, so a
schematic edit that has not been synced fails the gate.

### 3. Routing on demand

`route.py` routes only what you ask for, over the live board, and treats
every existing track and via as fixed.

- `make pcb-route` routes every net with unconnected items.
- `make pcb-route NETS=I2C_SDA,I2C_SCL` routes those nets only, first
  ripping up their unlocked copper.
- `ROUTER=freerouting` (default when `~/freerouting-*.jar` or
  `$FREEROUTING_JAR` exists) exports a DSN with `pcbnew.ExportSpecctraDSN`,
  runs the jar headless, imports the SES. Locked tracks are exported as
  fixed wiring; the implementation verifies on a scratch copy that
  Freerouting leaves them in place before trusting the import.
- `ROUTER=inhouse` builds `router.py`'s model from the board (pad nets
  from `pad.GetNetname()`, existing copper as fixed obstacles) and routes
  the requested nets with the existing A*.

Before the seed is committed, the copper the in-house router could only
produce with hand seeds (the USB pair, the ADE7953 I2C escapes, the
`MANUAL_VIAS` and `STITCH_VIAS`) is **locked** on the board so no router
and no sync can take it.

### 4. Schematic: one last generation, then hand-owned

`gen_sch.py` is extended once to emit a hierarchical schematic and then
deleted:

- A root sheet with one sheet symbol per functional sheet and the notes
  block.
- Seven sub-sheets, each an A3 landscape, formed from the existing
  `GROUPS` taxonomy: Power input and buck; MCU, USB, reset, status LED,
  headers and bus damping; Thermocouples; SSR drive and watchdog; Aux
  outputs, buzzer and protected inputs; Current sensing; Test points,
  mounting, fiducials and power flags.
- Inter-sheet nets stay global labels, rails stay power ports, two-pin
  block-local nets stay fused wires with local labels. The packer runs
  per sheet.
- Symbol instance paths carry the sub-sheet uuid; `check_sch_uuids.py`
  proves KiCad mints none of its own on the round trip.

After the seed: `check_sch_bounds.py`, `check_sch_layout.py`,
`check_sch_uuids.py` and `check_mpn.py` walk every sheet reachable from
the root. `check_mpn.py` compares the netlist's LCSC fields against
`gen_jlc.LCSC` in both directions. `gen_jlc.py` reads value, footprint and
refs from the netlist and placement from the board.

The schematic is then edited in KiCad or through Konnect. Nothing
regenerates it.

### 5. Makefile

| Target | Does |
|---|---|
| `pcb-netlist` | export + stamp the netlist |
| `pcb-sync` | `pcb-netlist`, then `sync_board.py`, then DRC |
| `pcb-route [NETS=…] [ROUTER=…]` | route over the live board |
| `pcb-check-portable` | pinmap, sch bounds/layout, mpn, pcb, drill, 3dmodels, usb pair, gerber zip, netlist freshness, netlist-vs-board |
| `pcb-check` | portable set + sch uuids, jlc placement, via-in-pad, silk, sync idempotence, datasheet manifest |
| `pcb-fab`, `pcb-render` | unchanged |
| `pcb` | `pcb-sync` + `pcb-fab` + `pcb-check` + `pcb-render` |

`pcb-build`, `pcb-cosmetic` and `pcb-cosmetic-verify` are removed.

### 6. Documentation

`hardware/kicad/README.md` "Regenerating the files" and "Which path"
sections are rewritten around sync / route / check. The hardware
paragraph of `CLAUDE.md` is rewritten: the byte-identity, fast-path and
router-ordering lore is dropped, the engineering facts stay, and the new
workflow (edit the files, sync, route what you need, check, commit) is
stated in a few paragraphs.

## Non-goals

- Reproducing the current board byte for byte. The seed commit is the
  current board with locks added and the derived group introduced.
- Restructuring the schematic beyond the hierarchical split. Tidying
  individual sheets is now ordinary GUI work.
- Changing any electrical content. The review findings on disk are the
  first jobs for the new workflow, not part of this change.

## Testing

- `check_sync_idempotent.py` on the seeded board.
- `check_netlist.py` passes on the seed (netlist equals board).
- `make pcb-check` green on the seed.
- `route.py` exercised on a scratch copy: rip up one net, route it with
  each router, assert zero unconnected and zero DRC errors, assert locked
  copper is byte-identical before and after.
- The hierarchical schematic exports a netlist identical to today's
  (same refs, same pins, same nets) before `gen_sch.py` is deleted.
