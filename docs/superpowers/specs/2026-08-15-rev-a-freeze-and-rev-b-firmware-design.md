# Rev A Freeze and Rev B Firmware Transition

Date: 2026-08-15
Status: **approved design / not yet implemented**

Companion to [`2026-08-10-pcb-rev-b-hardware-design.md`](2026-08-10-pcb-rev-b-hardware-design.md)
(the board this transition serves) and [`../../pin-assignments.md`](../../pin-assignments.md)
(the as-built rev B pin map).

## 1. The problem

Rev B is a respin, not a variant. Its firmware defaults are already on the
`pcb-rev-b-design` branch and they are **destructive to the rev A perfboard**,
which is the kiln currently in service:

| Change | Effect on the perfboard |
|---|---|
| Nav buttons 4/5/1/6/2 → 38/39/42/40/41 | Nav switch dead |
| `KILN_PIN_LID_SWITCH` → GPIO 4 | Reads lid-open, holds the SSR off, kiln will not heat |
| `sdkconfig.defaults` PSRAM octal → quad | Wrong for the N16R8 module |
| 2× MAX31856 replacing MAX31855 | Different chip; the existing driver cannot read it |

The perfboard must keep firing pots until the PCBs arrive, after which it and
everything specific to it become obsolete.

## 2. Decision: freeze, do not maintain

Rev A is preserved as a **published release**, not a maintained line.

Rejected alternatives, and why:

- **Two-target build** (`BISQUE_BOARD=reva|revb` through the existing
  `BISQUE_PROFILE` hook in `CMakeLists.txt`, plus a CI matrix and board-aware
  OTA asset selection). Correct if the perfboard needed to stay current. It
  does not, and the cost is permanent: every rev B change would have to stay
  rev A-compatible.
- **A rev A dev overlay** (`sdkconfig.defaults.reva`, uncommitted to CI) purely
  to preserve hardware-in-the-loop testing during the wait. Considered and
  declined; see §6.
- **Delaying the rev B merge** until the boards are in hand. Rejected — the
  branch would keep drifting from `main`.

### Consequence: the runtime-probe requirement dies

[`../../heat-treating-extension-plan.md:327`](../../heat-treating-extension-plan.md)
currently requires the thermocouple backend to be **runtime-selectable** —
MAX31856 probed alongside MAX31855 at init — on the grounds that
"a MAX31856-only image would OTA itself onto MAX31855 hardware."

With rev A frozen and never receiving an OTA, that premise is gone. The
MAX31856 driver **replaces** the MAX31855 driver outright. No probe, no dual
backend. That document is now wrong and correcting it is part of this work.

## 3. The freeze procedure

`main` today *is* the rev A firmware, so the freeze point already exists.

1. **Build `main`** — not `pcb-rev-b-design` — flash the perfboard, and **fire
   a real profile end to end.** This gate is not optional: an unverified tag is
   a recovery point that has never been proven to recover anything.
2. **Tag it.** `git tag -a v1.1.0` on that verified commit. Push; `release.yml`
   triggers on `v*` and publishes `bisque-<ver>.bin`, bootloader, partitions,
   spiffs and otadata, plus a Sigstore attestation. Archive the `.bin` locally
   as the recovery image.
3. **Branch it.** `git branch v1 v1.1.0 && git push -u origin v1`.
4. **Merge** `pcb-rev-b-design` → `main` via a PR, so `build.yml` runs against
   it. From then on `main` is rev B only. **Do not tag again** until the PCBs
   arrive and rev A is retired.

### The tag must be an ancestor of `main`

This is not a formality. As of this writing:

```
$ git merge-base --is-ancestor v1.0.0 main   # false
$ git describe --tags main
fatal: No tags can describe '3c3320a...'
```

The repository's only existing tag is **orphaned from the trunk**, which is why
`scripts/version.sh` currently prints a bare commit hash. Since `PROJECT_VER`
flows from that script into `esp_app_desc`, the frozen unit would otherwise
report a hash as its version. The freeze tag is what re-establishes a real
version string on the perfboard, not merely a recovery point.

### Why both a tag and a branch

They do different jobs, and neither substitutes for the other:

- The **tag** is load-bearing: immutable, what `release.yml` builds from, and
  the version the kiln reports.
- The **branch** is an affordance, not preservation — a tag is a ref, so the
  commit is never garbage-collected either way. `v1` exists so that a perfboard
  fix has somewhere to land if one proves necessary. None is planned.

`v1` is not protected, is not built by CI (`build.yml` fires only on `main` and
PRs to `main`, so it costs zero minutes), and takes no PRs. If a fix ever is
needed: branch from `v1`, fix, tag `v1.1.1`, flash over USB, and cherry-pick
forward to `main` if it also applies to rev B.

