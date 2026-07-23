import { describe, it, expect } from "vitest";
import {
  firingSegmentSchema,
  profileFormSchema,
  firingProfileSchema,
  settingsSchema,
} from "./kiln";
import { HOLD_UNTIL_SKIP } from "../types/kiln";

const validSegment = {
  id: "seg-1",
  name: "Ramp",
  rampRate: 100,
  targetTemp: 500,
  holdTime: 0,
};

const validProfile = {
  id: "test-profile",
  name: "Test",
  description: "",
  segments: [validSegment],
  maxTemp: 500,
  estimatedDuration: 60,
};

const validSettings = {
  tempUnit: "C" as const,
  maxSafeTemp: 1300,
  alarmEnabled: true,
  autoShutdown: true,
  notificationsEnabled: true,
  tcOffsetC: 0,
  webhookUrl: "",
  apiTokenSet: false,
  elementWatts: 0,
  electricityCostKwh: 0,
};

describe("firingSegmentSchema", () => {
  it("accepts a valid segment", () => {
    expect(firingSegmentSchema.safeParse(validSegment).success).toBe(true);
  });

  it("rejects zero ramp rate", () => {
    const r = firingSegmentSchema.safeParse({ ...validSegment, rampRate: 0 });
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues.some((i) => i.message === "Ramp rate must be non-zero")).toBe(true);
    }
  });

  it("rejects empty name", () => {
    const r = firingSegmentSchema.safeParse({ ...validSegment, name: "" });
    expect(r.success).toBe(false);
  });

  it("rejects targetTemp out of (0, 1400]", () => {
    expect(firingSegmentSchema.safeParse({ ...validSegment, targetTemp: -1 }).success).toBe(false);
    expect(firingSegmentSchema.safeParse({ ...validSegment, targetTemp: 1401 }).success).toBe(
      false,
    );
  });

  it("rejects zero targetTemp (firmware requires target_temp > 0)", () => {
    expect(firingSegmentSchema.safeParse({ ...validSegment, targetTemp: 0 }).success).toBe(false);
  });

  it("rejects holdTime out of [0, HOLD_UNTIL_SKIP]", () => {
    expect(firingSegmentSchema.safeParse({ ...validSegment, holdTime: -1 }).success).toBe(false);
    expect(
      firingSegmentSchema.safeParse({ ...validSegment, holdTime: HOLD_UNTIL_SKIP + 1 }).success,
    ).toBe(false);
  });

  it("accepts HOLD_UNTIL_SKIP sentinel", () => {
    expect(
      firingSegmentSchema.safeParse({ ...validSegment, holdTime: HOLD_UNTIL_SKIP }).success,
    ).toBe(true);
  });

  it("rejects NaN / Infinity from valueAsNumber on empty inputs", () => {
    expect(firingSegmentSchema.safeParse({ ...validSegment, rampRate: NaN }).success).toBe(false);
    expect(firingSegmentSchema.safeParse({ ...validSegment, targetTemp: Infinity }).success).toBe(
      false,
    );
  });
});

describe("profileFormSchema", () => {
  it("accepts a valid profile form", () => {
    expect(
      profileFormSchema.safeParse({
        name: "Bisque",
        description: "",
        segments: [validSegment],
      }).success,
    ).toBe(true);
  });

  it("rejects empty profile name", () => {
    expect(
      profileFormSchema.safeParse({
        name: "",
        description: "",
        segments: [validSegment],
      }).success,
    ).toBe(false);
  });

  it("rejects empty segments array", () => {
    expect(
      profileFormSchema.safeParse({
        name: "Bisque",
        description: "",
        segments: [],
      }).success,
    ).toBe(false);
  });
});

describe("firingProfileSchema", () => {
  it("accepts a full profile", () => {
    expect(firingProfileSchema.safeParse(validProfile).success).toBe(true);
  });

  it("rejects empty id", () => {
    expect(firingProfileSchema.safeParse({ ...validProfile, id: "" }).success).toBe(false);
  });

  it("rejects missing required fields", () => {
    const { maxTemp: _maxTemp, ...withoutMax } = validProfile;
    void _maxTemp;
    expect(firingProfileSchema.safeParse(withoutMax).success).toBe(false);
  });
});

describe("settingsSchema", () => {
  it("accepts valid settings", () => {
    expect(settingsSchema.safeParse(validSettings).success).toBe(true);
  });

  it("rejects invalid tempUnit", () => {
    expect(settingsSchema.safeParse({ ...validSettings, tempUnit: "K" }).success).toBe(false);
  });

  it("rejects maxSafeTemp out of [0, 1400]", () => {
    expect(settingsSchema.safeParse({ ...validSettings, maxSafeTemp: -1 }).success).toBe(false);
    expect(settingsSchema.safeParse({ ...validSettings, maxSafeTemp: 1401 }).success).toBe(false);
  });

  it("rejects negative elementWatts and electricityCostKwh", () => {
    expect(settingsSchema.safeParse({ ...validSettings, elementWatts: -1 }).success).toBe(false);
    expect(settingsSchema.safeParse({ ...validSettings, electricityCostKwh: -0.01 }).success).toBe(
      false,
    );
  });

  it("treats apiToken / apiTokenSet as optional", () => {
    const { apiTokenSet: _s, ...minimal } = validSettings;
    void _s;
    expect(settingsSchema.safeParse(minimal).success).toBe(true);
  });

  it("accepts non-zero tcOffsetC (positive or negative)", () => {
    expect(settingsSchema.safeParse({ ...validSettings, tcOffsetC: -5.5 }).success).toBe(true);
    expect(settingsSchema.safeParse({ ...validSettings, tcOffsetC: 12.3 }).success).toBe(true);
  });
});
