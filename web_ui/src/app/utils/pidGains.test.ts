import { describe, it, expect } from "vitest";
import { preparePidGains, formatGain } from "./pidGains";

const LIMITS = { min: 0, max: 10000 };

describe("preparePidGains", () => {
  it("accepts a hand-entered set from another controller", () => {
    const r = preparePidGains({ kp: "18", ki: "0.12", kd: "240" }, LIMITS);
    expect(r).toEqual({ ok: true, gains: { kp: 18, ki: 0.12, kd: 240 } });
  });

  it("names the empty field instead of submitting it as zero", () => {
    // Number("") is 0, so an unfilled Kd would otherwise reach the controller
    // as a deliberate zero.
    const r = preparePidGains({ kp: "2", ki: "0.01", kd: "  " }, LIMITS);
    expect(r).toEqual({ ok: false, message: "Kd is required" });
  });

  it("rejects non-numeric input", () => {
    const r = preparePidGains({ kp: "two", ki: "0.01", kd: "5" }, LIMITS);
    expect(r.ok).toBe(false);
  });

  it("rejects negative gains", () => {
    expect(preparePidGains({ kp: "-2", ki: "0.01", kd: "5" }, LIMITS)).toMatchObject({
      ok: false,
      message: "Kp cannot be negative",
    });
  });

  it("rejects the derivative-only controller the firmware refuses", () => {
    const r = preparePidGains({ kp: "0", ki: "0", kd: "5" }, LIMITS);
    expect(r).toMatchObject({ ok: false });
    if (!r.ok) expect(r.message).toMatch(/never reach temperature/);
  });

  it("accepts Kp or Ki alone", () => {
    expect(preparePidGains({ kp: "2", ki: "0", kd: "0" }, LIMITS).ok).toBe(true);
    expect(preparePidGains({ kp: "0", ki: "0.01", kd: "0" }, LIMITS).ok).toBe(true);
  });

  it("enforces the range the firmware served, quoting it in the message", () => {
    const r = preparePidGains({ kp: "2", ki: "0.01", kd: "20000" }, LIMITS);
    expect(r).toEqual({ ok: false, message: "Kd must be between 0 and 10000" });
  });

  it("uses the served limits rather than a hardcoded pair", () => {
    // A firmware that publishes a tighter ceiling must tighten the form with it.
    const r = preparePidGains({ kp: "500", ki: "0.01", kd: "5" }, { min: 0, max: 100 });
    expect(r).toEqual({ ok: false, message: "Kp must be between 0 and 100" });
  });

  it("still applies the shape rules before limits have arrived", () => {
    expect(preparePidGains({ kp: "2", ki: "0.01", kd: "5" }).ok).toBe(true);
    expect(preparePidGains({ kp: "0", ki: "0", kd: "5" }).ok).toBe(false);
  });
});

describe("formatGain", () => {
  it("keeps the four decimals NVS can hold and trims the rest", () => {
    expect(formatGain(240)).toBe("240");
    expect(formatGain(0.01)).toBe("0.01");
    expect(formatGain(1.23456)).toBe("1.2346");
  });

  it("renders a missing reading rather than NaN", () => {
    expect(formatGain(NaN)).toBe("--");
  });
});
