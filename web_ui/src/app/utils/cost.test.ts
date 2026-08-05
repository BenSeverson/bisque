import { describe, it, expect } from "vitest";
import {
  ASSUMED_DUTY_CYCLE,
  costPerHourAtFullPower,
  estimateFiringCost,
  estimateProfileCost,
  formatCost,
  heatingMinutes,
} from "./cost";
import { HOLD_UNTIL_SKIP } from "../types/kiln";

const SETTINGS = { elementWatts: 5000, electricityCostKwh: 0.2 };

/** 20 -> 1020 at 500 C/hr is exactly two hours of ramp. */
const twoHourRamp = { targetTemp: 1020, rampRate: 500, holdTime: 0 };

describe("heatingMinutes", () => {
  it("counts ramp time from room temperature", () => {
    expect(heatingMinutes([twoHourRamp])).toBeCloseTo(120);
  });

  it("counts hold time", () => {
    expect(heatingMinutes([{ ...twoHourRamp, holdTime: 30 }])).toBeCloseTo(150);
  });

  it("ignores a controlled cooling segment's ramp but keeps its hold", () => {
    // The crystalline shape: up, then a programmed cool with a soak at the
    // bottom of it. The element is off on the way down but on during the soak.
    const segments = [twoHourRamp, { targetTemp: 520, rampRate: -250, holdTime: 60 }];
    expect(heatingMinutes(segments)).toBeCloseTo(180);
  });

  it("treats an indefinite hold as contributing nothing", () => {
    // Same choice estimatedDuration makes — HOLD_UNTIL_SKIP is a sentinel, and
    // summing it verbatim would price the firing at tens of thousands of hours.
    expect(heatingMinutes([{ ...twoHourRamp, holdTime: HOLD_UNTIL_SKIP }])).toBeCloseTo(120);
  });

  it("counts a re-heat after a cool", () => {
    const segments = [
      twoHourRamp,
      { targetTemp: 520, rampRate: -250, holdTime: 0 },
      // 520 -> 1020 at 500 C/hr is another hour of real heating.
      { targetTemp: 1020, rampRate: 500, holdTime: 0 },
    ];
    expect(heatingMinutes(segments)).toBeCloseTo(180);
  });

  it("ignores an opening cooling segment written for an already-hot kiln", () => {
    // 1000 -> 800 is a cool, but against the assumed 20 C start its target still
    // looks like a climb. Only the negative rate says otherwise, so reading the
    // target alone billed the one segment that most needed excluding.
    expect(heatingMinutes([{ targetTemp: 800, rampRate: -200, holdTime: 0 }])).toBeCloseTo(0);
  });

  it("still counts that segment's hold", () => {
    expect(heatingMinutes([{ targetTemp: 800, rampRate: -200, holdTime: 45 }])).toBeCloseTo(45);
  });
});

describe("estimateProfileCost", () => {
  /** All 120 minutes of it are heating. */
  const allHeating = { segments: [twoHourRamp], estimatedDuration: 120 };

  it("multiplies duration, power, duty and rate", () => {
    // 5 kW * 2 h * 50% * $0.20 = $1.00
    expect(estimateProfileCost(allHeating, SETTINGS)).toBeCloseTo(2 * 5 * ASSUMED_DUTY_CYCLE * 0.2);
  });

  it("bills only the heating share of a profile with a programmed cool", () => {
    const withCool = {
      segments: [twoHourRamp, { targetTemp: 20, rampRate: -500, holdTime: 0 }],
      estimatedDuration: 240,
    };
    expect(estimateProfileCost(withCool, SETTINGS)).toBeCloseTo(
      estimateProfileCost(allHeating, SETTINGS)!,
    );
  });

  it("prices off the stored duration, not the raw segment arithmetic", () => {
    // The bundled profiles store hand-authored round durations that their own
    // segments disagree with. The card prints the stored one, so the cost has to
    // be reconcilable with it rather than with a number shown nowhere.
    const understated = { segments: [twoHourRamp], estimatedDuration: 60 };
    expect(estimateProfileCost(understated, SETTINGS)).toBeCloseTo(
      1 * 5 * ASSUMED_DUTY_CYCLE * 0.2,
    );
  });

  it("returns null when the element power is unconfigured", () => {
    // Not $0.00 — an unconfigured kiln must show nothing rather than claim a
    // firing is free.
    expect(estimateProfileCost(allHeating, { ...SETTINGS, elementWatts: 0 })).toBeNull();
  });

  it("returns null when the electricity rate is unconfigured", () => {
    expect(estimateProfileCost(allHeating, { ...SETTINGS, electricityCostKwh: 0 })).toBeNull();
  });

  it("returns null for a profile with no duration yet", () => {
    // The builder's empty state, before any segment has been added.
    expect(estimateProfileCost({ segments: [], estimatedDuration: 0 }, SETTINGS)).toBeNull();
  });

  it("returns null for a profile that only cools", () => {
    expect(
      estimateProfileCost(
        { segments: [{ targetTemp: 10, rampRate: -100, holdTime: 0 }], estimatedDuration: 60 },
        SETTINGS,
      ),
    ).toBeNull();
  });
});

