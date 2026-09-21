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

Skip this section on a rev A board. On **rev B** these four things each stop
the board dead or damage it, and none of them is a firmware bug:

- [ ] **The supply is 24 V.** J2 feeds F1 → D8 → D1 → U11 (an XL1509-5.0
      buck). Meter the PSU *before* landing the wire: 5 V there browns the
      board out, and anything above ~33 V takes out the TVS and the fuse.
- [ ] **`SJ2` ("WDT DEFEAT") is open.** The SSR rail is gated by the U10
      one-shot, which firmware retriggers on GPIO 36 at 5 Hz. Open is the
      supervised (correct) state — see "Bring-up: leave SJ2 open" in
      [`hardware/kicad/jlcpcb/README.md`](../hardware/kicad/jlcpcb/README.md).
- [ ] **`SJ1` ("AUX=5V") is open** if anything is landed on J10 pin 1.
      Bridging it with an external 24 V coil rail present puts 24 V on `+5V`.
- [ ] **The lid input is satisfied.** `IN1` (J11 pin 1) is pulled up, so an
      unwired terminal reads *lid open* and the kiln will not heat. Fit the
      lid switch, jumper J11 pin 1 to J11 pin 4 (GND), or build with
      `KILN_PIN_LID_SWITCH=-1`.

## First power-up on board 1 (once only)

The 24 V front end and the on-board 5 V buck are new in rev B and have never
been built. Before running a profile through them:

- [ ] **Scope `+5V`** at C44 under load (Wi-Fi associated, backlight on).
      Expect < ~100 mV of ripple at 150 kHz and **no** low-frequency
      envelope — subharmonic wobble at a few kHz means the buck's loop is
      marginal and C46, the bulk electrolytic, is doing less than intended.
- [ ] **Check U2 and U11 by hand** after 10 minutes at temperature. Warm is
      expected (U2 dissipates ~0.5 W); too hot to hold is not.
- [ ] **Power from USB-C alone, with J2 disconnected.** The board runs off
      VBUS through D2 for flashing, which back-feeds U11's output. Confirm
      U11 stays cool and the board enumerates.
- [ ] Bring the display up at a reduced SPI clock first if it is unstable —
      SCLK is a multi-drop net with two thermocouple stubs and ~150 mm of
      loom before the panel.

## Pre-flight

- [ ] Flash the release build (`./build.sh && idf.py flash`).
- [ ] LCD boots, shows the idle dashboard.
- [ ] Thermocouple reads a sensible room temperature (15–30°C) — not 0,
      not 1000, no fault icon.
- [ ] SSR is wired and the relay's LED (or audible click) is observable
      from the bench. On rev B the board has **two** channels (J4 = zone 1,
      J9 = zone 2) with amber indicators LED3/LED4; the firmware drives
      zone 1 only, so LED4 staying dark is expected.
- [ ] The `SSR1 ON` indicator is **off** at idle. If it is lit before any
      firing starts, the watchdog gate is defeated — check `SJ2`.

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
