import { describe, it, expect } from "vitest";
import {
  toDisplayTemp,
  fromDisplayTemp,
  toDisplayRate,
  fromDisplayRate,
  unitLabel,
  rateLabel,
  formatTemp,
  formatRate,
} from "./temperature";

describe("absolute temperature conversion", () => {
  it("is identity for Celsius", () => {
    expect(toDisplayTemp(600, "C")).toBe(600);
    expect(fromDisplayTemp(600, "C")).toBe(600);
  });

  it("applies the affine conversion for Fahrenheit", () => {
    expect(toDisplayTemp(0, "F")).toBe(32);
    expect(toDisplayTemp(100, "F")).toBe(212);
    expect(toDisplayTemp(600, "F")).toBe(1112);
  });

  it("round-trips C → F → C exactly for representative values", () => {
    for (const c of [0, 20, 600, 1000, 1280]) {
      expect(fromDisplayTemp(toDisplayTemp(c, "F"), "F")).toBeCloseTo(c, 9);
    }
  });
});

describe("delta/rate conversion", () => {
  it("scales without the +32 offset", () => {
    expect(toDisplayRate(100, "F")).toBe(180);
    expect(toDisplayRate(-150, "F")).toBe(-270);
    expect(toDisplayRate(100, "C")).toBe(100);
  });

  it("round-trips and differs from absolute conversion", () => {
    expect(fromDisplayRate(toDisplayRate(80, "F"), "F")).toBeCloseTo(80, 9);
    // A 0°C delta is 0°F, not 32°F.
    expect(toDisplayRate(0, "F")).toBe(0);
  });
});

describe("labels and formatting", () => {
  it("returns unit suffixes", () => {
    expect(unitLabel("C")).toBe("°C");
    expect(unitLabel("F")).toBe("°F");
    expect(rateLabel("C")).toBe("°C/hr");
    expect(rateLabel("F")).toBe("°F/hr");
  });

  it("formats absolute temps rounded with suffix", () => {
    expect(formatTemp(600, "C")).toBe("600°C");
    expect(formatTemp(600, "F")).toBe("1112°F");
    expect(formatTemp(20.4, "C")).toBe("20°C");
  });

  it("formats rates rounded with suffix", () => {
    expect(formatRate(100, "C")).toBe("100°C/hr");
    expect(formatRate(100, "F")).toBe("180°F/hr");
    expect(formatRate(-150, "F")).toBe("-270°F/hr");
  });
});
