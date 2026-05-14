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

## Pre-flight

- [ ] Flash the release build (`./build.sh && idf.py flash`).
- [ ] LCD boots, shows the idle dashboard.
- [ ] Thermocouple reads a sensible room temperature (15–30°C) — not 0,
      not 1000, no fault icon.
- [ ] SSR is wired and the relay's LED (or audible click) is observable
      from the bench.

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
