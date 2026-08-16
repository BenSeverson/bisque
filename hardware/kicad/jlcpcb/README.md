# JLCPCB order package — rev B

Everything an order uploads is in this directory. `gerbers.zip` goes to the PCB
order form; `BOM.csv` + `CPL.csv` go to the SMT assembly step.
`hand-solder-parts.csv` is the shopping list for the through-hole parts you
solder yourself after the board comes back.

All four are generated — don't hand-edit. `make pcb-fab` writes them:
`generator/gen_gerber_zip.py` packs `../gerbers/` (including the `.gbrjob`,
which is what tells the fab the stack-up), and `generator/gen_jlc.py` writes
the three CSVs. `make pcb-check` fails if `gerbers.zip` has gone stale against
`../gerbers/`, so the zip in a clone is always the one that matches the board
beside it.

## Bring-up: fit SJ2 or the kiln will not heat

`SJ2` (the "WDT DEFEAT" solder jumper, silkscreened near the SSR drive
section) is **not** in `BOM.csv`, `CPL.csv`, or `hand-solder-parts.csv` — it's
a solder jumper, not a manufactured part, so it's deliberately excluded from
assembly (see `NOT_ASSEMBLED` in `gen_jlc.py`).

Nothing on this firmware revision toggles `GPIO 36` yet (`KILN_PIN_WDT_KICK`
in `main/Kconfig.projbuild`). The hardware watchdog on this board gates both
SSR channels off unless that pin is kept alive by a kick task that doesn't
exist yet. (There are no opto channels — see "SJ3 and SJ4 no longer exist"
below; this line said "SSR opto channels" for a while after the optocouplers
were reverted out.) Until it lands:

**Bridge `SJ2` with solder (or a 0 Ω jumper) after assembly, before first
power-on. An unfitted `SJ2` means both SSR outputs stay de-energized — the
kiln will not heat, and it will look like a dead board rather than a
missing jumper.**

Remove/open `SJ2` only once a firmware release actually kicks the watchdog.

## SJ3 and SJ4 no longer exist

Earlier rev B builds had `SJ3`/`SJ4`, per-channel links from board +5 V to an
optocoupler collector, and told you to leave them open to keep each SSR
channel isolated. **Both the jumpers and the optocouplers are gone.** The
board now drives each SSR channel with a direct low-side MOSFET and supplies
the control loop itself: `J4`/`J9` pin 1 is +5 V (watchdog-gated), pin 2 is
the switched low side. Opto-isolation only isolates when the control loop is
powered off-board, which this one is not — see `hardware/kicad/README.md`.
Only `SJ1` and `SJ2` remain.
