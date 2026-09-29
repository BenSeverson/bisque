# Bench Smoke Test

A one-page checklist for the manual hardware test that should run on the
bench before tagging a release. Verifies the parts that automated tests
*cannot* exercise: real SSR clicking, real thermocouple reading,
end-to-end firing flow, and history persistence across reboot.

This is **not** a pottery firing. It peaks at ~50°C, takes 3–8 minutes
wall-clock for a typical empty bench kiln, and tests the controller —
not the kiln, the elements, or your clay. Don't fire pottery with this
profile.

CI already covers everything else:

- Layers 1 & 2 — pure-logic + accelerated firing scenarios (`unit-host`)
- Layer 3 — API JSON contract (`unit-host` + `lint-web`)
- Layer 4 — UI screenshot regression (`ui-screenshots`)
- Layer 5 — Web UI schemas, hooks, and mock-server parity (`lint-web`)

If a green PR ships, the only thing left to verify on the bench is that
the firmware actually talks to the hardware. That's what this
checklist is for.

## Rev B board prerequisites

Skip this section on a rev A board. These checks apply to the rev B.2 board,
which carries `REV B.2` in its silk nameplate. Each item below stops the board
dead, damages it, or leaves an SSR that nothing on the board can turn off.
None of them is a firmware bug.

- [ ] **The supply is 24 V.** J2 feeds F1 → D8 → Q8 (reverse polarity) →
      `VIN_P`, which supplies U11 (the XL1509-5.0 buck) **and both SSR
      terminals**. Meter the PSU *before* landing the wire. 5 V there browns
      the board out, and anything above ~33 V takes out the TVS and the fuse.
- [ ] **The SSRs' control inputs take 24 V.** J4/J9 pin 1 is the 24 V input
      itself, up to 26.4 V at the HDR-15-24's full +10 % trim. Check the
      SSR's *operating* input range, not only the rated one: an SSR-40DA-class
      input is 3–32 V and fine, but a 5 V-only input is destroyed.
- [ ] **Each SSR's `−` is on its own `OUT` terminal and nowhere else.**
      J4/J9 pin 1 (`24V`) is always live, and the board switches the
      *return*. An SSR whose `−` reaches ground by any other route is on, and
      neither firmware nor the hardware watchdog can turn it off. That
      includes the PSU `−`, J2 `-`, a negative bus shared between the two
      SSRs, or a lead touching the enclosure, which is bonded to board GND.
      `+` to `24V`, `−` to `OUT`, one pair per SSR.
- [ ] **`SJ2` ("WDT DEFEAT") is open.** The SSR stage is gated by the U10
      one-shot, which firmware retriggers on GPIO 36 at 5 Hz. Open is the
      supervised (correct) state — see "Bring-up: leave SJ2 open" in
      [`hardware/kicad/jlcpcb/README.md`](../hardware/kicad/jlcpcb/README.md).
- [ ] **`SJ1` ("AUX=5V") is open** if anything is landed on J10 pin 1.
      Bridging it with an external 24 V coil rail present puts 24 V on `+5V`.
- [ ] **The lid input is satisfied.** `IN1` (J11 pin 1) is pulled up, so an
      unwired terminal reads *lid open* and the kiln will not heat. Fit the
      lid switch, jumper J11 pin 1 to J11 pin 4 (GND), or build with
      `KILN_PIN_LID_SWITCH=-1`.
