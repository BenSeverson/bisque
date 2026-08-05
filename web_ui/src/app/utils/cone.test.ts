import { describe, it, expect } from "vitest";
import { coneEquivalent, coneEquivalentLabel } from "./cone";
import { mockProfiles } from "../data/mockProfiles";
// The mock's copy of the Orton table is contract-tested against the C
// serializer (test/contracts/firmwareContract.test.ts), so asserting against it
// is asserting against the temperatures the device actually reports.
import { CONE_TABLE } from "../../../mock-server/router";

const profileNamed = (name: string) => {
  const profile = mockProfiles.find((p) => p.name === name);
  if (!profile) throw new Error(`no built-in profile named ${name}`);
  return profile;
};

const label = (maxTemp: number, segments: { targetTemp: number; rampRate: number }[]) =>
  coneEquivalentLabel(maxTemp, segments, CONE_TABLE);

describe("coneEquivalentLabel", () => {
  // The built-in profiles name the cone they fire to, so a lookup that
  // disagrees with the name is wrong by construction.
  it.each([
    ["Bisque Cone 04", "≈ Cone 04"],
    ["Glaze Cone 6", "≈ Cone 6"],
    ["Glaze Cone 10", "≈ Cone 10"],
    ["Low Fire Cone 06", "≈ Cone 06"],
  ])("labels %s as %s", (name, expected) => {
    const profile = profileNamed(name);
    expect(label(profile.maxTemp, profile.segments)).toBe(expected);
  });

  it("reads the peak segment's ramp, not a later cooling one", () => {
    // Crystalline peaks at 1260°C on a +200°C/hr ramp and then cools at -200.
    const profile = profileNamed("Crystalline Glaze");
    expect(label(profile.maxTemp, profile.segments)).toBe("≈ Cone 8");
  });

  // Every profile the Cone Fire Wizard generates must round-trip back to the
  // cone it was generated for, at every speed — the wizard's final segment
  // ramps at exactly the rate behind the column it took its target from.
  it.each([
    ["slowTempC", 60],
    ["mediumTempC", 150],
    ["fastTempC", 300],
  ] as const)("round-trips wizard profiles built from the %s column", (column, rampRate) => {
    for (const cone of CONE_TABLE) {
      const targetTemp = cone[column];
      const segments = [
        { targetTemp: 600, rampRate: 100 },
        { targetTemp, rampRate },
      ];
      expect(label(targetTemp, segments)).toBe(`≈ Cone ${cone.name}`);
    }
  });

  it("stays on the standard column for a merely gentle ramp", () => {
    // 80°C/hr is nowhere near the table's 60°C/hr column, and published cone
    // temperatures are the standard column's — so 1222°C is cone 6, not the
    // cone 7 the slow column would name.
    expect(label(1222, [{ targetTemp: 1222, rampRate: 80 }])).toBe("≈ Cone 6");
  });

  it("switches to the slow column for a slow-column ramp", () => {
    // Same profile 21°C cooler and crawling at the slow column's own rate: that
    // is cone 6 slow-fired, not the cone 5 the standard column would name.
    expect(label(1201, [{ targetTemp: 1201, rampRate: 60 }])).toBe("≈ Cone 6");
    expect(label(1201, [{ targetTemp: 1201, rampRate: 150 }])).toBe("≈ Cone 5");
  });

  it("is silent when the peak is nowhere near a cone", () => {
    expect(label(300, [{ targetTemp: 300, rampRate: 100 }])).toBeNull();
    expect(label(1500, [{ targetTemp: 1500, rampRate: 100 }])).toBeNull();
  });

  it("still labels a peak just past the end of the table", () => {
    // Cone 14 is the hottest row (1395°C standard); overshooting it slightly is
    // still that cone, overshooting it wildly is not.
    expect(label(1415, [{ targetTemp: 1415, rampRate: 150 }])).toBe("≈ Cone 14");
    expect(label(1425, [{ targetTemp: 1425, rampRate: 150 }])).toBeNull();
  });

  it("is silent for an empty profile", () => {
    expect(label(0, [])).toBeNull();
  });

  it("is silent when the cone table has not loaded", () => {
    // useConeTable() defaults to [] while fetching and after a failed fetch.
    expect(coneEquivalentLabel(1222, [{ targetTemp: 1222, rampRate: 150 }], [])).toBeNull();
  });
});

describe("coneEquivalent", () => {
  it("returns the matching table entry", () => {
    expect(coneEquivalent(1222, [{ targetTemp: 1222, rampRate: 150 }], CONE_TABLE)).toMatchObject({
      name: "6",
      mediumTempC: 1222,
    });
  });
});
