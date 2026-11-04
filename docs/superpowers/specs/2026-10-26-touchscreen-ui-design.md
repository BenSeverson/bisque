# Touchscreen LCD UI — design

Status: **proposed**, 2026-10-26. Supersedes the 5-way nav-switch interaction
model described in `CLAUDE.md` § "Input model" and resolves
[RB-11](https://github.com/BenSeverson/bisque/issues/316) (XPT2046 touch
driver) in the "replace" direction, not the "supplement" one.

The next step after this document is approved is a task-level implementation
plan (`docs/superpowers/plans/`). Nothing here is built yet.

## Intent

The rev B board routes the LCD module's resistive touch controller (`T_CS`,
`T_IRQ` on the shared SPI2 bus; `docs/pin-assignments.md` §1) but no driver
reads it, and the whole on-device UI is built around a 5-way switch: focus
groups, an invisible SELECT trap, LEFT/RIGHT polled outside LVGL, and a
contextual menu that only appears when you press SELECT on a bare dashboard.

This design replaces that with a touch-first UI. **The nav switch is dropped
entirely** — no encoder input device, no focus groups, no fallback path. The
existing screens were used as reference for what information matters and
where the eye expects it, not as layouts to port; the interaction model is
different enough that most surfaces are redesigned.

What stays true: the LCD is the *glanceable, at-the-kiln* interface. Profile
authoring, Wi-Fi credentials, webhooks, tokens and cost settings stay on the
web UI. The LCD is for starting, watching, intervening in and reviewing
firings, plus the handful of settings an operator changes standing at the
kiln.

## Goals

- Every operation the LCD offers today is reachable by **tapping visible
  controls**: start a firing (with a delayed start), pause/resume, skip a
  segment, stop, acknowledge an error, run a PID auto-tune, read the last
  firings.
- Add the things touch makes cheap and the switch made awkward: a delayed
  start, firing history, a segment list, the settings an operator changes at
  the kiln, and Wi-Fi setup instructions on the device itself.
- A stray touch — a sleeve, a glove, a clay-dusty knuckle — **never changes
  the kiln's state**. Starting, stopping, skipping and tuning all confirm.
- Usable with gloves and a stylus. Resistive touch works with both, so the
  design must not depend on anything a gloved finger does badly (small
  targets, swipes, long-presses).
- Still fully testable off-hardware: every page and sheet is a simulator
  scene, and the navigation is drivable by synthetic touches in `--verify`.

## Non-goals

- Editing or creating profiles on the LCD. No text entry anywhere; the only
  numeric inputs are steppers.
- Wi-Fi credential entry on the LCD. The device shows how to reach the
  setup page; the page does the rest.
- Multi-touch gestures. The XPT2046 reports one point.
- Backlight dimming or a screen-off timer. `LCD_BL` is a GPIO, not PWM.
- A board respin. The five `BTN_*` nets and header J6 stay on rev B; the
  firmware just stops reading them (see "Dropping the buttons").
- Keeping the 5-way switch as a fallback. That doubles every surface's test
  matrix and is the thing this design exists to remove.

## Anti-goals

- A dialog that can be confirmed by the same tap that opened it (double
  registration on a resistive panel is real).
- A surface with no visible way back. The switch model needed Cancel buttons
  for this reason; touch keeps the rule.
- A hidden gesture that is the only way to do something.
- Losing the live temperature from view. Whatever page is open during a
  firing, the status and temperature are still on screen.

## Constraints

- **Panel:** ST7796S 480×320 landscape, 16-bit, SPI at 40 MHz, partial
  double-buffered refresh at ~30 FPS. LVGL 9.6, `LV_MEM_SIZE` 24 KiB, fonts
  Montserrat 24/36/48 only. Runtime image decoders stay off.
- **Touch:** XPT2046 resistive, on the LCD module, on the shared SPI2 bus
  (≤ 2.5 MHz), `T_CS` + `T_IRQ` on dedicated GPIOs. Single point, pressure
  available, no hover. Needs a stored calibration.
- **Physical scale:** the 3.5" and 4.0" variants of this module family are
  both 480×320, so pixel density is 5.7–6.5 px/mm. A fingertip pad is
  ~9 mm; a gloved one more. **Minimum target 56 px** on the short axis covers
  ≥ 8.6 mm on either panel.