- [ ] **Nothing real is on J9 yet.** Firmware does not drive SSR2's GPIO
      (21) until zone 2 support lands
      ([#310](https://github.com/BenSeverson/bisque/issues/310)). Rev B.2
      no longer pins that line low on the board, so while the watchdog is
      live, channel 2 depends on the pin's reset state. Leave J9 empty, or
      fit only a dummy (below), until firmware parks GPIO 21 low or the
      "SSR2 stays off" check below has passed.

## First power-up on board 1 (once only)

The 24 V front end, the buck, the reverse-polarity FET (Q8) and the
USB/buck power mux (U12) have never been built. Work through this section
with **J4/J9/J10 empty** and a current-limited bench supply at 24 V, with the
limit set around 300 mA.

**Test points:** TP1 `+3V3`, TP2 `+5V`, TP3 GND, TP9 `SSR1_CTRL`,
TP10 `SSR2_CTRL`, TP12 the watchdog timing node. `BUCK_5V`, the buck's own
output ahead of the mux, is not `+5V`; probe it at C44.

### Power stage

- [ ] **Idle draw.** Once booted with the display lit, expect roughly
      50–150 mA at 24 V. A supply sitting in current limit with nothing
      connected means stop and look.
- [ ] **Rails:** TP2 (`+5V`) 4.9–5.1 V, TP1 (`+3V3`) 3.2–3.4 V, C44
      (`BUCK_5V`) the same as TP2 to within a few tens of mV.
- [ ] **Q8 is switched on, not conducting through its body diode.** J4
      pin 1 (`VIN_P`) reads within ~50 mV of J2's `+`. If it is ~0.6 V
      below, the gate is not being pulled: check R62, and D11's orientation
      (cathode to `VIN_P`).
- [ ] **Scope `BUCK_5V`** at C44 under load (Wi-Fi associated, backlight on).
      Expect < ~100 mV of ripple at 150 kHz and **no** low-frequency
      envelope. Subharmonic wobble at a few kHz means the buck's loop is
      marginal and C46, the bulk electrolytic, is doing less than intended.
- [ ] **Check U2, U11 and Q8 by hand** after 10 minutes at temperature.
      U2 is warm (it dissipates ~0.5 W). U11 is warm. Q8 should be barely
      above ambient; if it is hot, it is running on its body diode.
- [ ] *Optional, board 1 only:* **reverse the supply** with the current
      limit at ~100 mA. The supply should sit in current limit (D8 conducting
      forward), the board should stay dark, and nothing should warm. Restore
      the polarity, and the board boots.

### USB/buck source selection (U12)

- [ ] **USB-C alone, J2 disconnected.** The board boots and enumerates, TP2
      reads close to the port's VBUS, and **C44 (`BUCK_5V`) stays near 0 V**.
      This is the one U12 behaviour the design review could not check against
      the datasheet: with the buck absent, the mux must select USB. It also
      proves the buck is not being back-fed. If the board is dead on USB
      alone, check U12 before anything else.
- [ ] **Both connected: the buck wins.** With 24 V and USB both present,
      TP2 reads the buck's 5.0 V, not the port's (often 5.1–5.2 V).
      Unplugging USB should not move it.
- [ ] **Switchover.** With USB attached, switch the 24 V off, then on again.
      The board must **not reset**: check that uptime (Settings → System, or
      `GET /api/v1/system`) carried on. If you have a scope on TP2, `+5V`
      should bottom out no lower than ~3.7 V on the way to USB.
- [ ] Bring the display up at a reduced SPI clock first if it is unstable.
      SCLK is a multi-drop net with two thermocouple stubs and ~150 mm of
      loom before the panel.

### Output stage and watchdog (before a real kiln)

Use an SSR with nothing on its load side. Failing that, use a dummy for
each channel: a 4.7 kΩ ¼ W resistor in series with an LED, wired `24V` →
LED anode, cathode → resistor → `OUT`. Flash the release build first. Every
check here runs at **idle**: firmware kicks the watchdog whenever its
supervision loop is healthy, firing or not, so `SSR_EN` (the watchdog's
permission rail) is live without starting a profile.

- [ ] **`OUT` is not grounded.** With firmware idle, meter J4 pin 2 (and
      J9 pin 2) to GND. Expect close to 24 V, a few volts less with nothing
      connected. **Near 0 V means that SSR's `−` has found ground** and the
      SSR is on with nothing able to stop it. Fix the wiring before anything
      else.
- [ ] **Idle is dark.** LED3/LED4 (the amber `SSR1`/`SSR2` indicators) and
      the SSRs' own input LEDs are off. A lit indicator at idle means either
      `SJ2` is bridged or `OUT` is grounded. Both indicators sit across the
      terminal, so they report what the channel is actually doing.
- [ ] **Watchdog cutoff with the MCU dead.** Hold RESET (SW1) and, while
      holding it, connect TP9 (`SSR1_CTRL`) to TP1 (`+3V3`) through 1 kΩ.
      That lights channel 1's opto as if firmware had asked for heat, so the
      expired watchdog is the only thing holding the channel off. **The SSR
      and LED3 must stay off.** Remove the resistor before releasing RESET.
      The firing below is the positive control: the same channel does come on
      when the watchdog is live.
- [ ] **Watchdog window.** Scope TP12 and `SSR_EN`. `SSR_EN` is R18's
      non-ground pad, which reads ~5 V while firmware runs. Press and hold
      RESET. The time from TP12's last retrigger to `SSR_EN`
      falling should be **1.65–2.71 s**. Record the number; it is the one
      safety-path figure that is extrapolated rather than specified.
- [ ] **SSR2 stays off.** With `SSR_EN` live, R20's non-ground pad
      (`SSR2_GATE`) reads **below 0.3 V**, and LED4 and the J9 dummy stay
      dark. If the gate sits higher, GPIO 21's reset state is pulling
      channel 2 on, and a real SSR must not go on J9 until firmware parks
      that pin low.

## Pre-flight

- [ ] Flash the release build (`./build.sh && idf.py flash`).
- [ ] LCD boots, shows the idle dashboard.
- [ ] Thermocouple reads a sensible room temperature (15–30°C) — not 0,
      not 1000, no fault icon.
- [ ] SSR is wired and its input LED (or audible click) is observable from
      the bench. On rev B the board has **two** channels (J4 = zone 1,
      J9 = zone 2) with amber indicators LED3/LED4. The firmware drives
      zone 1 only, so LED4 staying dark is expected.
- [ ] The `SSR1` indicator (LED3) is **off** at idle. If it is lit before
      any firing starts, `SJ2` is bridged or J4's `OUT` is grounded (see
      above). Neither is something firmware can override.

## Load the smoke-test profile

Either import the JSON or type the values into the web UI.

The profile is in [`docs/smoke-test-profile.json`](smoke-test-profile.json):

| Segment | Ramp rate | Target | Hold |
|---------|-----------|--------|------|
| Heat    | 600 °C/hr | 50 °C  | 0 m  |
| Cool    | −300 °C/hr | 30 °C | 0 m  |

To import: web UI → Profiles → Import → upload the JSON, **or**:

```bash
curl -X POST http://<kiln-ip>/api/v1/profiles/import \
  -H 'Content-Type: application/json' \
  -d @docs/smoke-test-profile.json
```

## Run the firing

- [ ] Start the **Smoke Test** profile (web UI or LCD action menu).
- [ ] **SSR clicks on** within ~5 s of start (LED on / audible click).
- [ ] LCD dashboard shows `heating` status, temperature climbs.
- [ ] Temperature reaches ~50°C and the **status changes to `cooling`**
      (segment 1 → segment 2 advance).
- [ ] **SSR clicks off** during cooling — the dashboard should show the
      relay disengaged. Temperature drifts back down passively.
- [ ] When the kiln cools to ~30°C, status transitions to `complete`.
      (If your kiln cools slowly, this can take a while; the segment
      advance from `heating` → `cooling` is the more important check.
      Press the on-screen Stop button if you don't want to wait for
      the cool segment to finish naturally.)
- [ ] **BZ1 sounds on completion** — three ~500 ms beeps, 200 ms apart, at
      a clear steady volume. A weak or raspy buzz means the alarm pin is
      being chopped rather than held
      ([#342](https://github.com/BenSeverson/bisque/issues/342)).
- [ ] **No error events** during the run (no `error` status, no fault
      banner on the LCD).

## Verify persistence

- [ ] Open the History screen on the LCD or `GET /api/v1/history` — the
      smoke run is recorded with `outcome: "complete"` (or `aborted` if
      you pressed Stop), peak ~50°C, plausible duration.
- [ ] **Power-cycle the controller.** After it boots, the same history
      record is still present.

## Done

If every checkbox passed, the firmware is ready for a release tag.

If anything failed — SSR didn't click, thermocouple read wrong, segment
didn't advance, history vanished after reboot — open an issue with the
checkbox you stopped at and what you observed. Don't tag the release.
