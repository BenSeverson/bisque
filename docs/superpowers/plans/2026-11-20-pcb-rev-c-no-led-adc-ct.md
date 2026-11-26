# PCB Rev C (no status LED, one CT on the ESP32 ADC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the unbuilt rev B.5 board to rev C by deleting the WS2812 status LED and replacing the ADE7953 metering chip with a single CT channel read by the ESP32-S3's ADC1, leaving one module pin spare.

**Architecture:** The schematic is edited first and owns connectivity; the pin map then has to agree in three places (schematic, `main/Kconfig.projbuild`, `docs/pin-assignments.md` §1) before `check_pinmap.py` passes. Generator tables that name the removed parts are cleaned up before the board is synced, so the sync writes rev C silk. The board is then synced, the six new passives placed, and only the affected nets rerouted. One CT measures the total element current; telling two zones apart is left to firmware, which knows which SSR is on.

**Tech Stack:** KiCad 10 (`kicad-cli`, `pcbnew` Python), the repo's `hardware/kicad/generator/` scripts, ESP-IDF (C), `make` targets from the top-level `Makefile`.

**Spec:** none. The user asked for this plan directly and skipped the design round, so the decisions below stand in for a spec. The reasoning behind the ADC front end is in the "PCB BOM cost optimization" session of 2026-11-16.

## Design decisions

| Decision | Choice | Why | Whose |
|---|---|---|---|
| CT channels | **One**, on terminal J12; J17 is deleted | A CT on the shared feed reads the total for any number of elements. Per-zone attribution is done in firmware by sampling while only one SSR is on. | User (2026-11-26) |
| Revision name | **C** | The pin map changes and a functional block is deleted; B.x steps so far kept the pin map. | Planner |
| CT input | `CT_SENSE` on GPIO6 (U1 pad 6, ADC1_5) | ADC2 is unusable with Wi-Fi on. Pad 6 carries `T_IRQ`, which has no driver. `T_CS` stays where it is. | Planner |
| Touch interrupt | `T_IRQ` → GPIO48 (U1 pad 25, was `LED_DATA`) | Keeps the touchscreen spec intact and can follow the corridor `LED_DATA` used. | Planner |
| Spare pin | GPIO37 (U1 pad 30, was `ADE_RESET`) left unconnected | It is one of the three pins an octal-PSRAM module reserves, so a later module swap has one fewer signal to move. | Planner |
| Burden | 100 Ω (0805) ∥ 33 Ω (0603) = 24.8 Ω | Both values are already BOM lines. With a 2000:1 CT, 1.2 V peak is 68 A rms full scale. The single CT sees the sum of every zone, so the whole kiln must stay under 68 A; fit 33 Ω ∥ 33 Ω (16.5 Ω, 100 A) otherwise. | Planner |
| Bias | 10k/10k divider from `+3V3` (1.65 V), bypassed by 10 µF + 100 nF | Firmware subtracts the measured mean, so the exact bias voltage does not matter. | Planner |
| Anti-alias | 1 kΩ series at the CT end, 100 nF at the module pad | Corner 1.6 kHz; 60 Hz passes at 0.999. 100 nF at the pad is Espressif's ADC recommendation. | Planner |
| Status LED firmware | Keep the `status_led` component; `KILN_PIN_STATUS_LED` gains "−1 = not fitted" and defaults to −1 | Perfboard and dev-kit builds still have an LED; every pin in this project is reconfigurable. | Planner |
| Surface finish | Stay on ENIG | U12 and U10 are still 0.5 mm-pitch parts. Revisit at order time, not here. | Planner |