- **RAM:** the dashboard and one full-screen modal already coexist in the
  24 KiB LVGL pool today. The design keeps at most *three* live widget trees
  (Home, one Page, one Sheet); if the builder's measurement in the simulator
  shows pressure, `LV_MEM_SIZE` goes to 32 KiB, which the `sdkconfig.defaults`
  comment already anticipates.
- **Threading:** unchanged. All widget work under `lv_lock()`; the pointer
  input device is read inside `lv_timer_handler()` like any LVGL indev.

## Interaction model

The rules below are numbered so the implementation plan and reviews can cite
them.

**R1 — Tap is the only required gesture.** Every task is completable with
taps alone. Dragging scrolls lists and nothing else; every scrollable list
also has page buttons, so drag is a convenience. No swipe-back, no
long-press menus, no double-tap. Holding a stepper button auto-repeats, but
single taps get you there too.

**R2 — Everything tappable looks like a button, and nothing else is tappable.**
Targets are raised faces (`UI_COLOR_BUTTON_BG` or an accent) with a radius,
at least **56 px** tall and 56 px wide, at least **12 px** from any other
target. Plain labels are never targets. The two "card" targets (the chart
card and list rows) are full-width bordered surfaces with a `›` affordance.

**R3 — Press feedback, release to act.** The theme gives every button and
list row an `LV_STATE_PRESSED` style (face darkened ~12 %). Actions fire on
`LV_EVENT_CLICKED`, i.e. release inside the target, so sliding off cancels.
No sound: the buzzer is an alarm, not a click.

**R4 — Navigation is a stack: Home → Page → Sheet.** Home is the adaptive
dashboard. A *Page* replaces Home's content area and is headed by the global
bar (R6). A *Sheet* is a centred card over a dimming scrim, on top of Home or
a Page. Depth never exceeds three, and only one Page and one Sheet exist at
a time. Every Page has a **← Back** button at the top-left of the bar; every
Sheet has **Cancel** (or **Close**) as its bottom-left button. Tapping the
scrim does nothing — one way back, always in the same place.

**R5 — Actions that affect the kiln confirm; reversible ones don't.**
Confirm: Start firing, Stop, Skip segment, Cancel scheduled start, Start
auto-tune, Stop auto-tune. No confirm: Pause (heat off is the safe
direction), Resume (restores a state the operator chose), Done, Clear error
(both only acknowledge). A confirm Sheet names what it will do in the title
and the consequence in one line.

