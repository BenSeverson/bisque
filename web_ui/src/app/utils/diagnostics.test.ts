import { describe, it, expect } from "vitest";
import {
  buildDiagnosticsBundle,
  redactSettings,
  REDACTED,
  diagnosticsFilename,
  hasAnySection,
  serializeDiagnosticsBundle,
  DIAGNOSTICS_BUNDLE_VERSION,
} from "./diagnostics";
import type { DeviceLog, SystemInfo } from "../schemas/api";
import type { KilnSettings } from "../types/kiln";

const system: SystemInfo = {
  firmware: "v1.4.2",
  model: "Bisque ESP32-S3",
  uptimeSeconds: 86412.5,
  freeHeap: 198432,
  freeInternalHeap: 31744,
  emergencyStop: false,
  lastErrorCode: 0,
  elementHoursS: 151200,
  spiffsTotal: 917504,
  spiffsUsed: 233472,
  boardTempC: 38.25,
};

const settings = {
  maxTemp: 1300,
  tempUnit: "C",
  apiTokenSet: true,
  webhookUrl: "https://hooks.slack.com/services/T000/B000/XXXXsecretXXXX",
} as unknown as KilnSettings;

const log: DeviceLog = {
  lines: ["I (312) main: === Bisque v1.4.2 ===", "E (940512) firing: aborting, error=3"],
  lineCount: 2,
  droppedLines: 128,
  totalLines: 1204,
  usedBytes: 5891,
  capacityBytes: 6144,
};

const ok = <T>(value: T): PromiseSettledResult<T> => ({ status: "fulfilled", value });
const failed = <T>(message: string): PromiseSettledResult<T> => ({
  status: "rejected",
  reason: new Error(message),
});

const AT = new Date("2026-08-12T14:30:05Z");

describe("buildDiagnosticsBundle", () => {
  it("carries every section plus the collection metadata", () => {
    const bundle = buildDiagnosticsBundle(
      { system: ok(system), settings: ok(settings), log: ok(log) },
      { generatedAt: AT, userAgent: "Mozilla/5.0 (test)", href: "http://kiln.local/settings" },
    );

    expect(bundle.bundleVersion).toBe(DIAGNOSTICS_BUNDLE_VERSION);
    expect(bundle.generatedAt).toBe(AT.toISOString());
    expect(bundle.client).toEqual({
      userAgent: "Mozilla/5.0 (test)",
      href: "http://kiln.local/settings",
    });
    expect(bundle.system).toEqual(system);
    expect(bundle.settings).toEqual({ ...settings, webhookUrl: REDACTED });
    expect(bundle.log).toEqual(log);
    // No `errors` key at all when nothing failed — an empty object would read
    // as "something went wrong and nobody said what".
    expect(bundle.errors).toBeUndefined();
    expect(hasAnySection(bundle)).toBe(true);
  });

  /**
   * The case that matters most in the field: a controller on firmware older
   * than GET /log 404s it, and the bundle is still the thing to attach to the
   * bug report.
   */
  it("keeps the sections that succeeded and records the ones that did not", () => {
    const bundle = buildDiagnosticsBundle(
      { system: ok(system), settings: ok(settings), log: failed("API error 404: Not found") },
      { generatedAt: AT },
    );

    expect(bundle.system).toEqual(system);
    expect(bundle.log).toBeUndefined();
    expect(bundle.errors).toEqual({ log: "API error 404: Not found" });
    expect(hasAnySection(bundle)).toBe(true);
  });

  it("reports an all-failed collection as having nothing worth saving", () => {
    const bundle = buildDiagnosticsBundle(
      {
        system: failed("API error 401: Unauthorized"),
        settings: failed("API error 401: Unauthorized"),
        log: failed("API error 401: Unauthorized"),
      },
      { generatedAt: AT },
    );

    expect(hasAnySection(bundle)).toBe(false);
    expect(Object.keys(bundle.errors ?? {})).toEqual(["system", "settings", "log"]);
  });

  it("serializes to indented JSON that round-trips", () => {
    const bundle = buildDiagnosticsBundle(
      { system: ok(system), settings: ok(settings), log: ok(log) },
      { generatedAt: AT },
    );
    const text = serializeDiagnosticsBundle(bundle);

    expect(text).toContain("\n  ");
    expect(JSON.parse(text)).toEqual(bundle);
  });
});

/**
 * The bundle exists to be handed to someone else, so anything in it that can be
 * *used* rather than merely read has to go. The firmware already reduces the
 * API token to `apiTokenSet`; `webhookUrl` is the one credential GET /settings
 * still returns in full, and for Slack, Discord, ntfy and IFTTT the URL is the
 * credential.
 */
describe("redactSettings", () => {
  it("replaces a configured webhook URL without hiding that one is configured", () => {
    const redacted = redactSettings(settings);

    expect(redacted.webhookUrl).toBe(REDACTED);
    expect(JSON.stringify(redacted)).not.toContain("XXXXsecretXXXX");
    // Everything else survives — this is a redaction, not a filter.
    expect(redacted.tempUnit).toBe(settings.tempUnit);
    expect(redacted.apiTokenSet).toBe(true);
  });

  it("leaves an unconfigured webhook empty rather than claiming one is set", () => {
    expect(redactSettings({ ...settings, webhookUrl: "" }).webhookUrl).toBe("");
  });

  /**
   * build_settings_json() never emits `apiToken`. Dropping it anyway is the
   * defensive half: a firmware regression that started returning it must not
   * find a path into a file people paste into bug reports.
   */
  it("drops an api token even though the firmware should never send one", () => {
    const withToken = { ...settings, apiToken: "hunter2" } as KilnSettings;
    expect(JSON.stringify(redactSettings(withToken))).not.toContain("hunter2");
  });

  it("does not mutate the response it was given", () => {
    const original = { ...settings };
    redactSettings(settings);
    expect(settings).toEqual(original);
  });
});

describe("diagnosticsFilename", () => {
  /**
   * Local time, not UTC: the operator is matching this against the clock on the
   * wall next to the kiln. Built from the same Date the bundle stamps, so the
   * file name and `generatedAt` can never disagree.
   */
  it("stamps the local date and time", () => {
    const at = new Date(2026, 7, 12, 9, 5, 3);
    expect(diagnosticsFilename(at)).toBe("bisque-diagnostics-20260812-090503.json");
  });
});
