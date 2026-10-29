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
      itself, up to 29 V at the top of the HDR-15-24's trim range. Check the
      SSR's *operating* input range, not only the rated one: an SSR-40DA-class
      input is 3–32 V and fine, but a 5 V-only input is destroyed.
- [ ] **Each SSR is wired `+` to `OUT` (pin 1) and `−` to `GND` (pin 2).**
      Rev B.4 switches the + side and grounds the −, so a `−` lead that
      also reaches the PSU `−` or the enclosure is harmless; the B.2/B.3
      silk read `24V`/`OUT` with the same pin order. What must not happen
      is an `OUT` lead touching the earthed box: that shorts the channel
      to ground (the supply current-limits, the SSR stays off).
- [ ] **`SJ2` ("WDT DEFEAT") is open.** The SSR stage is gated by the U10
      one-shot, which firmware retriggers on `WDT_KICK` at 5 Hz. Open is the
      supervised (correct) state — see "Bring-up: leave SJ2 open" in
      [`hardware/kicad/jlcpcb/README.md`](../hardware/kicad/jlcpcb/README.md).
- [ ] **`SJ1` ("AUX=5V") is open** if anything is landed on J10 pin 1.
      Bridging it with an external 24 V coil rail present puts 24 V on `+5V`.
- [ ] **The lid input is satisfied.** `IN1` (J11 pin 1) is pulled up, so an
      unwired terminal reads *lid open* and the kiln will not heat. Fit the
      lid switch, jumper J11 pin 1 to J11 pin 4 (GND), or build with
      `KILN_PIN_LID_SWITCH=-1`.