**R6 — The global bar is always on screen.** The 48-px bar at the top is
coloured by `ui_status_color()` on every surface. On Home it carries the
status word, markers (LID, VENT) and segment, as today, plus a **≡ Menu**
button `(408, 0, 72, 48)` at its right end in every Home state — the one
route to History, Settings and Segments that does not depend on which
action bar is showing (an alarm toggle or the segment list must be reachable
mid-firing). On a Page it carries ← Back, the page title, and the live
temperature on the right, so a firing is never out of sight. Back and Menu
are the bar's only targets; both are screen-edge targets, so 48 px tall is
acceptable (R2's 56 applies to free-standing targets).

**R7 — Double-tap guard.** Every Sheet ignores input for its first
**300 ms**, which is the protection that always applies: a resistive press
that registers twice across the transition lands on a Sheet that is not yet
listening. On top of that, a Sheet opened from the **Home action bar** (Stop,
Skip, Cancel start, Stop auto-tune) keeps its buttons at y ≤ 240, clear of the
bar at y 256–312, so a late second registration cannot reach a confirming
button at all. Sheets opened from list rows (Start, Choice, Firing detail)
live on Pages, which have no action bar; for them the 300 ms guard is the
rule, since a row spans the width of the page and no button placement can
avoid it.

**R8 — Surfaces time out back to Home.** A Sheet with no touch for **60 s**
closes; a Page with no touch for **120 s** pops to Home. Exceptions:
Calibration (nothing else is usable until it finishes) and the Auto-tune and
Network pages while an auto-tune is running or the device is in setup mode.
Rationale: the operator walks away mid-dialog, and the next glance at the
kiln should be the dashboard.

**R9 — State changes close what they invalidate.** When the firing status
family changes (idle / scheduled / active / paused / complete / error /
auto-tune), any open Sheet closes — its premise is gone (a "Skip segment?"
over a firing that just finished). A transition **into ERROR** also pops any
Page, so the error screen is what the operator sees. Other transitions leave
Pages alone. Calibration (S12) is exempt from R9 as it is from R8: the bar is
red on Home the moment it finishes, and a half-done calibration is worse
than a slightly delayed error screen.

**R10 — No text entry, steppers only.** The only numeric inputs are
`[−] value [+]` steppers: 56×56 buttons, 36-px value, hold to auto-repeat
(400 ms, then 10 steps/s), range clamped and shown.

## Layout system

All coordinates are pixels on the 480×320 canvas; `(x, y, w, h)`.

| Token | Value | Use |
|---|---|---|
| `UI_BAR_H` | 48 | global bar height |
| `UI_MARGIN` | 12 | screen edge margin |
| `UI_GAP` | 12 | between targets |
| `UI_TARGET_MIN` | 56 | minimum target height/width |
| `UI_ACTION_BAR_Y` | 256 | top of the Home action bar |
| `UI_ROW_H` | 64 | list row height (3 rows fit a Page) |
| `UI_SHEET_W` | 440 | sheet card width |
| `UI_COLOR_SCRIM` | black @ 50 % | sheet backdrop |
| `UI_COLOR_PRESSED` | face darkened 12 % | R3 feedback |

**Home action bar.** Three slots at y 256, h 56: left `(12, 256, 140, 56)`,
centre `(164, 256, 152, 56)`, right `(328, 256, 140, 56)`. The centre slot is
the primary action. A state with one action spans all three
`(12, 256, 456, 56)`. Home content is `(0, 48, 480, 200)`.

**Page.** Bar `(0, 0, 480, 48)`: Back `(0, 0, 72, 48)` — full bar height,
screen-edge target so 48 px is acceptable — title centred, live temperature
right-aligned at x 468. Content `(12, 60, 456, 248)`. A scrolling Page splits
content into the list `(12, 60, 388, 248)` and a scroll column
`(412, 60, 56, 248)` with ▲ `(412, 60, 56, 118)` and ▼ `(412, 190, 56, 118)`
page buttons; the list's scrollbar is always visible when it overflows.

**Sheet.** Card `(20, y, 440, h)`, white, radius 12, 1-px
`UI_COLOR_BORDER`, over the scrim. Title (36 px) at the top, body (24 px,
`UI_COLOR_TEXT_DIM`), then a button row: Cancel `(36, y+h−68, 196, 56)` and
the primary `(248, y+h−68, 196, 56)`. A one-button Sheet centres Close
`(142, y+h−68, 196, 56)`. Two height classes:

- **Confirm Sheet** (opened from the action bar): top 56, height ≤ 196, so
  its buttons end at ≤ 240 (R7). Title + one body line + buttons = 44 + 30 +
  56 + 4×12 = 178; fits.
- **Page Sheet** (opened from a row): top 60, height ≤ 244, buttons end at
  ≤ 292. The Start Sheet uses all of it: title 44, body 30, stepper 56,
  buttons 56, five 12-px gaps.

**Choice Sheet.** Title, then one full-width option row per choice
`(36, …, 408, 56)` with 12-px gaps, the current value marked with a filled
dot and `UI_COLOR_HEATING` text; tapping an option applies it and closes the
sheet. Cancel below. Up to four options fit.

## Screens

### S1 — Splash

Unchanged (`splash.c`). No targets. One addition: a touch held anywhere
during the splash resets the stored touch calibration, so a bad calibration
can never lock the operator out (see S12). Mechanics: `run_splash_phase()`
does not exit while `T_IRQ` is asserted (up to 10 s, so a shorted panel
cannot hang boot); at 3 s of continuous pen-down the status line reads
"Touch calibration reset", the NVS entry is erased, and S12 runs after the
splash in the same boot. Coordinates are never read, so it works whatever
the calibration says.

### S2 — Home · Idle

```
┌────────────────────────────────────────────────────┐ 0
│ IDLE                                 (green)    ≡  │ 48
│                                                    │
│      1 0 1 ° C      ┆  LAST FIRING                 │
│      Ready          ┆  Glaze Cone 6                │
│                     ┆  Peak 1222°C · 8h 02m · OK   │
│                                                    │
├──────────┬────────────────────┬────────────────────┤ 256
│ History  │   Start firing  ●  │   Settings         │ 312
└──────────┴────────────────────┴────────────────────┘ 320
```

- Temperature 48 px at `(12, 64)`, "Ready" 24 px dim beneath. If the
  thermocouple faults: "—" and "TC fault" in `UI_COLOR_ERROR`.
- Right half `(240, 64, 228, 180)`: last firing (name, peak · duration ·
  outcome) when history has one; otherwise empty.
- Setup-mode hint: when the device is in AP mode (`wifi_manager_is_ap_mode()`),
  the right half shows "Wi-Fi setup: join **Bisque**, open 192.168.4.1" in
  place of the last firing. Tapping Settings › Network gives the full text.
- Action bar: **History** → S8, **Start firing** (orange) → S6,
  **Settings** → S9. The bar's **≡** opens the Menu Sheet (S2a) in every
  Home state; on Idle it duplicates the two side buttons, which is accepted
  for the sake of the ≡ always being there.

### S2a — Sheet · Menu

Opened by ≡ on any Home state. Option rows (choice-Sheet layout): **Segments**
(present only while active or paused) → S7, **History** → S8, **Settings**
→ S9, then Cancel. This is how History and Settings are reached during a
firing, when the action bar is spent on Pause/Skip/Stop.

### S3 — Home · Scheduled (delayed start armed)

Status is `IDLE` with `delay_remaining > 0`. The LCD does not show this
today; it should, because it is the state an operator leaves a kiln in
overnight.

- Bar reads **SCHEDULED** in `UI_COLOR_HOLDING` (my call: the yellow family
  already means "waiting").
- Content: temperature as S2 on the left; right half: profile name (36 px),
  "Starts in 1h 23m" (24 px) counting down each tick.
- "Starts in" is a countdown only. **No wall-clock time on the LCD**: the
  firmware runs SNTP but has no timezone setting, so `localtime()` is UTC
  and would disagree with the web UI, which uses the browser's zone. A
  timezone setting is a cross-cutting change (settings struct, NVS, API,
  both schemas, iOS) and is out of scope here; until it exists the LCD shows
  durations and never times of day.
- Action bar: **History**, **Cancel start** (red) → confirm Sheet
  "Cancel the scheduled firing?" / "Glaze Cone 6 will not start." →
  `FIRING_CMD_STOP` (the engine already clears `delay_active` on STOP),
  **Settings**.

### S4 — Home · Active (heating / holding / cooling)

```
┌────────────────────────────────────────────────────┐ 0
│ HEATING                     LID  VENT  SEG 2/3  ≡  │ 48
│ 1180°C          ┆┌──────────────────────[Segments ›]┐
│ › 1222°C        ┆│                              ╱   │
│ ───────────     ┆│                        ╱╱╱╱╱     │
│ Elapsed 5h 32m  ┆│                  ╱╱╱             │
│ Left   ~2h 14m  ┆└──────────────────────────────────┘
├──────────┬────────────────────┬────────────────────┤ 256
│ Pause    │   Skip segment     │   Stop         (red)│ 312
└──────────┴────────────────────┴────────────────────┘ 320
```

- Left column `(12, 56, 184, 192)`: temperature 48 px; target with the `›`
  prefix 24 px dim; separator; "Elapsed 5h 32m" and "Left ~2h 14m" as single
  24-px lines (the stacked header/value pairs of the current layout do not
  fit above an action bar).
- Chart card `(208, 56, 260, 192)`: the existing planned-vs-actual chart,
  same series, same y-range logic. A **Segments ›** chip in the card's
  top-right corner; the whole card is one target → S7.
- Action bar: **Pause** → `FIRING_CMD_PAUSE`, no confirm. **Skip segment** →
  Skip Sheet (below). **Stop** (red) → Sheet "Stop the firing?" / "Elements
  turn off. Progress is lost." → `FIRING_CMD_STOP`.
- **Skip Sheet.** The engine refuses two kinds of skip silently (a log line
  only): one into a segment whose ramp direction contradicts the current
  temperature, and one while paused. A confirmed dialog that does nothing
  is the worst outcome, so the Sheet evaluates the same rule the engine does
  — next segment's `target_temp − current_temp` against the sign of its
  `ramp_rate`, from the cached profile — before it offers anything:
  - ordinary case: "Skip to segment 3?" / "Segment 2 ends now. Next: ▲
    150°/h → 1222°C, hold 10m." → Cancel · **Skip**;
  - last segment: "End the firing now?" / "This is the last segment. The
    firing completes." → Cancel · **End firing** (the engine completes on a
    last-segment skip);
  - contradicting ramp: "Can't skip yet" / "Segment 3 ramps down, but the
    kiln is below its target. Stop instead, or wait." → **Close** only.
