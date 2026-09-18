# JLCPCB order package — rev B

Everything an order uploads is in this directory. `gerbers.zip` goes to the PCB
order form; `BOM.csv` + `CPL.csv` go to the SMT assembly step.
`hand-solder-parts.csv` is the shopping list for the through-hole parts you
solder yourself after the board comes back, plus the mating connectors for the
board's headers.

Its first column, `Kind`, splits it in two. `board` rows are parts that get
soldered down — one row per **orderable part**, so the five identical
2-position screw terminals are one line of `Qty 5` rather than five lines of
one (their schematic names are joined in the `Comment` cell, in designator
order, so nothing is lost). `mating` rows are the female crimp housings and
terminals that go on the far end of the loom: they are not on the board, so
they have no designator, footprint or LCSC line, and they appear in neither
`BOM.csv` nor `CPL.csv`. See the sourcing section of `../README.md` for the
part numbers and why those particular ones.

`mouser-order.csv` is the same shopping list again, shaped for Mouser's
importer instead of for a reader — see "Ordering from Mouser" below.

All five are generated — don't hand-edit. `make pcb-fab` writes them:
`generator/gen_gerber_zip.py` packs `../gerbers/` (including the `.gbrjob`,
which is what tells the fab the stack-up), and `generator/gen_jlc.py` writes
the four CSVs. `make pcb-check` fails if `gerbers.zip` has gone stale against
`../gerbers/`, so the zip in a clone is always the one that matches the board
beside it.

## Ordering from Mouser

`hand-solder-parts.csv` is for a human deciding what a part is and where it
goes, so it carries the LCSC number beside the Mouser one and works against
either supplier. That shape does not import: Mouser's spreadsheet upload has a
column-mapping step where picking `LCSC Part #` by mistake silently fails
every line, and its quick-paste box takes two columns and nothing else.

`mouser-order.csv` is the same parts shaped for that importer — one
part-number column, with `Mfr Part Number` and `Quantity` first so columns A
and B paste straight into the quick-import box, then `Manufacturer`,
`Description` and `Customer Part Number` (the designators, so Mouser echoes
onto the packing list which bag is which). Board-fitted and mating parts are
one list. Both of Mouser's import paths need a My Mouser login.

The `Description` is the **Mouser** part's, not the LCSC one's — a row reading
`22-27-2141 … XD-2510-14A` is the kind of thing that makes you think the
import matched the wrong part.

Two deliberate differences from `hand-solder-parts.csv`:

* **`LED1` is not in it.** No bare Worldsemi 5050 is in Mouser's catalog, and
  an unmatched line you have to notice and delete is worse than one the
  generator names on stdout. Source the WS2812B from LCSC, DigiKey, Adafruit
  or SparkFun.
* **35 crimp terminals, not 28.** A miscrimp is not un-done — it is cut off
  and thrown away — and running out halfway through a 14-way loom stops the
  build for a week over $0.16, so `SPARES` adds 25 % to that line alone.
  Housings and board parts get no margin; you do not consume those by getting
  them wrong. `hand-solder-parts.csv` keeps saying the exact per-board 28,
  because the two files answer different questions and conflating them is how
  one of them ends up wrong.

`Quantity` is otherwise per board — use Mouser's own board multiplier for
more than one.

## Bring-up: leave SJ2 open

`SJ2` (the "WDT DEFEAT" solder jumper, silkscreened near the SSR drive
section) is **not** in `BOM.csv`, `CPL.csv`, or `hand-solder-parts.csv` — it's
a solder jumper, not a manufactured part, so it's deliberately excluded from
assembly (see `NOT_ASSEMBLED` in `gen_jlc.py`).

**Leave it open.** This package's board carries `U10`, an SN74LVC1G123
retriggerable one-shot gating the SSR +5 V rail, and firmware kicks it on
`GPIO 36` at 5 Hz (`KILN_PIN_WDT_KICK`, `components/safety/wdt_kick.h`) — the
SSR outputs energize as soon as running firmware is supervising them.
Bridging `SJ2` holds the rail on unconditionally, defeating the only
interlock on this board that survives firmware death.

The only reasons to bridge it: bench-debugging the SSR drive path with no
firmware flashed, or a board assembled from a **pre-one-shot** rev B package
(BAT54S charge pump where `U10` now sits) — on those boards the kick cannot
hold the rail and `SJ2` must stay fitted.

(This section used to say the opposite — "fit SJ2 or the kiln will not
heat" — written before the kick task and the one-shot landed. On a current
build that advice is exactly backwards.)

If a fresh board will not heat, check that firmware is running and the kick
is alive (scope `GPIO 36`, or `TP12` for the timing node) before suspecting
the SSRs — an expired watchdog window presents as a dead output stage.

## SJ3 and SJ4 no longer exist

Earlier rev B builds had `SJ3`/`SJ4`, per-channel links from board +5 V to an
optocoupler collector, and told you to leave them open to keep each SSR
channel isolated. **Both the jumpers and the optocouplers are gone.** The
board now drives each SSR channel with a direct low-side MOSFET and supplies
the control loop itself: `J4`/`J9` pin 1 is +5 V (watchdog-gated), pin 2 is
the switched low side. Opto-isolation only isolates when the control loop is
powered off-board, which this one is not — see `hardware/kicad/README.md`.
Only `SJ1` and `SJ2` remain.
