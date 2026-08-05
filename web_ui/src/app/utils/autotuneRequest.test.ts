import { describe, it, expect } from "vitest";
import { prepareAutotuneRequest, AUTOTUNE_DEFAULT_HYSTERESIS_C } from "./autotuneRequest";

describe("prepareAutotuneRequest", () => {
  it("accepts a normal tune", () => {
    expect(prepareAutotuneRequest(500, AUTOTUNE_DEFAULT_HYSTERESIS_C)).toEqual({
      ok: true,
      setpoint: 500,
      hysteresis: 5,
    });
  });

  it("rejects a non-positive or empty setpoint", () => {
    // parseFloat("") is NaN — the state the setpoint field is in mid-edit.
    expect(prepareAutotuneRequest(NaN, 5)).toMatchObject({ ok: false });
    expect(prepareAutotuneRequest(0, 5)).toMatchObject({ ok: false });
    expect(prepareAutotuneRequest(-10, 5)).toMatchObject({ ok: false });
  });

  it("rejects a non-positive or empty relay band", () => {
    expect(prepareAutotuneRequest(500, NaN)).toMatchObject({ ok: false });
    expect(prepareAutotuneRequest(500, 0)).toMatchObject({ ok: false });
    expect(prepareAutotuneRequest(500, -5)).toMatchObject({ ok: false });
  });

  it("rejects a band wide enough to keep the element off for the whole run", () => {
    // The firmware validates the two fields independently and accepts this, then
    // sits at 0% output until the 60-minute timeout fails the tune: with
    // setpoint - hysteresis <= 0 no reading ever satisfies the relay's turn-on
    // condition in pid_autotune_update().
    expect(prepareAutotuneRequest(500, 500)).toMatchObject({ ok: false });
    expect(prepareAutotuneRequest(500, 800)).toMatchObject({ ok: false });
    // Just inside the bound is still the user's call to make.
    expect(prepareAutotuneRequest(500, 499)).toMatchObject({ ok: true });
  });

  describe("against the max safe temperature", () => {
    // A tune drives the kiln to setpoint + hysteresis, so the firmware's
    // `setpoint > max_temp` check leaves the band free to overshoot the trip.
    it("rejects a band that would overshoot the safety trip", () => {
      const r = prepareAutotuneRequest(1300, 200, { maxSafeTemp: 1400 });
      expect(r).toMatchObject({ ok: false });
      expect(r.ok === false && r.message).toContain("1500°C");
    });

    it("accepts a band that stays under the trip", () => {
      expect(prepareAutotuneRequest(1300, 50, { maxSafeTemp: 1400 })).toMatchObject({ ok: true });
      // Exactly at the limit is allowed — the trip is `>`, not `>=`.
      expect(prepareAutotuneRequest(1300, 100, { maxSafeTemp: 1400 })).toMatchObject({ ok: true });
    });

    it("skips the check when the limit has not arrived", () => {
      expect(prepareAutotuneRequest(1300, 200)).toMatchObject({ ok: true });
    });
  });

  describe("against the current temperature", () => {
    it("rejects a turn-on threshold the kiln is already above", () => {
      // setpoint 50 / band 40 puts the turn-on threshold at 10°C. An idle kiln at
      // 20°C leaves pid_autotune_update()'s heat-up phase immediately, enters
      // cycling with the element off, and will not switch it on until the reading
      // drops below 10°C — which ambient cooling cannot do. Times out at 60 min.
      const r = prepareAutotuneRequest(50, 40, { currentTemp: 20 });
      expect(r).toMatchObject({ ok: false });
      expect(r.ok === false && r.message).toContain("20°C");
    });

    it("accepts a threshold the kiln still has to heat up to", () => {
      expect(prepareAutotuneRequest(500, 5, { currentTemp: 20 })).toMatchObject({ ok: true });
      // One degree of heat-up is enough to reach the threshold properly.
      expect(prepareAutotuneRequest(500, 479, { currentTemp: 20 })).toMatchObject({ ok: true });
    });

    it("allows a tune that starts above the setpoint", () => {
      // Not the stall case: above_setpoint is set correctly, so the kiln cools
      // through the setpoint, records the crossing, then drops past the turn-on
      // threshold and cycles normally. Tuning on the way down is legitimate.
      expect(prepareAutotuneRequest(500, 5, { currentTemp: 600 })).toMatchObject({ ok: true });
      expect(prepareAutotuneRequest(500, 5, { currentTemp: 500 })).toMatchObject({ ok: true });
    });

    it("skips the check when no status frame has arrived", () => {
      // The store seeds currentTemp to a synthetic 20°C; validating against it
      // would reject a legitimate low-setpoint tune on a cold page load.
      expect(prepareAutotuneRequest(50, 40)).toMatchObject({ ok: true });
    });
  });

  it("reports temperatures in the caller's display unit", () => {
    const r = prepareAutotuneRequest(1300, 200, {
      maxSafeTemp: 1400,
      formatTemp: (c) => `${Math.round(c * (9 / 5) + 32)}°F`,
    });
    expect(r.ok === false && r.message).toContain("2732°F");
  });
});
