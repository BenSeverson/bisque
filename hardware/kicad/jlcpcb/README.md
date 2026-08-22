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
