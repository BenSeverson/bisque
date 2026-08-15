# Rev A Freeze and Rev B Transition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the rev A perfboard firmware behind a verified tag and a `v1` branch, hand `main` to rev B, and correct every document that the handover makes false.

**Architecture:** Rev A is preserved as a published GitHub release, not a maintained line — no board profile, no CI matrix, no OTA changes. `main` becomes rev B only. The documentation debt is then paid in one follow-up PR so `main` is not left internally inconsistent.

**Tech Stack:** git/GitHub Actions (`release.yml` triggers on `v*`, `build.yml` on `main` + PRs to `main`), ESP-IDF, `make test` / `make lint` / `make pcb-check`.

**Spec:** [`docs/superpowers/specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md`](../specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md)

## Global Constraints

- **Task 1 is a human gate.** It requires physical hardware — flashing the perfboard and firing a real profile end to end. An agent cannot complete it and must not mark it done.
- The freeze tag must be an **annotated** tag matching `v*` and must be an **ancestor of `main`**. `v1.0.0` is not (`git merge-base --is-ancestor v1.0.0 main` is false, `git describe --tags main` fails), which is why `scripts/version.sh` currently prints a bare hash.
- **Never create a tag named `v1`.** `refs/heads/v1` and `refs/tags/v1` would both answer to `v1`. Tags on that line stay fully qualified: `v1.1.0`, `v1.1.1`.
- **Do not push any new `v*` tag after Task 1** until the PCBs arrive. An untagged `main` is the mechanism that keeps the frozen perfboard from being offered a rev B image.
- After editing any firmware C/H file, run `clang-format -i` on it. CI's `clang-format` job fails on unformatted code.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| File | Task | Responsibility after this plan |
|---|---|---|
| `docs/heat-treating-extension-plan.md` | 3 | Phase-3 TC plan, corrected to a driver *replacement* |
| `components/app_config/include/app_config.h` | 4 | `APP_PID_KD_DEFAULT` rationale, no longer citing MAX31855 quantization as settled |
| `components/pid_control/pid_control.c` | 4 | Same rationale in the derivative-filter comment |
| `tests/host/stubs/safety_host.c` | 4 | Lid-switch default comment, GPIO 21 → 4 |
| `docs/perfboard-layout.svg` | 5 | Marked historical (rev A) |
| `docs/wiring-diagram.svg` | 5 | Marked historical (rev A) |
| `README.md` | 5 | Perfboard BOM/wiring marked rev A; MAX31855 → MAX31856 in the component tree |
| `CLAUDE.md` | 5 | Hardware Diagrams section and component tree point at rev B |

---

### Task 1: Verify and freeze rev A

**HUMAN GATE — requires the physical perfboard kiln. Do not mark complete without a real firing.**

**Files:** none modified. Produces a tag, a branch, and a GitHub release.

**Interfaces:**
- Produces: the annotated tag `v1.1.0` and the branch `v1`, both consumed by Task 2's ordering constraint (rev B must not reach `main` before the freeze exists).

- [ ] **Step 1: Confirm you are freezing rev A, not rev B**

```bash
git switch main
git log --oneline -1
grep -A1 'config KILN_PIN_BTN_UP' main/Kconfig.projbuild
```

Expected: `KILN_PIN_BTN_UP` defaults to `4` (the rev A perfboard map). If it defaults to `38`, you are on the rev B branch — stop, switch to `main`.

- [ ] **Step 2: Build the freeze candidate**

```bash
./build.sh
```

Expected: `=== Build Complete ===`. This builds the web UI and firmware together; the frozen image must include the SPIFFS web bundle.

- [ ] **Step 3: Flash the perfboard**

```bash
. ./scripts/idf-env.sh && idf.py flash monitor
```

Expected: the kiln boots to the splash and then the dashboard, the 5-way nav switch moves focus, and a temperature reads.

- [ ] **Step 4: Fire a real profile end to end**

Load `docs/smoke-test-profile.json` (or a real bisque profile) and run it to completion on the actual kiln. Follow `docs/bench-smoke-test.md`.

Expected: the firing starts, ramps, holds, and completes; the SSR cycles; history records the run. **This is the step that makes the tag a proven recovery point.** If anything fails, fix it on `main` and restart from Step 2.

- [ ] **Step 5: Tag the verified commit**

```bash
git tag -a v1.1.0 -m "Rev A perfboard — final firmware

Verified on the perfboard kiln with a complete firing before tagging.
Rev A is frozen here: main moves to rev B hardware after this tag.
Recovery image for the perfboard; see docs/superpowers/specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md"
git push origin v1.1.0
```