- Holding/cooling differ only in bar colour and text, as today.

### S5 — Home · Paused

S4's layout with the chart kept alive (same `LAYOUT_ACTIVE` reuse as today)
and a "PAUSED" watermark over the chart. **No Skip while paused**: the
engine ignores it on purpose (a skip would re-energise elements the operator
believes are off), so the bar is **Resume** (orange, spanning the left and
centre slots `(12, 256, 304, 56)`) → `FIRING_CMD_RESUME`, no confirm, and
**Stop** (red). A lid-open pause (`lid_mode = pause`) replaces Resume's label
with "Lid open — close to resume" on a disabled face, since the engine
auto-resumes.

### S4a — Home · Auto-tune

Bar **AUTOTUNE** (orange). Left column: temperature, "Setpoint 1000°C",
"Elapsed 12m 30s", "Cycle 3" from `firing_engine_get_autotune_snapshot()`.
Chart card without the planned series, no Segments chip. Action bar: a
single full-width **Stop auto-tune** (red) → confirm Sheet →
`FIRING_CMD_AUTOTUNE_STOP`.

### S4b — Home · Complete

Bar **COMPLETE** (green). Content: "Firing complete" 36 px, profile name,
"Peak 1222°C · 8h 02m", "Now 850°C, cooling" updating. Action bar:
**History**, **Done** (green) → `FIRING_CMD_STOP` (the engine's
acknowledge path; takes the view to Idle), **Settings**.

