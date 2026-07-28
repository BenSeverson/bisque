import { describe, it, expect } from "vitest";
import { describeFiringChart, describeTraceChart } from "./chartAria";

describe("describeFiringChart", () => {
  const points = [{ temp: 20 }, { temp: 300 }, { temp: 250 }];

  it("reports the count, the latest reading and the peak", () => {
    const label = describeFiringChart({ points, hasPlanned: true, unit: "C" });
    expect(label).toContain("3 readings");
    expect(label).toContain("currently 250°C");
    // The peak is not the last point — a chart that has come back down should
    // still announce how hot it actually got.
    expect(label).toContain("peak 300°C");
  });

  it("converts to the display unit exactly once", () => {
    // buildChartData already converts, so this helper takes raw Celsius.
    // Passing pre-converted values here would read as 572°F for 300°C.
    const label = describeFiringChart({ points, hasPlanned: true, unit: "F" });
    expect(label).toContain("572°F");
    expect(label).not.toContain("1062");
  });

  it("mentions the planned profile only when one is selected", () => {
    expect(describeFiringChart({ points, hasPlanned: true, unit: "C" })).toContain("planned");
    expect(describeFiringChart({ points, hasPlanned: false, unit: "C" })).not.toContain("planned");
  });

  it("says the chart is empty rather than announcing a peak of -Infinity", () => {
    // Math.max() of an empty array is -Infinity; an unguarded label would
    // announce "peak -Infinity°C" on every idle dashboard.
    const empty = describeFiringChart({ points: [], hasPlanned: false, unit: "C" });
    expect(empty).not.toContain("Infinity");
    expect(empty).toMatch(/no data/i);
    expect(describeFiringChart({ points: [], hasPlanned: true, unit: "C" })).toMatch(
      /no temperatures recorded/i,
    );
  });

  it("does not pluralise a single reading", () => {
    expect(describeFiringChart({ points: [{ temp: 20 }], hasPlanned: false, unit: "C" })).toContain(
      "1 reading,",
    );
  });
});

describe("describeTraceChart", () => {
  const points = [
    { time_s: 0, temp_c: 20 },
    { time_s: 1800, temp_c: 600 },
    { time_s: 3600, temp_c: 400 },
  ];

  it("names the profile and summarises duration and peak", () => {
    const label = describeTraceChart({ points, profileName: "Bisque", unit: "C" });
    expect(label).toContain("Bisque");
    expect(label).toContain("3 readings");
    expect(label).toContain("60 minutes");
    expect(label).toContain("peak 600°C");
  });

  it("handles a record whose trace was never stored", () => {
    const label = describeTraceChart({ points: [], profileName: "Bisque", unit: "C" });
    expect(label).not.toContain("Infinity");
    expect(label).toMatch(/no trace data/i);
  });
});
