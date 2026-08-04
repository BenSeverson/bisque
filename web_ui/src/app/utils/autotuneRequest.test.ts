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
});
