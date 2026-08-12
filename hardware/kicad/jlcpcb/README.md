# JLCPCB assembly package — rev B

`BOM.csv` + `CPL.csv` go to JLCPCB's SMT assembly upload. `hand-solder-parts.csv`
is the shopping list for the through-hole parts you solder yourself after the
board comes back. Both are generated from `generator/gen_jlc.py`; don't hand-edit.

## Bring-up: fit SJ2 or the kiln will not heat

`SJ2` (the "WDT DEFEAT" solder jumper, silkscreened near the SSR drive
section) is **not** in `BOM.csv`, `CPL.csv`, or `hand-solder-parts.csv` — it's
a solder jumper, not a manufactured part, so it's deliberately excluded from
assembly (see `NOT_ASSEMBLED` in `gen_jlc.py`).

Nothing on this firmware revision toggles `GPIO 36` yet (`KILN_PIN_WDT_KICK`
in `main/Kconfig.projbuild`). The hardware watchdog on this board gates both
SSR opto channels off unless that pin is kept alive by a kick task that
doesn't exist yet. Until it lands:

**Bridge `SJ2` with solder (or a 0 Ω jumper) after assembly, before first
power-on. An unfitted `SJ2` means both SSR outputs stay de-energized — the
kiln will not heat, and it will look like a dead board rather than a
missing jumper.**

Remove/open `SJ2` only once a firmware release actually kicks the watchdog.