- [ ] **Step 6: Verify the tag actually describes `main`**

```bash
git merge-base --is-ancestor v1.1.0 main && echo OK-ancestor
git describe --tags main
./scripts/version.sh
```

Expected: `OK-ancestor`, then `v1.1.0` from both commands (not a bare hash). If `describe` still fails, the tag is on the wrong commit — delete and redo it before going further.

- [ ] **Step 7: Create the `v1` branch**

```bash
git branch v1 v1.1.0
git push -u origin v1
```

Do not protect it, do not open PRs against it, do not add it to any workflow trigger.

- [ ] **Step 8: Archive the release artifacts**

Wait for the `Release` workflow to finish, then download `bisque-v1.1.0.bin` (plus bootloader, partitions, spiffs, otadata) from the GitHub release and store them somewhere off GitHub. This is the recovery image for the perfboard.

Expected: `bisque-v1.1.0.bin` exists locally and is the same size the release notes report.

---

### Task 2: Merge rev B to `main`

**Files:**
- Modify (via merge): `main/Kconfig.projbuild`, `components/app_config/include/app_config.h`, `main/main.c`, `sdkconfig.defaults`, plus the `hardware/kicad/` artifacts already on the branch.

**Interfaces:**
- Consumes: the `v1.1.0` tag and `v1` branch from Task 1 — this task must not run before they exist and are pushed.
- Produces: a `main` whose Kconfig pin defaults are rev B, which Tasks 3–5 describe.

- [ ] **Step 1: Confirm the freeze is in place**

```bash
git fetch --all --tags
git rev-parse v1.1.0 && git rev-parse origin/v1
```

Expected: both resolve. If either fails, go back to Task 1 — merging first strands the perfboard with no recovery point.

- [ ] **Step 2: Open the PR**

```bash
git switch pcb-rev-b-design
git push -u origin pcb-rev-b-design
gh pr create --base main --title "feat(hw)!: rev B board and pin map" --body "$(cat <<'EOF'
Rev B is a respin, not a variant. This makes `main` rev B only.

Breaking for the rev A perfboard, deliberately: nav buttons move
4/5/1/6/2 -> 38/39/42/40/41, the lid switch lands on GPIO 4 and holds the
SSR off, PSRAM goes octal -> quad, and rev B fits 2x MAX31856 where the
current driver reads a MAX31855.

Rev A is frozen at v1.1.0 on the `v1` branch, verified with a full firing
before tagging. Do not push a new `v*` tag until the PCBs arrive — an
untagged main is what keeps the frozen perfboard from being offered this
image over OTA.

Design: docs/superpowers/specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md

Follow-up PRs: documentation debt (§5.4), then the MAX31856 driver (§5.1)
and the watchdog kick task (§5.2), both of which the board needs before it
will heat.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verify CI is green, with the pin-map check in particular**

The `build` job runs `make pcb-check`, whose `check_pinmap.py` step asserts `hardware/kicad/generator/design.py` and the Kconfig defaults agree. Both are rev B on this branch, so it should pass — this is the check that proves the merge is self-consistent.

```bash
gh pr checks --watch
```

Expected: all checks pass. A `check_pinmap.py` failure means Kconfig and `design.py` disagree — fix before merging, never merge past it.

- [ ] **Step 4: Merge**

```bash
gh pr merge --merge
git switch main && git pull
```

- [ ] **Step 5: Confirm `main` is now rev B**

```bash
grep -A1 'config KILN_PIN_BTN_UP' main/Kconfig.projbuild
grep -n 'SPIRAM_MODE' sdkconfig.defaults
```

Expected: `default 38`, and `CONFIG_SPIRAM_MODE_QUAD=y`.

---

### Task 3: Correct the thermocouple-backend requirement

The freeze voids `heat-treating-extension-plan.md`'s requirement that the TC backend be runtime-selectable. That requirement existed **only** because OTA would reach MAX31855 hardware. It now never will.

The same section also states as fact that the generated PCB "carries a MAX31855" — false since rev B.

**Files:**
- Modify: `docs/heat-treating-extension-plan.md` (§5.3 "Second thermocouple", and the Phase 3 row of the phase table near line 419)

- [ ] **Step 1: Replace the "second backend, never a replacement" sentence**

Find this text in §5.3 and replace it:

Old:
```
  This phase therefore adds a **second driver backend, never a replacement**: a
  MAX31856 backend in `components/thermocouple/` (config registers on init,
  fault-register decode) alongside the existing MAX31855 one, both generalized to N
  channels.