### S4c — Home · Error

Bar **ERROR** (red). Content: "Firing stopped" 36 px, the
`error_code_description()` line, "Last reading 850°C", "Stopped at Seg 2 /
4h 00m". Action bar: **History**, **Clear error** → `FIRING_CMD_STOP` (same
acknowledgement the SELECT trap does today, with the same "must actually
queue" rule), **Settings**. An error pops every Page and Sheet (R9).

### S6 — Page · Profiles

Reached from Start firing. Title "Start a firing", scrolling Page.

```
│ ← │ Start a firing                        101°C │ 48
│ ┌──────────────────────────────────────┐ ┌────┐│
│ │ Bisque Cone 04            1060°C  9h ││ ▲  ││
│ ├──────────────────────────────────────┤ │    ││
│ │ Glaze Cone 6              1222°C  8h ││────││
│ ├──────────────────────────────────────┤ │ ▼  ││
│ │ Slow bisque               1060°C 12h ││    ││
│ └──────────────────────────────────────┘ └────┘│
```

- Rows 64 px: name 24 px, max temp and duration right-aligned dim. Profile
  IDs are listed once at open (`firing_engine_list_profiles`) and each row
  loads its profile on build, as today — BSS stays small.
- Tap a row → S6a. No profiles → one dim line "No profiles. Add one on the
  web UI." and Back.

### S6a — Sheet · Start

Title "Start Glaze Cone 6?". Body line "Max 1222°C · ~8h 00m · 5 segments".
Stepper row: "Start in" `[−]` **Now** `[+]` — steps of 30 min, range 0–24 h,
value shows "Now" at 0, "1h 30m" otherwise. No "≈ 21:45" wall-clock hint
(see S3: the device has no timezone). Buttons: **Cancel**, **Start**
(orange) → `FIRING_CMD_START` with `delay_minutes`, then pop to Home. A
Page Sheet: top 60, height 244.

### S7 — Page · Segments

From the chart card or the Menu Sheet during an active/paused firing. Title
is the profile name. Scrolling list, rows 56 px:

```
│ 1  ▲ 100°/h → 600°C      hold 0m          done │
│ 2  ▲ 150°/h → 1222°C     hold 10m          now │  ← status-coloured
│ 3  ▼ 80°/h → 500°C       hold 0m               │
```

Rates through `ui_temp_rate()`, targets through `ui_temp_value()`. Done rows
dim, the current row filled in `ui_status_color()`, `FIRING_HOLD_INDEFINITE`
shown as "hold until skipped". Read-only; Back returns to Home.

### S8 — Page · History

Title "Firing history". Scrolling list of up to 20 rows, newest first:

```
│ Glaze Cone 6           1222°C  8h 02m   ● OK    │
│ Bisque Cone 04         1060°C  3h 10m   ● Error │
│ Slow bisque            1060°C 12h 00m   ● Stop  │
```

Outcome dot: complete green, error red, aborted dim. Tap a row → S8a. No
clear-history control on the LCD (web only).