describe("estimateFiringCost", () => {
  const profile = { segments: [twoHourRamp], estimatedDuration: 120 };

  it("agrees with the profile estimate for a firing that ran to plan", () => {
    expect(estimateFiringCost(120 * 60, profile, SETTINGS)).toBeCloseTo(
      estimateProfileCost(profile, SETTINGS)!,
    );
  });

  it("scales by the profile's heating fraction so a programmed cool is not billed", () => {
    // Half the wall-clock duration is a cool, so the same 4-hour firing costs
    // what its two heating hours cost.
    const withCool = {
      segments: [twoHourRamp, { targetTemp: 20, rampRate: -500, holdTime: 0 }],
      estimatedDuration: 240,
    };
    expect(estimateFiringCost(240 * 60, withCool, SETTINGS)).toBeCloseTo(
      estimateProfileCost(profile, SETTINGS)!,
    );
  });

  it("prices a firing that stopped early below one that ran to completion", () => {
    const short = estimateFiringCost(60 * 60, profile, SETTINGS)!;
    expect(short).toBeCloseTo(estimateFiringCost(120 * 60, profile, SETTINGS)! / 2);
  });

  it("bills an abort during the heat at full rate, not the profile-wide average", () => {
    // Two hours of heat then two hours of programmed cool. An abort an hour in
    // never reached the cool, so all of it was heating — discounting it by the
    // profile's 50% heating share would charge for half an hour of element time
    // that the kiln spent at full tilt.
    const heatThenCool = {
      segments: [twoHourRamp, { targetTemp: 20, rampRate: -500, holdTime: 0 }],
      estimatedDuration: 240,
    };
    expect(estimateFiringCost(60 * 60, heatThenCool, SETTINGS)).toBeCloseTo(
      1 * 5 * ASSUMED_DUTY_CYCLE * 0.2,
    );
  });

  it("stops charging once the firing reaches the cool", () => {
    // Three hours in: two of heat, one of cool. Only the heat is billed, so this
    // costs the same as the two-hour abort above.
    const heatThenCool = {
      segments: [twoHourRamp, { targetTemp: 20, rampRate: -500, holdTime: 0 }],
      estimatedDuration: 240,
    };
    expect(estimateFiringCost(180 * 60, heatThenCool, SETTINGS)).toBeCloseTo(
      estimateFiringCost(120 * 60, heatThenCool, SETTINGS)!,
    );
  });

  it("never charges for more hours than the firing actually ran", () => {
    // A kiln that fell behind schedule reports a duration past its estimate; the
    // heating tally must not exceed the wall clock.
    const cost = estimateFiringCost(30 * 60, profile, SETTINGS)!;
    expect(cost).toBeCloseTo(0.5 * 5 * ASSUMED_DUTY_CYCLE * 0.2);
  });

  it("falls back to the whole duration when the profile is gone", () => {
    expect(estimateFiringCost(120 * 60, undefined, SETTINGS)).toBeCloseTo(
      2 * 5 * ASSUMED_DUTY_CYCLE * 0.2,
    );
  });

  it("returns null for a zero-length record", () => {
    expect(estimateFiringCost(0, profile, SETTINGS)).toBeNull();
  });
});

describe("costPerHourAtFullPower", () => {
  it("is power times rate, with no duty assumption", () => {
    expect(costPerHourAtFullPower(SETTINGS)).toBeCloseTo(1.0);
  });

  it("returns null when unconfigured", () => {
    expect(costPerHourAtFullPower({ elementWatts: 0, electricityCostKwh: 0.2 })).toBeNull();
    expect(costPerHourAtFullPower({ elementWatts: 5000, electricityCostKwh: 0 })).toBeNull();
  });

  it("returns null when a blank number input yields NaN", () => {
    // `valueAsNumber: true` on an emptied field gives NaN, which every
    // comparison fails — the guards must reject it rather than render "$NaN".
    expect(costPerHourAtFullPower({ elementWatts: NaN, electricityCostKwh: 0.2 })).toBeNull();
    expect(costPerHourAtFullPower({ elementWatts: 5000, electricityCostKwh: NaN })).toBeNull();
  });
});

describe("formatCost", () => {
  it("formats to cents", () => {
    expect(formatCost(4.2)).toBe("$4.20");
    expect(formatCost(0.005)).toBe("$0.01");
  });
});