- [ ] **Channel 2 is not driven by firmware yet.** Zone 2 support has not
      landed ([#310](https://github.com/BenSeverson/bisque/issues/310)), and
      rev B.2 no longer pins that line on the board. Firmware parks the SSR2
      pin low at boot instead; the boot log says "Parked zone 2 SSR
      control low on GPIO …". Confirm it with the "SSR2 stays off" check
      below before relying on J9.

## First power-up on board 1 (once only)

The 24 V front end, the buck, the reverse-polarity FET (Q8) and the
USB/buck power mux (U12) have never been built. Work through this section
with **J4/J9/J10 empty** and a current-limited bench supply at 24 V, with the
limit set around 300 mA.

**Test points:** TP3 GND, TP9 `SSR1_CTRL`, TP10 `SSR2_CTRL`, TP12 the
watchdog timing node. The rails have no test points: probe `+5V` at C2 (the
LDO's input cap) and `+3V3` at J7 pin 1 (the AUX header) or C4. `BUCK_5V`,
the buck's own output ahead of the mux, is not `+5V`; probe it at C44.

### Power stage

- [ ] **Idle draw.** Once booted with the display lit, expect roughly
      50–150 mA at 24 V. A supply sitting in current limit with nothing
      connected means stop and look.
- [ ] **Rails:** `+5V` (C2) 4.9–5.1 V, `+3V3` (J7 pin 1) 3.2–3.4 V, C44
      (`BUCK_5V`) the same as `+5V` to within a few tens of mV.
- [ ] **Q8 is switched on, not conducting through its body diode.** J4
      pin 1 (`VIN_P`) reads within ~50 mV of J2's `+`. If it is ~0.6 V
      below, the gate is not being pulled: check R62, and D11's orientation
      (cathode to `VIN_P`).
- [ ] **Scope `BUCK_5V`** at C44 under load (Wi-Fi associated, backlight on).
      Expect < ~100 mV of ripple at 150 kHz (the design figure is 36–41 mV pp)
      and **no** low-frequency envelope. Subharmonic wobble at a few kHz means
      the buck's loop is marginal and C46, the bulk electrolytic, is doing
      less than intended.
- [ ] **Buck loop qualification** (PCB review 2026-10-05 item 3 — the XL1509's
      compensation is undocumented, so this is the evidence, not the design
      notes). Probe `BUCK_5V` at C44 with a short ground spring, AC-coupled:
      - *Load step* 0.2 → 0.8 A and back (a resistive load on `+5V` switched by
        a FET, or a bench load in transient mode), 10 µs edges. Record the
        overshoot and the ring: ≤ 2 cycles of decaying ring, settled within
        ~200 µs, is a healthy phase margin; a ring that lasts > 5 cycles, or
        any sustained oscillation at 1–20 kHz, is the loop telling you C46 is
        not the part the sheet says — stop and read `DESIGN-NOTES.md` at C46.
      - *Startup* at 24 V into the idle board: monotonic rise, no overshoot
        past 5.5 V (the XL1509 has no soft-start; the 4 A current limit sets
        the slope).
      - *No load* (U2 unplugged is not possible — use the board's idle draw)
        and *full load* (1.0 A total on `+5V`, the rated ceiling): ripple and
        the step response at both.
      - *Hot*: repeat the load step after the enclosure soak below. U11's
        datasheet puts it at ~110 °C junction at 1.0 A and 50 °C ambient;
        a thermocouple on its body should read under 90 °C.
      Record all four in the board log with the firmware revision.
- [ ] **Check U2, U11 and Q8 by hand** after 10 minutes at temperature.
      U2 is warm (it dissipates ~0.5 W). U11 is warm. Q8 should be barely
      above ambient; if it is hot, it is running on its body diode.
- [ ] *Optional, board 1 only:* **reverse the supply** with the current
      limit at ~100 mA. The supply should sit in current limit (D8 conducting
      forward), the board should stay dark, and nothing should warm. Restore
      the polarity, and the board boots.

### USB/buck source selection (U12)

- [ ] **USB-C alone, J2 disconnected.** The board boots and enumerates, `+5V`
      (C2) reads close to the port's VBUS, and **C44 (`BUCK_5V`) stays near 0 V**.
      With the buck absent, MODE and PR1 are both at 0 V, and the TPS2116
      datasheet has the mux pass the higher input, which is USB. This check
      confirms that on hardware, and also proves the buck is not being
      back-fed. If the board is dead on USB alone, check U12 before anything
      else.
- [ ] **Both connected: the buck wins.** With 24 V and USB both present,
      `+5V` reads the buck's 5.0 V, not the port's (often 5.1–5.2 V).
      Unplugging USB should not move it.
- [ ] **Switchover.** With USB attached, switch the 24 V off, then on again.
      The board must **not reset**: check that uptime (Settings → System, or
      `GET /api/v1/system`) carried on. If you have a scope on `+5V` (C2), it
      should bottom out no lower than ~3.7 V **in both directions**; the
      return of 24 V dips it too, by design. If you can spare a second
      channel, probe VBUS at C47 while the 24 V comes back: C47/C48 are U12's
      input caps, and VBUS should not overshoot 6 V. On a board built before
      they were added (fab review A6), treat any overshoot as a stop.
- [ ] Bring the display up at a reduced SPI clock first if it is unstable.
      SCLK is a multi-drop net with two thermocouple stubs and ~150 mm of
      loom before the panel.

### Output stage and watchdog (before a real kiln)

Use an SSR with nothing on its load side. Failing that, use a dummy for
each channel: a 4.7 kΩ ¼ W resistor in series with an LED, wired `OUT` →
LED anode, cathode → resistor → `GND`. Flash the release build first. Every
check here runs at **idle**: firmware kicks the watchdog whenever its
supervision loop is healthy, firing or not, so `SSR_EN` (the watchdog's
permission rail) is live without starting a profile.

- [ ] **`OUT` is dead at idle.** With firmware idle, meter J4 pin 1 (and
      J9 pin 1) to GND. Expect near 0 V. **Near 24 V means that channel's
      switch (Q5/Q6) or the cutoff Q9 has failed short, or `SJ2` is
      bridged** — fix before anything else. `SSR_24V` (Q9's drain) should
      read ~24 V while firmware kicks and collapse within ~3 s when it stops.
- [ ] **Idle is dark.** LED3/LED4 (the amber `SSR1`/`SSR2` indicators) and
      the SSRs' own input LEDs are off. A lit indicator at idle means either
      `SJ2` is bridged or a switch has failed short. Both indicators sit
      across the terminal, so they report what the channel is actually doing.
- [ ] **Watchdog cutoff with the MCU dead.** Hold RESET (SW1) and, while
      holding it, connect TP9 (`SSR1_CTRL`) to `+3V3` (J7 pin 1) through 1 kΩ.
      That lights channel 1's opto as if firmware had asked for heat, so the
      expired watchdog is the only thing holding the channel off. **The SSR
      and LED3 must stay off.** Remove the resistor before releasing RESET.
      The firing below is the positive control: the same channel does come on
      when the watchdog is live.
- [ ] **Watchdog window.** Scope TP12 and `SSR_EN`. `SSR_EN` is R18's
      non-ground pad, which reads ~5 V while firmware runs. Press and hold
      RESET. The time from TP12's last retrigger to `SSR_EN`
      falling should be **1.3–3.1 s** (2.0–2.2 s nominal). Record the
      number; it is the one safety-path figure that is extrapolated rather
      than specified.
- [ ] **SSR2 stays off.** With `SSR_EN` live, R20's non-ground pad
      (`SSR2_GATE`) reads **below 0.3 V**, and LED4 and the J9 dummy stay
      dark. If the gate sits higher, something is lifting `SSR2_CTRL` despite
      firmware parking it low: disconnect J9 and report it.

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
      any firing starts, `SJ2` is bridged or a channel switch has failed
      short (see above). Neither is something firmware can override.

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