**Not in this plan:** the CT ADC driver, its zone-separation logic and its API fields (backlog RB-10 is rewritten to specify them, not implemented); the Economic hand-solder split (an order-time choice on the symbols' `Assembly` field); any replacement indicator for the LED; a move to an octal-PSRAM module; editing GitHub issue #315 (ask the user first).

## Global Constraints

- Never text-edit a `.kicad_sch` or `.kicad_pcb`. Use the KiCad GUI or Konnect (load the `konnect` and `kicad-schematic` / `kicad-pcb` skills first), or a script built on `generator/sexp.py`.
- Name a pin by its net or Kconfig symbol everywhere except the three places allowed to state a GPIO number: U1's labels, `main/Kconfig.projbuild` defaults, `docs/pin-assignments.md` §1.
- Every new part reuses an LCSC line already on the BOM: 33 `C23140`, 10k `C17414`, 10uF `C15850`, 100nF `C14663`; R31 moves to the 100R line `C17408`. No new BOM lines.
- `CT_SENSE` copper stays west of x = 88 mm until south of y = 66 mm, so it never enters the thermocouple front-end area around U3/U5.
- Run `idf.py` only through `make firmware` (or `. ./scripts/idf-env.sh && idf.py …` in one command). Run `clang-format -i` on every changed C/H file.
- Work on branch `hw/rev-c-no-led-adc-ct`, not `main`.
- `DESIGN-NOTES.md` is a history: append a rev C section, do not rewrite the B.x sections.

## Review Focus

1. **Stale `sdkconfig`.** Changing a Kconfig default does not change an existing `sdkconfig`; a build tree from B.5 would still drive the WS2812 waveform out of GPIO48 (now `T_IRQ`) and wait for a touch interrupt on the CT pin. Task 2 Step 6 pins this.
2. **CT disconnected or hot-plugged.** With no CT on J12 the ADC pad must sit at the 1.65 V bias through the burden and series resistor, not float. Task 1 Step 8 pins the nets that guarantee it.
3. **CT route passing noisy or sensitive copper.** No checker knows `CT_SENSE` is analog. Task 4 Step 6 is the check against the keep-out in Global Constraints.
4. **Installer clamps one zone only.** The board now has one CT input and the old docs describe one per zone. A CT on a single zone's wire reads half the kiln and looks like a working measurement. Task 5 Step 6 pins the wiring instruction: one clamp on the feed shared by every zone.
5. **Filter cap far from the pad.** C58 only works at the module pad; parked at the CT corner it does nothing against pickup along a 70 mm run. Task 4 Step 3 pins the distance.

---

### Task 1: Schematic — delete the LED and the ADE7953, build the ADC front end

**Files:**
- Modify: `hardware/kicad/sheets/ct.kicad_sch`, `hardware/kicad/sheets/mcu.kicad_sch`, `hardware/kicad/bisque-controller.kicad_sch`
- Modify (title block only): `hardware/kicad/sheets/power.kicad_sch`, `kiln.kicad_sch`, `io.kicad_sch`
- Regenerate: `hardware/kicad/bisque-controller.net`, `bisque-controller.net.stamp`

**Interfaces:**
- Produces: nets `CT_SENSE` (U1 pad 6), `T_IRQ` (U1 pad 25), `/ct/CT_P`, `/ct/CT_BIAS`; U1 pad 30 unconnected; new refs R81–R83, C56–C58; title-block rev `C`.

- [ ] **Step 1: Delete the LED cluster on the `mcu` sheet.** Remove LED1, R3, C10, D3 and the nets `LED_DATA`, `WS_DIN`, `VLED`.

- [ ] **Step 2: Delete the metering block and channel B on the `ct` sheet.** Remove U7, Y1, C25, C27–C37, C40, R30, R33–R38, R59, R60, R61, R65 and J17 (27 parts). Keep D6, J12, R31, R32.

- [ ] **Step 3: Wire the `ct` sheet to exactly this.**

| Ref | Value / footprint / LCSC | Pin 1 | Pin 2 |
|---|---|---|---|
| J12 | unchanged | `CT_P` | `CT_BIAS` |
| R31 | **100R** 0805 `C17408` (was 5R1) | `CT_P` | `CT_BIAS` |
| R81 | 33 0603 `C23140` | `CT_P` | `CT_BIAS` |
| R32 | 1k, unchanged | `CT_P` | `CT_SENSE` |
| C58 | 100nF 0603 `C14663` | `CT_SENSE` | `GND` |
| R82 | 10k 0805 `C17414` | `+3V3` | `CT_BIAS` |
| R83 | 10k 0805 `C17414` | `CT_BIAS` | `GND` |
| C56 | 10uF 0805 `C15850` | `CT_BIAS` | `GND` |
| C57 | 100nF 0603 `C14663` | `CT_BIAS` | `GND` |

D6 (SRV05-4): pins 1 and 4 `CT_P`, pins 3 and 6 `CT_BIAS`, pin 2 `GND`, pin 5 `+3V3`. Copy `MPN`, `Manufacturer` and `LCSC` fields for each new part from an existing part on the same LCSC line. `CT_P` and `CT_BIAS` are sheet-local labels (the old `CTA_P` is renamed); `CT_SENSE` is a hierarchical label (output).

- [ ] **Step 4: Re-point the sheet pins on the root sheet.** Delete the `ct` sheet's `I2C_SDA`, `I2C_SCL` and `ADE_RESET` pins and the `mcu` sheet's `ADE_RESET` pin, with their wires. Add a `CT_SENSE` pin (output on `ct`, input on `mcu`) and wire it.

- [ ] **Step 5: Re-label U1 on the `mcu` sheet.** Pad 6 → `CT_SENSE`, pad 25 → `T_IRQ`, pad 30 → no-connect flag. `T_CS` on pad 5 does not change, and nothing else on `T_IRQ` changes (R43 stays).

- [ ] **Step 6: Set the title blocks.** On all six sheets: rev `C`, date = today, comment 1 `ESP32-S3-WROOM-1U-N16R2 + 2x MAX31856 + dual SSR + CT (ADC)`. `ct` sheet title: `Bisque Kiln Controller - CT current sensing (ESP32 ADC)`.

- [ ] **Step 7: ERC and export.**

Run: `make erc && make pcb-netlist`
Expected: ERC reports 0 violations; the netlist is rewritten and stamped.

- [ ] **Step 8: Verify the nets.**

```bash
cd hardware/kicad && python3 - <<'EOF'
import sys; sys.path.insert(0, "generator")
import netlist as NL
n = NL.load("bisque-controller.net")
u1 = n.comps["U1"]["pins"]
assert (u1["5"], u1["6"], u1["25"]) == ("T_CS", "CT_SENSE", "T_IRQ"), u1
assert u1.get("30") is None, u1.get("30")
for gone in ("U7", "Y1", "LED1", "R3", "C10", "D3", "R30", "C37", "J17", "R34", "R35"):
    assert gone not in n.comps, gone
for new in ("R81", "R82", "R83", "C56", "C57", "C58"):
    assert new in n.comps, new
pins = lambda net: {(r, p) for r, c in n.comps.items() for p, x in c["pins"].items() if x == net}
assert pins("CT_BIAS") >= {("J12", "2"), ("R31", "2"), ("R81", "2"), ("R82", "2"), ("R83", "1")}
assert pins("CT_P") >= {("J12", "1"), ("R31", "1"), ("R32", "1")}
assert pins("CT_SENSE") == {("R32", "2"), ("C58", "1"), ("U1", "6")}
print("rev C netlist OK")
EOF
```

Expected: `rev C netlist OK`. If `NL.load` exposes pins differently, adapt the accessor, not the assertions. The BOM part count (167) is checked in Task 5.

- [ ] **Step 9: Confirm the expected red.**

Run: `python3 hardware/kicad/generator/check_pinmap.py`
Expected: FAIL, naming `LED_DATA` and `ADE_RESET` as not on U1, `KILN_PIN_TOUCH_IRQ` (6 vs 48), `U1 nets with no Kconfig symbol: CT_SENSE`, and three `pin-assignments.md` rows (GPIO 6, 37, 48). Task 2 turns this green.

- [ ] **Step 10: Commit.**

```bash
git add hardware/kicad/bisque-controller.kicad_sch hardware/kicad/sheets hardware/kicad/bisque-controller.net hardware/kicad/bisque-controller.net.stamp
git commit -m "feat(hw): rev C schematic - drop status LED, single CT on ESP32 ADC"
```

---

### Task 2: Pin map in firmware and docs

**Files:**
- Modify: `main/Kconfig.projbuild`, `components/app_config/include/app_config.h`
- Modify: `components/status_led/status_led.c`, `components/status_led/include/status_led.h`, `main/main.c:236-240`
- Modify: `hardware/kicad/generator/check_pinmap.py` (`NET_KCONFIG`)
- Modify: `docs/pin-assignments.md` §1, §2

**Interfaces:**
- Consumes: Task 1's U1 nets.
- Produces: `CONFIG_KILN_PIN_CT` (default 6), `APP_PIN_CT`; `status_led_init()` returns `ESP_ERR_NOT_SUPPORTED` when `APP_PIN_STATUS_LED < 0`.

- [ ] **Step 1: Kconfig.**
  - `KILN_PIN_STATUS_LED`: prompt `Status LED GPIO (WS2812B, -1 = not fitted)`, `default -1`; help says the rev C board has no status LED and a perfboard build sets its own pin.
  - `KILN_PIN_TOUCH_IRQ`: `default 48`. `KILN_PIN_TOUCH_CS` is unchanged.
  - Delete `KILN_PIN_ADE_RESET`.
  - Add `KILN_PIN_CT` (`default 6`), prompt `CT ADC input GPIO (-1 = not fitted)`. Help: must be an ADC1 pin; reads the burden voltage around a mid-rail bias; one CT on the feed shared by every zone; `NOTHING READS THIS PIN YET`.
  - In the `KILN_PIN_I2C_SDA` help, remove the ADE7953 mention; the bus now serves only the Qwiic header and J7.

- [ ] **Step 2: `app_config.h`.** Add `APP_PIN_CT`; fix the I2C comment at line 108.

- [ ] **Step 3: Status LED opt-out.** `status_led_init()` returns `ESP_ERR_NOT_SUPPORTED` before touching RMT when the pin is negative; document it in the header. In `main.c`, log that case at info level as `Status LED not fitted` and keep the existing warning for real failures. The task-creation branch is unchanged.

- [ ] **Step 4: `check_pinmap.py`.** In `NET_KCONFIG` remove `LED_DATA` and `ADE_RESET`; add `"CT_SENSE": "KILN_PIN_CT"`.

- [ ] **Step 5: `docs/pin-assignments.md`.** Replace three rows of the §1 table:

```markdown
| 6 | 6 | ADC1_5 | `CT_SENSE` | CT burden voltage (J12, via R32/C58) | `KILN_PIN_CT` | routed, **no driver** |
| 37 | 30 | — | — | Spare | — | **unconnected** |
| 48 | 25 | — | `T_IRQ` | Touch pen-down interrupt | `KILN_PIN_TOUCH_IRQ` | routed, **no driver** |
```

Change the heading to `as-built, rev C`. Rewrite the "All 30 usable GPIOs are assigned" paragraph: one pin is spare, and `T_IRQ` and `IN3` remain the cheap ones to free after it. Rewrite §2 item 1: ADC1 now carries one analog input. In §6, drop the claim that the ADE7953 is on the I2C bus.

- [ ] **Step 6: Verify.**

```bash
python3 hardware/kicad/generator/check_pinmap.py
rm -f sdkconfig && make firmware
grep -E "CONFIG_KILN_PIN_(STATUS_LED|TOUCH_CS|TOUCH_IRQ|CT)=|KILN_PIN_ADE_RESET" sdkconfig
```

Expected: `check_pinmap: 30 GPIO assignments agree …`; the firmware builds; the grep prints `STATUS_LED=-1`, `TOUCH_CS=5`, `TOUCH_IRQ=48`, `CT=6` and no `ADE_RESET` line. `sdkconfig` is untracked, so deleting it is safe; use `make build` instead of `make firmware` if `spiffs_data/www` is empty. If `sdkconfig.defaults.local` pins any of these symbols, stop and report rather than editing it.

- [ ] **Step 7: Static analysis.**

```bash
clang-format -i components/status_led/status_led.c components/status_led/include/status_led.h components/app_config/include/app_config.h main/main.c
make test-host && make cppcheck && make clang-tidy
grep -E ':[0-9]+:[0-9]+: (warning|error): ' warnings.txt | grep -vc clang-diagnostic-
```

Expected: tests and cppcheck pass; the final count is `0`.

- [ ] **Step 8: Commit.**

```bash
git add main components/status_led components/app_config hardware/kicad/generator/check_pinmap.py docs/pin-assignments.md
git commit -m "feat: rev C pin map - CT ADC input, touch IRQ moved, status LED optional"
```

---

### Task 3: Generator tables and checkers

**Files:**
- Modify: `hardware/kicad/generator/gen_jlc.py` (`LCSC`, `JLC_PLACEMENT`, `MOUSER_ALT`, comments)
- Modify: `hardware/kicad/generator/gen_pcb.py` (`FANOUT`, `EP_VIA_GRID`, `ROUTE_ORDER`, `TITLE_ROWS`, `TP_LABEL_SPECIAL`, the J17 entries near lines 1267, 1436 and 1709, the ENIG comment near line 458)
- Modify: `hardware/kicad/generator/kicad_build.py` (`MODEL_FIXUP`)
- Modify: `hardware/kicad/generator/check_sync_idempotent.py:172-184,252`
- Modify: `hardware/kicad/generator/gen_datasheet_manifest.py` (`DOC_FOR`, `RETIRED`)

**Interfaces:**
- Consumes: Task 1's refs and nets.
- Produces: tables that name only parts and nets that exist, so Task 4's sync and route run clean.

- [ ] **Step 1: `gen_jlc.py`.** Delete the `LCSC` entries for the 31 removed refs (Task 1 Steps 1–2). Change R31 to the `C17408` 100R line. Add R81 (`C23140`), R82, R83 (`C17414`), C56 (`C15850`), C57, C58 (`C14663`), each with the same `fee_free`/`verified` flags as its neighbours on that line. Remove the `JLC_PLACEMENT` entries for `C515890`, `C2838127` and `C2920042`, and the `MOUSER_ALT` entry for `C2920042`. If `check_jlc_placement.py` then reports unused land patterns, remove the oscillator and LED entries from `lcsc_pads.json` as well.

- [ ] **Step 2: `gen_pcb.py`.**
  - `FANOUT`: remove `U7`. `EP_VIA_GRID`: remove `("U7", "29")`.
  - `ROUTE_ORDER`: remove every entry for `ADE_*`, `CTA_*`, `CTB_*`, `LED_DATA`, `WS_DIN`, `VLED`. Add `("CT_P", 0.4)`, `("CT_BIAS", 0.4)`, `("CT_SENSE", SIG_W)` where the `CTA_*` entries were.
  - `TITLE_ROWS`: `"REV B.5"` → `"REV C"`.
  - `TP_LABEL_SPECIAL`: replace the four `CTA_*`/`CTB_*` entries with `"CT_P": "CT +"`, `"CT_BIAS": "CT -"`.
  - Terminal legends: remove the three `J17` entries; J12's pin legend `("A+", "A-")` becomes `("+", "-")`.
  - ENIG comment: the reason is now U12 and U10, not the ADE7953.

- [ ] **Step 3: `kicad_build.py`.** Remove the `U7` and `Y1` entries from `MODEL_FIXUP`.

- [ ] **Step 4: `check_sync_idempotent.py`.** Test 5 renames `/ct/ADE_CS`; point it at `/ct/CT_BIAS` → `/ct/CT_BIASX` (and the bare `ADE_CS`/`ADE_CSX` names with it). In test 6, the first `victims` entry becomes `(name "/ct/CT_BIAS")`.

- [ ] **Step 5: `gen_datasheet_manifest.py`.** Move `ADE7953_Analog_Devices.pdf`, `TFOM_3.579545M_XO_C2838127.pdf` and `WS2812B_RGB_LED_with_integrated_controller.pdf` from `DOC_FOR` to `RETIRED`, following the existing `RETIRED` entries' format, with a note that rev C removed the parts.

- [ ] **Step 6: Verify nothing stale is left.**

```bash
grep -n -E '"(U7|Y1|LED1|J17)"|"ADE_|"CT[AB]_|"(LED_DATA|WS_DIN|VLED)"' hardware/kicad/generator/*.py
cd hardware/kicad && python3 generator/gen_datasheet_manifest.py --check
```

Expected: the grep prints nothing; the manifest check reports no orphans. (`gen_jlc.py` is verified in Task 5, once the board has the new footprints.)

- [ ] **Step 7: Commit.**

```bash
git add hardware/kicad/generator
git commit -m "chore(hw): generator tables for rev C parts and nets"
```

---

### Task 4: Board — sync, place, route

**Files:**
- Modify: `hardware/kicad/bisque-controller.kicad_pcb`

**Interfaces:**
- Consumes: Task 1's netlist, Task 3's tables.
- Produces: a fully routed, DRC-clean rev C board.

- [ ] **Step 1: Record what the sync will orphan.** Before syncing, list the copper on nets that are about to disappear, so Step 2's report can be checked against it:

```bash
cd hardware/kicad && python3 - <<'EOF'
import sys; sys.path.insert(0, "generator")
import board as B
bd = B.load("bisque-controller.kicad_pcb")
dead = lambda n: n and (n.startswith(("ADE_", "CTB_")) or n in ("CTA_F", "CTA_FN", "CTA_N", "LED_DATA", "WS_DIN", "VLED"))
print(sum(1 for t in bd.tracks if dead(t["net"])), "tracks,", sum(1 for v in bd.vias if dead(v["net"])), "vias on dead nets")
print("locked among them:", sum(1 for t in bd.tracks if dead(t["net"]) and t["locked"]))
EOF
```

- [ ] **Step 2: Sync.**

Run: `make pcb-sync`
Expected: 31 refs removed, 6 added and parked east of the outline (R81–R83, C56–C58), R31's value changed, `CTA_P` renamed to `CT_P` with its copper following, U1 pads 6/25/30 re-netted, dead copper reported for the nets from Step 1. Delete that dead copper in KiCad, including the locked ADE7953 escapes, the I2C stubs that ran to U7 and the old `ADE_RESET` run from U1 pad 30 (unlock where needed; they have no pads left to reach).

- [ ] **Step 3: Place the six new parts.**
  - C58: beside U1 pad 6 (pad at about (61.25, 31.94)), its `CT_SENSE` pad within 3 mm of the module pad.
  - R81 next to R31 (93.5, 83.5), sharing its two nets with the shortest possible links.
  - R82, R83, C56, C57: in the area U7 vacated, between D6 (103.0, 83.5) and R31.
  - Run `make pcb-sync` again so the owned silk is re-derived around the new positions and J17's legend is gone.

- [ ] **Step 4: Rip up and route the affected nets.**

Run: `make pcb-route NETS=CT_SENSE,CT_BIAS,CT_P,T_IRQ`
Expected: all four nets routed, none reported failed. `T_IRQ` can follow the corridor `LED_DATA` used from U1 pad 25 toward R43.

**If `CT_SENSE` or `T_IRQ` fails to route after one retry with the order changed, stop and report.** Do not move a pin to make it fit; the pin map is a user decision.

- [ ] **Step 5: Route anything else left open.**

Run: `make pcb-route`
Expected: `0 unconnected` (unconnected `GND`/`+3V3` pads are skipped with a note and need a hand-placed via to the plane).

- [ ] **Step 6: Check the CT route by hand.** Confirm `CT_SENSE` obeys the keep-out in Global Constraints and does not run parallel to the buck's switch node (`SW_5V`, around U11/L1) for more than 5 mm:

```bash
cd hardware/kicad && python3 - <<'EOF'
import sys; sys.path.insert(0, "generator")
import board as B
bd = B.load("bisque-controller.kicad_pcb")
bad = [t for t in bd.tracks if t["net"] == "CT_SENSE"
       and max(t["x1"], t["x2"]) > 88 and min(t["y1"], t["y2"]) < 66]
print("segments inside the thermocouple area:", len(bad)); sys.exit(1 if bad else 0)
EOF
```

Expected: `segments inside the thermocouple area: 0`.

- [ ] **Step 7: Gate.**

Run: `make pcb-check`
Expected: every checker passes, including `check_netlist.py`, `check_sync_idempotent.py`, `check_via_in_pad.py` and `check_silk.py`.

- [ ] **Step 8: Commit.**

```bash
git add hardware/kicad/bisque-controller.kicad_pcb hardware/kicad/bisque-controller-drc.rpt
git commit -m "feat(hw): rev C board - CT front end placed and routed, LED and ADE7953 removed"
```

---

### Task 5: Fab outputs, renders and documentation

**Files:**
- Regenerate: `hardware/kicad/jlcpcb/*`, `hardware/kicad/gerbers/*`, `hardware/kicad/pdf/*`, `hardware/kicad/3d/*`
- Modify: `hardware/kicad/README.md`, `hardware/kicad/DESIGN-NOTES.md`, `hardware/kicad/jlcpcb/README.md`
- Modify: `docs/application-roadmap-and-pcb-provisions.md` §3.6 and its cross-references, `docs/firmware-backlog.md` (RB-9, RB-10), `docs/tasks-and-timers.md`
- Modify: `CLAUDE.md`, `README.md:96`, `hardware/enclosure/README.md`

**Interfaces:**
- Consumes: the routed board from Task 4.

- [ ] **Step 1: Regenerate everything.**

Run: `make pcb`
Expected: sync is a no-op, fab outputs are rewritten, `pcb-check` passes, and the 3D renders are re-raytraced (the stamp changes because footprints changed; if it reports "skipped", run `make pcb-render FORCE=1`).

- [ ] **Step 2: Check the generator's summary against these numbers.**

Run: `cd hardware/kicad && python3 generator/gen_jlc.py jlcpcb | grep -E "parts on the BOM|unique Extended|assembly tier"`
Expected: `167 parts on the BOM/CPL: 167 placed by JLCPCB (49 BOM lines)`, `24 unique Extended part(s)`, and `assembly tier: Standard -> setup $25.56 + stencil $8.21 + 49 BOM lines x $1.53 = $74.97 feeder fees -> $108.74 fixed per order`. `BOM.csv` must contain no `C515890`, `C2838127`, `C2920042`, `C1739` or `C17724`, and the screw-terminal line must read quantity 10.

- [ ] **Step 3: Look at the renders.** Open the regenerated images in `hardware/kicad/3d/` and confirm U7, Y1, LED1 and J17 are gone and the six new passives are present.

- [ ] **Step 4: `hardware/kicad/DESIGN-NOTES.md`.** Append a `## Rev C (date)` section recording: what was removed and why; why one CT channel is enough and what it gives up (see Step 6's backlog text); the front-end values and the 68 A full-scale arithmetic, with the 33 Ω ∥ 33 Ω option for a kiln over 68 A total; that the 100 nF filter cap and 10 µF bias cap form a capacitive divider costing about 1% of gain, absorbed by calibration; why GPIO6 was chosen and why GPIO37 is the spare; that D6 still clamps the CT input; that the status-LED indications now live only on the LCD and the web UI.

- [ ] **Step 5: `hardware/kicad/README.md` and `jlcpcb/README.md`.** Update the block list, the CT section (one terminal, `CT_P`/`CT_BIAS` on J12), the GPIO summary, the terminal counts and designator ranges (eleven 2-position terminals become ten; `J15–J17` becomes `J15, J16`), the silk legend description (`CT +/-`), the BOM/fee paragraphs (54 → 49 lines, $116.39 → $108.74, the Extended list and count), the ENIG rationale, and remove the LED1 sourcing paragraph and the LED1 rows and notes. In `jlcpcb/README.md`, drop LED1 and J17 from the optional hand-solder list and remove the "LED1 is not in it" note.

- [ ] **Step 6: Project docs.**
  - `docs/application-roadmap-and-pcb-provisions.md` §3.6: retitle to the ADC front end; one channel, not one per zone; accuracy about ±2–5% after a one-point calibration; note that it returns to the analog approach the section originally specified. Fix the cross-references that say the CT "went digital".
  - `docs/firmware-backlog.md`, RB-10 becomes "CT current sensing on ADC1" with this specification:
    - Input `CT_SENSE` (`KILN_PIN_CT`); continuous ADC at about 2 kHz; RMS over whole mains cycles with the mean subtracted; one per-board calibration constant; no dependency on RB-9.
    - Single zone: the reading is the kiln's total current. Compare it with the expected current while the SSR is commanded on (dead element, SSR failed open) and with zero while it is commanded off (SSR stuck on).
    - Two zones: attribute current per zone by sampling only in SSR windows where exactly one zone is commanded on. Because zone 2 otherwise follows zone 1's duty, the scheduler must offset the two zones' on-times or insert a short single-zone test pulse.
    - Limits to state in the entry: a stuck-on SSR is detected but not identified without a test pulse; three-phase kilns are not covered by one CT.
  - RB-9 (I2C driver) no longer has an on-board consumer. Leave the issue links; do not edit the GitHub issues.
  - `hardware/enclosure/README.md`: find the CT wiring instruction (`grep -n -i -E "SCT-013|current|ADE7953|WS2812" hardware/enclosure/README.md`) and make it one clamp on the conductor that feeds every zone, upstream of the SSRs; remove the status LED and ADE7953 mentions.
  - `docs/tasks-and-timers.md`: `status_led` runs only when a pin is configured.
  - `CLAUDE.md`: the hardware paragraph (ADE7953 → single-channel ADC CT front end; "ADE7953 and U12 escapes" → "U12 escapes"), and the `status_led/` line (optional, not fitted on rev C).
  - `README.md:96`: remove the status LED and ADE7953 mentions.

- [ ] **Step 7: Sweep for leftovers.**

```bash
grep -rn -i -E "ade7953|ws2812|LED_DATA|ADE_RESET|CT[AB]_|\bJ17\b|rev B\.5" --include='*.md' --include='*.py' --include='*.projbuild' --include='*.h' --include='*.c' . \
  | grep -v -E "node_modules|\.worktrees|managed_components|/build/|docs/superpowers/|REVIEW|DESIGN-NOTES|analysis/|datasheets/"
```

Expected: only deliberate history remains (for example the `RETIRED` datasheet entries and `status_led`'s own WS2812 comments). Fix anything that describes the current board.

- [ ] **Step 8: Final gate and commit.**

```bash
make pcb-check && make lint
git add -A hardware/kicad docs CLAUDE.md README.md hardware/enclosure/README.md
git commit -m "docs(hw): rev C fab package, renders and documentation"
```