```

New:
```
  This phase therefore **replaces** the driver: a MAX31856 backend in
  `components/thermocouple/` (config registers on init, fault-register decode)
  takes over from the MAX31855 one, generalized to N channels. It is a
  replacement rather than an addition because rev A is frozen — see the
  installed-base note below.
```

- [ ] **Step 2: Replace the installed-base paragraph**

Old (the whole paragraph beginning `**The installed base makes "replace the driver" a device-bricking change.**` and ending `strictly more work than carrying two small drivers.`):

New:
```
  **The installed base argument no longer applies — rev A is frozen.** This was
  once a device-bricking change: `.github/workflows/release.yml` publishes a
  **single** `bisque.bin` plus one `manifest.json` that all devices fetch from
  `/releases/latest/download/manifest.json`, with no hardware-revision axis, so a
  MAX31856-only image would OTA itself onto MAX31855 hardware and leave it unable
  to read temperature — i.e. unable to fire. That is why this section previously
  required a runtime-probed dual backend.

  It is void as of `v1.1.0`. The only MAX31855 hardware that exists is the rev A
  perfboard, which is frozen on the `v1` branch and never receives an OTA; rev B
  fits 2× MAX31856. So the MAX31856 backend simply replaces its predecessor: no
  probe, no dual backend, no release matrix. See
  [`superpowers/specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md`](superpowers/specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md).
```

- [ ] **Step 3: Correct the Phase 3 table row**

In the phase table, replace `MAX31856 backend *added alongside* MAX31855 with runtime selection` with `MAX31856 backend *replacing* MAX31855 (rev A frozen)`, and replace the risk cell `Medium (needs bench; OTA reaches mixed hardware)` with `Medium (needs bench; rev B hardware only)`.

- [ ] **Step 4: Verify no stale runtime-selection claim survives**

```bash
grep -n "runtime selection\|selectable at runtime\|added alongside\|never a replacement\|mixed hardware" docs/heat-treating-extension-plan.md
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add docs/heat-treating-extension-plan.md
git commit -m "$(cat <<'EOF'
docs: the TC backend replaces its predecessor, it no longer joins it

heat-treating-extension-plan.md required a runtime-probed dual backend on
one ground: release.yml publishes a single image with no hardware axis, so
a MAX31856-only build would OTA itself onto MAX31855 hardware and leave it
unable to fire. That was true while rev A could receive an update.

Rev A is frozen at v1.1.0 on the v1 branch and never will, and rev B fits
2x MAX31856, so the only MAX31855 in existence is unreachable by OTA. The
probe, the dual backend and the release matrix it argued against are all
unnecessary. The section also claimed the generated PCB carries a
MAX31855, which stopped being true at rev B.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Correct the MAX31855-derived PID rationale

`APP_PID_KD_DEFAULT` and the derivative filter are both justified in comments by "the MAX31855's 0.25 °C quantization step." The MAX31856 is 19-bit (0.0078125 °C). The value must **not** be changed here — it needs bench data — but the comment must stop presenting a dead rationale as settled.

`tests/host/stubs/safety_host.c` also carries a stale rev A lid-switch default.

**Files:**
- Modify: `components/app_config/include/app_config.h` (the `APP_PID_KD_DEFAULT` comment)
- Modify: `components/pid_control/pid_control.c:70-80` (the derivative filter comment)
- Modify: `tests/host/stubs/safety_host.c:17-18`

**Interfaces:**
- Consumes: nothing. Comment-only; no behavior changes, so no new tests.

- [ ] **Step 1: Update the Kd comment in `app_config.h`**

Old:
```c
/* Pre-autotune starting derivative gain. Kept modest because the MAX31855's
 * 0.25°C quantization step, at the 1 Hz tick, turns a large Kd into a
 * noise-driven bang-bang term (see pid_compute's filtered derivative). Autotune
 * overrides this; the value is a safe default, not a tuned one — confirm on
 * hardware if changing. */
```

New:
```c
/* Pre-autotune starting derivative gain. Kept modest because the MAX31855's
 * 0.25°C quantization step, at the 1 Hz tick, turned a large Kd into a
 * noise-driven bang-bang term (see pid_compute's filtered derivative).
 *
 * THAT RATIONALE IS REV A's. Rev B reads 2x MAX31856 at 19-bit resolution
 * (0.0078125°C), roughly 32x finer, so the quantization noise this value was
 * chosen to survive is gone. The value is carried forward unchanged because
 * nothing has measured the replacement — revisit it on the bench at rev B
 * bring-up rather than inheriting it silently. Autotune overrides it either
 * way; it is a safe default, not a tuned one. */
```

- [ ] **Step 2: Update the derivative filter comment in `pid_control.c`**