### S8a — Sheet · Firing detail

Title: profile name. Body lines: outcome text, "Peak 1222°C", "Duration
8h 02m", and the `error_code_description()` for an error outcome. No
started-at time (see S3); the web history has the dates. One **Close**
button.

### S9 — Page · Settings

Title "Settings". Scrolling list, rows 64 px, each "Label …… value ›":

| Row | Tap → | Options / page |
|---|---|---|
| Temperature unit | choice Sheet | °C, °F |
| Lid switch | choice Sheet | Warn, Pause, Interlock — row hidden when `LID_STATE_NOT_FITTED` |
| Alarm | choice Sheet | On, Off |
| PID auto-tune | Page S10 | |
| Touch calibration | Page S12 | |
| Network | Page S11 | |
| About | Page S13 | |

Choice Sheets write through `firing_engine_set_settings()` (read-modify-
write of the full `kiln_settings_t`, exactly as the web PUT does). Only
settings an operator changes at the kiln are here; everything else stays on
the web UI on purpose.

### S10 — Page · PID auto-tune

Title "PID auto-tune". Content: one explanatory line ("Heats to the setpoint
and oscillates to measure the kiln. Takes 30–60 min."), a stepper "Setpoint"
`[−]` **1000°C** `[+]` in 25 °C steps clamped to `safety_get_max_temp()`, and
the last result: "Last run: complete · Kp 12.0 Ki 0.40 Kd 8.0" or "failed" or
"never run" from the autotune snapshot and `firing_engine_get_pid_gains()`.
Bottom: **Start auto-tune** (orange, `(164, 256, 304, 56)`) → confirm Sheet
"Start auto-tune at 1000°C?" / "The kiln will heat. Do not load ware." →
`FIRING_CMD_AUTOTUNE_START` with the web UI's default hysteresis, then Home.
Only shown enabled when idle.

### S11 — Page · Network

Title "Network". Two variants:

- **Connected:** "Connected to ‹SSID›", "http://192.168.1.50",
  "http://bisque.local", and a QR code of the IP URL on the right (`LV_USE_QRCODE`,
  LVGL's built-in generator, ~2 KB of code and no decoder — a phone scan
  replaces typing an address at a kiln). My call; drop the QR if flash is
  tight, the text is sufficient.
- **Setup mode (AP):** "Wi-Fi setup", "1. Join Wi-Fi **Bisque**",
  "2. Password **bisquesetup**", "3. Open **http://192.168.4.1**", QR of the
  URL. This page does not time out while in AP mode (R8).

No controls beyond Back. Requires the display component to depend on
`wifi_manager` and a new `wifi_manager_get_ssid()` (the station SSID it was
initialised with; there is no getter today). The AP name and password come
from `APP_WIFI_AP_SSID` / `APP_WIFI_AP_PASS`, never literal strings. The
simulator mocks the four getters.

### S12 — Page · Touch calibration

Full-screen, replaces the bar too (the bar is itself a touch target the
calibration is about). Sequence:

1. "Tap the target" with a crosshair at `(48, 48)`, then `(432, 48)`,
   `(432, 272)`, `(48, 272)`. Each tap must be ≥ 2 stable samples; the raw
   point is kept.
2. Least-squares affine fit (6 coefficients) from the four pairs.
3. Verification: a crosshair at `(240, 160)`; if the mapped tap lands within
   12 px → "Calibrated" and save to NVS (`touch` namespace); else "Try again"
   and restart from step 1. Three failures → keep the previous calibration
   and show "Calibration failed — using default", Back.
4. Runs automatically after the splash when NVS holds no calibration;
   otherwise from Settings. Does not time out. No Back during the automatic
   first run (there is nothing usable to go back to); from Settings, Back is
   available on the first screen.
5. **Touch absent.** When `KILN_PIN_TOUCH_CS` is −1 or the driver fails to
   initialise (no controller answers), the automatic run is skipped, Home
   loads read-only, and the bar's ≡ position shows a dim "NO TOUCH" marker.
   The kiln still fires from the web UI and the dashboard still shows it.
   Rev A boards are frozen on their own firmware and never receive this
   one, so this path is for a dead or unfitted panel on rev B, not a
   supported configuration.

Factory default coefficients map the XPT2046's typical raw range
(~200–3900) onto the panel with the same `swap_xy` the display uses, so an
uncalibrated unit is roughly usable and the S1 reset gesture always leads
here.

### S13 — Page · About

Title "About". Lines: firmware version (`ota_current_version()`), element
hours (`firing_engine_get_element_hours_s()` in h), IP, uptime. Back only.

## Sheets summary

| Sheet | Opened from | Title / body | Buttons |
|---|---|---|---|
| Menu | Home ≡ | — / Segments, History, Settings rows | Cancel |
| Start | S6 row | "Start ‹name›?" / details + delay stepper | Cancel · Start |
| Stop | S4/S5 Stop | "Stop the firing?" / "Elements turn off. Progress is lost." | Cancel · Stop (red) |
| Skip | S4 Skip | "Skip to segment N?" / "End the firing now?" / "Can't skip yet" | Cancel · Skip, or Close |
| Cancel scheduled | S3 | "Cancel the scheduled firing?" / "‹name› will not start." | Cancel · Cancel start (red) |
| Stop auto-tune | S4a | "Stop auto-tune?" / "Gains will not be saved." | Cancel · Stop (red) |
| Start auto-tune | S10 | "Start auto-tune at N°?" / "The kiln will heat." | Cancel · Start |
| Choice | S9 rows | setting name / option rows | Cancel |
| Firing detail | S8 row | profile name / record lines | Close |

## Touch input pipeline

- **Driver:** `esp_lcd_touch_xpt2046` from the component registry
  (atanisoft), which takes an `esp_lcd_panel_io_spi` handle — the same
  pattern `display_init.c` already uses for the panel — with its own CS and a
  2 MHz clock on the shared SPI2 bus, `int_gpio_num = T_IRQ`. The host
  serialises bus transactions, so the panel's 40 MHz DMA stream and the
  thermocouple reads are unaffected. The in-house alternative is ~150 lines
  (three 24-bit commands plus median-of-3); fall back to it only if the
  component's bus handling does not fit.
- **Indev:** one `LV_INDEV_TYPE_POINTER`, `g_indev_touch`, read callback
  polled at LVGL's default 30 ms. The callback checks `T_IRQ` first and skips
  the SPI read when the pen is up, so idle cost is one GPIO read. Nothing in
  this design *needs* the interrupt line: with `KILN_PIN_TOUCH_IRQ = −1` the
  callback reads the controller's pressure (Z) every poll instead, and the
  S1 reset gesture keys off that same pen-down. `docs/pin-assignments.md`
  lists `T_IRQ` as a pin that could be freed; if it is, the cost is ~100 µs
  of SPI every 30 ms, nothing in the UI.
- **Sampling:** on pen-down, the controller's X/Y are read three times and
  medianed; a press is reported only after two consecutive samples within
  8 px (≈ 60 ms), which rejects the first-contact edge jitter resistive
  panels produce. Pressure (Z) below the threshold counts as pen-up.
- **Calibration:** `touch_calib.c`, pure C — an affine map, the
  least-squares fit from four pairs, NVS serialisation — with no ESP-IDF
  dependency so `tests/host/test_touch_calib.c` can drive it. The driver
  applies it before handing points to LVGL.
- **What goes away:** `g_indev_encoder`, `g_input_group`, `g_modal_group`,
  `s_select_trap`, `encoder_read_cb`, `btn_is_pressed`, auto-repeat,
  `display_consume_left/right_press`, `route_lr_focus`,
  `dashboard_modal_nav_left/right`, `lv_group_*` everywhere, and the
  `LV_STATE_FOCUSED` theme styles.

## Dropping the buttons

- **Firmware:** `KILN_PIN_BTN_*` leave `main/Kconfig.projbuild` and
  `APP_PIN_BTN_*` leave `app_config.h`. No GPIO is configured for them.
- **Board:** rev B keeps the five `BTN_*` nets and J6. No respin for a
  firmware change; a rev C may repurpose the header.
- **`check_pinmap.py`:** maps `BTN_*` → `KILN_PIN_BTN_*` today and would
  fail once the symbols go. Add a `ROUTED_NO_DRIVER` set for the five nets
  (beside `NO_KCONFIG_SYMBOL`), and mark their rows in
  `docs/pin-assignments.md` §1 "routed to J6, unused by firmware". My call;
  the alternative — keeping dead Kconfig symbols — is what the touch pins
  used to do and it misled.
- **Docs:** `CLAUDE.md` § "Input model" and the `display.h` header comment
  are rewritten to this model.

## Simulator and tests

- `lv_sdl_mouse_create()` replaces the keyboard encoder; `S` (cycle presets)
  and `Q` stay. `LV_SDL_MOUSEWHEEL_MODE` becomes irrelevant.
- `--screenshot` / `--diff` gain one scene per Page and Sheet: menu sheet
  (idle and active), profiles, start sheet, segments, history, firing
  detail, settings, choice sheet, auto-tune, network (both variants), about,
  calibration step 1, stop/skip (all three variants)/cancel-scheduled/
  stop-autotune confirms, scheduled Home, auto-tune Home, no-touch Home.
  Baselines are regenerated once, deliberately, as part of the switchover.
- `--verify` drives navigation by **synthetic touches**: the sim's pointer
  indev read callback is fed `(x, y, pressed)` from the test, and sequences
  assert on the stack and widget tree. Required sequences: Stop → Cancel
  leaves the firing untouched; Stop → Stop sends the command; a Sheet
  ignores a tap inside 300 ms (R7); ERROR pops a Page (R9); a status change
  closes a Sheet (R9); a Sheet closes after 60 s (R8); the Start sheet's
  stepper clamps; the Settings choice writes the setting; a `--verify` pass
  with the stack at depth 3 reports `lv_mem_monitor` free bytes above a
  floor.
- `make test-host` gains the calibration fit test.

## Implementation phases

Each is a reviewable PR; the switchover is complete at phase 4, phases 5–6
are the additions touch makes possible.

1. **Input.** Touch driver + indev + calibration module and host test +
   S12 + S1 reset gesture. The existing UI becomes tappable where it already
   has buttons; the encoder stays for one phase so the device is never
   unusable mid-migration.
2. **Model.** Remove the encoder, groups, trap and L/R polling. Theme:
   pressed styles in, focused styles out, scrim/sheet/action-bar styles.
   `modal.c` becomes the Home/Page/Sheet stack with R7/R8/R9 built in.
   New helpers in `ui_widgets.h`: action bar, page header, sheet, choice
   sheet, stepper, list row. Simulator: SDL mouse, synthetic-touch `--verify`.
3. **Home.** S2–S5, S4a–S4c with their action bars, the ≡ Menu Sheet and
   the confirm Sheets. Pixel baselines regenerated.
4. **Start.** S6 + S6a with the delayed start, S3. Buttons dropped from
   Kconfig/app_config/pinmap/docs. *Feature parity with today plus delayed
   start reached here.*
5. **Pages.** S8/S8a, S9 with choice Sheets, S10, S13.
6. **Context.** S7, S11 (+ QR), setup-mode hint on S2.

## Left to the builder

- Exact typography inside rows and sheets, as long as R2's sizes hold.
- Whether to add Montserrat 20 for list subtitles (≈ 25 KB flash). Not
  required; 24 px fits every layout above.
- The scroll column's ▲▼ page size (one row vs. one page).
- Whether `esp_lcd_touch_xpt2046` or the in-house driver wins (see pipeline).
- The auto-tune hysteresis default — take the web UI's.
- QR code on/off per flash budget.

## Calls I made (for review)

1. Dropping the switch with no fallback, as asked; J6 stays on the board.
2. Confirmations on Start, Stop, Skip, Cancel-scheduled and both auto-tune
   actions; none on Pause/Resume/Done/Clear.
3. Timeouts: 60 s Sheets, 120 s Pages, back to Home.
4. Bar grows 44 → 48 px and becomes the Page header; Home content shrinks to
   200 px to make room for a permanent action bar.
5. Elapsed/remaining collapse to single lines in the Active view.
6. A SCHEDULED Home state and the Segments page, neither of which the LCD
   has today.
7. Settings on the LCD limited to unit, lid mode, alarm, auto-tune,
   calibration, network, about.
8. Calibration auto-runs on first boot, verifies itself, and can be reset by
   a long touch during the splash (which stretches the splash while held).
9. `check_pinmap.py` learns a "routed, no driver" set rather than keeping
   dead Kconfig symbols.
10. A ≡ Menu button on the bar in every Home state, so History, Settings and
    Segments stay reachable mid-firing without a fourth action-bar slot.
11. No Skip while paused (the engine refuses it), and the Skip Sheet
    pre-checks the ramp-direction rule so it never confirms a no-op.
12. No times of day anywhere on the LCD until a timezone setting exists;
    countdowns and durations only.
13. A missing or dead touch controller degrades to a read-only dashboard
    rather than a calibration screen nothing can get past.