**Never create a tag literally named `v1`.** `refs/heads/v1` and `refs/tags/v1`
would both answer to `v1` and every `git checkout v1` becomes ambiguous. Tags on
that line stay fully qualified — `v1.1.0`, `v1.1.1`. The branch is the only bare
`v1`.

### OTA needs no code

`ota_check()` and `ota_install_from_manifest()` are separate, both user-initiated
from the API/UI; there is no auto-install task. Combined with not tagging during
the wait, the frozen unit is never offered a rev B image. No board-aware asset
names, no manifest changes, no firmware guard.

## 4. What `main` becomes

Rev B only. No `BISQUE_BOARD` axis, no `sdkconfig.defaults.reva`, no CI matrix.

The firmware half of the merge is already done on `pcb-rev-b-design` and is
small — 3 files, 170 lines:

| File | Change |
|---|---|
| `main/Kconfig.projbuild` | Pin remap; new SSR2/TC2/I2C/touch/WDT/protected-input symbols |
| `components/app_config/include/app_config.h` | `APP_PIN_*` exposure |
| `main/main.c` | `TC_CS`→`TC1_CS`, `SSR`→`SSR1` |

Plus `sdkconfig.defaults` octal → quad PSRAM.

After the merge, HEAD will not run correctly on the perfboard. **That is the
intended state**, not a regression.

## 5. Rev B firmware work

Two items block a board that heats at all. Everything else is additive.

### 5.1 Blocking — MAX31856 driver

`components/thermocouple/` is a MAX31855 driver: a single 32-bit read-only
frame, no register writes, fault reported by bit D16. The MAX31856 needs
config-register setup on init and a separate fault-register decode. Without
this the rev B board reads no temperature at all.

Replaces the MAX31855 driver (see §2). Host tests stub the driver
(`tests/host/stubs/thermocouple_host.c`) and the simulator mocks ESP-IDF
entirely, so the swap does not reach either suite.

### 5.2 Blocking — watchdog kick task

GPIO 36 (`KILN_PIN_WDT_KICK`) feeds a charge pump that gates **both** SSR opto
channels. It needs *transitions* — a pin stuck high fails exactly like a pin
that stopped. Until the kick task exists, every rev B board needs the SJ2
"WDT DEFEAT" solder jumper fitted or it will not heat.

The kick must **stop** on a safety fault. That is the entire purpose of the
circuit.

### 5.3 Additive — not needed for first light

All routed, all with real Kconfig defaults, none driven by any code:

| Function | GPIO | Kconfig |
|---|---|---|
| SSR zone 2 | 21 | `KILN_PIN_SSR2` |
| Thermocouple 2 CS | 35 | `KILN_PIN_TC2_CS` |
| I2C (ADE7953 metering + Qwiic) | 18 / 47 | `KILN_PIN_I2C_SDA` / `_SCL` |
| XPT2046 touch | 5 / 6 | `KILN_PIN_TOUCH_CS` / `_IRQ` |
| Aux bank 2 and 3 (ULN2003) | 15 / 16 | `KILN_PIN_AUX2` / `_AUX3` |
| Protected inputs 2 and 3 | 2 / 1 | `KILN_PIN_IN_GASFLOW` / `_IN_SPARE` |

### 5.4 Documentation debt created by the swap

- `docs/heat-treating-extension-plan.md` §327 and the phase-3 table: the
  runtime-selection requirement is void (§2).
- `APP_PID_KD_DEFAULT` in `app_config.h` and the matching comment in
  `pid_control.c:77` both justify a modest Kd by "the MAX31855's 0.25 °C
  quantization step." The MAX31856 is 19-bit. That rationale no longer holds
  and the default must be revisited on the bench rather than silently
  inherited.
- `docs/perfboard-layout.svg` and `docs/wiring-diagram.svg` become historical.
  Keep them in place with a status line pointing at the rev B pin map, matching
  how `hardware/kicad/FAB-READINESS-REVIEW.md` is already kept as history.

## 6. Accepted risks

- **No hardware-in-the-loop testing until the PCBs arrive.** The MAX31856
  driver and the WDT kick task in particular will be written blind and first
  executed at bring-up. Coverage during the wait is `make sim` / `make
  sim-verify` for the display, host tests for PID, firing scenarios and API
  JSON, and the mock server for web and iOS. Budget bench time for first light.
- **The perfboard is one accidental flash from being unusable.** Post-merge
  firmware leaves it with a dead nav switch and a lid reading open that holds
  the SSR off. Not a brick — recoverable by USB-reflashing the archived
  `v1.1.0` `.bin`.
- **`main` carries no releasable firmware during the wait.** Deliberate: the
  absence of new tags is the mechanism that keeps the frozen unit quiet.