Old:
```c
    /* Derivative on measurement, low-pass filtered (skip first iteration).
       Taking the derivative of the measurement rather than the error avoids a
       kick when the setpoint steps (segment/skip transitions); the first-order
       filter attenuates the MAX31855's 0.25°C quantization noise, which with an
       unfiltered derivative and a large Kd swamped the P/I terms and drove the
       output bang-bang. alpha = dt / (tau + dt). */
```

New:
```c
    /* Derivative on measurement, low-pass filtered (skip first iteration).
       Taking the derivative of the measurement rather than the error avoids a
       kick when the setpoint steps (segment/skip transitions); the first-order
       filter attenuates thermocouple quantization noise, which on rev A's
       MAX31855 (0.25°C steps) with an unfiltered derivative and a large Kd
       swamped the P/I terms and drove the output bang-bang. Rev B's MAX31856
       quantizes ~32x finer, so the filter is cheap insurance there rather than
       load-bearing — keep it, but see APP_PID_KD_DEFAULT before retuning Kd.
       alpha = dt / (tau + dt). */
```

- [ ] **Step 3: Fix the stale lid-switch default in the host stub**

Old:
```c
   is no longer the production default: CONFIG_KILN_PIN_LID_SWITCH defaults to
   GPIO 21 to match the PCB, and -1 is the opt-out for a build with no switch. */
```

New:
```c
   is no longer the production default: CONFIG_KILN_PIN_LID_SWITCH defaults to
   GPIO 4 to match the rev B PCB, and -1 is the opt-out for a build with no
   switch. */
```

- [ ] **Step 4: Format the firmware files**

```bash
clang-format -i components/app_config/include/app_config.h components/pid_control/pid_control.c tests/host/stubs/safety_host.c
```

- [ ] **Step 5: Confirm nothing changed behaviorally**

```bash
git diff --stat
make test
```

Expected: the diff touches only comment lines — **no changed values, no changed code**. `make test` passes (both `test-host` and `test-web`). If any test fails, you edited more than a comment; revert and redo.

- [ ] **Step 6: Commit**

```bash
git add components/app_config/include/app_config.h components/pid_control/pid_control.c tests/host/stubs/safety_host.c
git commit -m "$(cat <<'EOF'
docs: Kd's rationale died with the MAX31855, say so before someone trusts it

APP_PID_KD_DEFAULT and the derivative filter were both justified by the
MAX31855's 0.25 C quantization step swamping the P/I terms. Rev B reads
2x MAX31856 at 19-bit resolution, ~32x finer, so the noise the value was
chosen to survive no longer exists.

The value is deliberately unchanged — nothing has measured the
replacement. The comment now says the number is inherited and untested
rather than reasoned, so bring-up revisits it instead of trusting it.

Also corrects the host stub's claim that the lid switch defaults to GPIO
21; rev B put it on 4.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Mark the perfboard documentation historical

The two SVGs describe rev A wiring and are now history, kept in place the way `hardware/kicad/FAB-READINESS-REVIEW.md` is. `README.md` and `CLAUDE.md` still present the perfboard as current and name the MAX31855 as the driver.

**Files:**
- Modify: `docs/perfboard-layout.svg` (header comment)
- Modify: `docs/wiring-diagram.svg` (header comment)
- Modify: `README.md` (BOM section header, wiring section header, component tree)
- Modify: `CLAUDE.md` (Hardware Diagrams section, component tree)

- [ ] **Step 1: Mark both SVGs historical**

In **both** `docs/perfboard-layout.svg` and `docs/wiring-diagram.svg`, the header comment currently reads:

```
    Generated by: Claude Code (hand-crafted SVG)
    Source of truth: components/app_config/include/app_config.h
    Last updated: 2026-08-05
    To update: ask Claude Code to regenerate, or edit SVG directly
```

Replace with:

```
    HISTORICAL — REV A PERFBOARD ONLY. Frozen at firmware v1.1.0 (branch v1).
    This is NOT the current pin map. Rev B moved most GPIOs; see
    docs/pin-assignments.md for the as-built map and hardware/kicad/ for the
    board that replaced this wiring.

    Generated by: Claude Code (hand-crafted SVG)
    Source of truth (rev A): components/app_config/include/app_config.h @ v1.1.0
    Last updated: 2026-08-05
    Superseded: 2026-08-15
```

Note the removed "To update" line — these are not regenerated any more.

- [ ] **Step 2: Verify the SVGs still parse**

```bash
python3 -c "import xml.dom.minidom,sys; [xml.dom.minidom.parse(f) for f in ['docs/perfboard-layout.svg','docs/wiring-diagram.svg']]; print('both parse OK')"
```

Expected: `both parse OK`. An unescaped `--` inside an XML comment is the easy way to break this.

- [ ] **Step 3: Mark the README's perfboard sections rev A**

Change the BOM heading from `## Bill of Materials` to:

```markdown
## Bill of Materials (rev A perfboard — historical)

> The perfboard build is frozen at firmware `v1.1.0` (branch `v1`). Current
> hardware is the rev B PCB in [`hardware/kicad/`](hardware/kicad/); its pin map
> is [`docs/pin-assignments.md`](docs/pin-assignments.md).
```

Change the wiring heading from `## Wiring` to `## Wiring (rev A perfboard — historical)`.

- [ ] **Step 4: Correct both component trees**

In `README.md`, change:

```
  thermocouple/       MAX31855 SPI driver
```
to
```
  thermocouple/       MAX31856 SPI driver (2 channels)
```

In `CLAUDE.md`, change:

```
  thermocouple/     # MAX31855 SPI thermocouple driver
```
to
```
  thermocouple/     # MAX31856 SPI thermocouple driver (2 channels)
```

Both describe rev B's target state; the driver itself lands in the §5.1 plan.

- [ ] **Step 5: Update CLAUDE.md's Hardware Diagrams section**

Replace:

```markdown
Two SVG diagrams document the perfboard wiring layout:
```

with:

```markdown
Two SVG diagrams document the **rev A perfboard** wiring layout. They are
**historical** — frozen at firmware `v1.1.0` (branch `v1`) and no longer
regenerated. The current pin map is `docs/pin-assignments.md`; the current
hardware is `hardware/kicad/`.
```

And replace the "How to update" bullets:

```markdown
- Ask Claude Code: "update the perfboard layout diagram" or "update the wiring diagram"
- Or edit the SVG directly in any SVG editor (Inkscape, Figma, browser dev tools)
```

with:

```markdown
- **Do not update them.** They describe hardware that no longer exists. A pin
  change belongs in `main/Kconfig.projbuild` and `docs/pin-assignments.md`.
```

Leave the `kicad-cli` bullet and the "Source of truth for pin assignments" line intact.

- [ ] **Step 6: Verify no doc still calls the perfboard current**

```bash
grep -rn "MAX31855" README.md CLAUDE.md
grep -rn "update the perfboard layout diagram" CLAUDE.md
```

Expected: no output from either.

- [ ] **Step 7: Run the full local check**

```bash
make lint && make test
```

Expected: both pass. `make lint` covers the web UI checks and `clang-format --dry-run`; nothing in this task touches C, so it should be unaffected.

- [ ] **Step 8: Commit**

```bash
git add docs/perfboard-layout.svg docs/wiring-diagram.svg README.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: retire the perfboard diagrams instead of leaving them to be believed

The two SVGs describe rev A wiring that no board now has, and both README
and CLAUDE.md still presented the perfboard as the build and the MAX31855
as the driver. A reader following any of it would wire a dead nav switch.

Marks the SVGs historical in their own headers, frozen at v1.1.0 on the v1
branch, and drops the "ask Claude Code to regenerate" instruction — there
is nothing left to regenerate them from. Points both trees at the MAX31856
the rev B board fits.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9: Open the documentation PR**

```bash
gh pr create --base main --title "docs: retire rev A" --body "$(cat <<'EOF'
Pays the documentation debt that merging rev B created (spec §5.4).

- The phase-3 thermocouple plan required a runtime-probed dual backend
  purely because OTA would reach MAX31855 hardware. Rev A is frozen at
  v1.1.0 and never will, so the MAX31856 driver replaces its predecessor.
- Kd's justification was the MAX31855's quantization noise. Rev B's part is
  ~32x finer. Value unchanged, comment no longer presents it as reasoned.
- The perfboard SVGs, README and CLAUDE.md are marked historical.

Design: docs/superpowers/specs/2026-08-15-rev-a-freeze-and-rev-b-firmware-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr checks --watch
```

Expected: all checks pass, then merge.

---

## Out of scope — follow-on plans

Both are **blocking for a rev B board that heats at all**, and both are written blind until bring-up:

- **§5.1 MAX31856 driver.** Replaces `components/thermocouple/`'s read-only 32-bit MAX31855 frame with config-register setup on init and fault-register decode. Without it the board reads no temperature.
- **§5.2 Watchdog kick task.** GPIO 36 feeds a charge pump gating **both** SSR channels and needs transitions — stuck high fails like stopped. Until it exists every board needs the SJ2 "WDT DEFEAT" jumper or it will not heat. The kick must stop on a safety fault.
