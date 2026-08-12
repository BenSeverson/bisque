/**
 * The diagnostics bundle behind Settings → Diagnostics → Download Diagnostics
 * (#189).
 *
 * Three independent requests feed it — GET /log, /system and /settings — and
 * the assembly is deliberately separated from the fetching so both halves are
 * testable: this file turns settled promises into the file's contents and
 * nothing here touches the network or the DOM.
 *
 * Partial failure produces a bundle, never an error. A controller running
 * firmware older than the log endpoint answers /log with a 404, and the
 * remaining two sections are exactly what a person troubleshooting that kiln
 * needs; the failure is recorded in `errors` so the reader can see the section
 * is missing rather than assume the kiln had nothing to say.
 *
 * Nothing secret goes in. GET /settings replaces the API token with the
 * `apiTokenSet` boolean on the firmware side (build_settings_json), which is
 * what makes it safe to attach to a forum post — and the reason the bundle
 * takes the API response rather than the settings form's own values. The one
 * credential the firmware does return verbatim is `webhookUrl`, redacted here;
 * see redactSettings().
 */
import type { DeviceLog, SystemInfo } from "../schemas/api";
import type { KilnSettings } from "../types/kiln";
import { toErrorMessage } from "./error";

export const DIAGNOSTICS_BUNDLE_VERSION = 1;

export interface DiagnosticsBundle {
  bundleVersion: number;
  generatedAt: string;
  client: { userAgent?: string; href?: string };
  system?: SystemInfo;
  settings?: KilnSettings;
  log?: DeviceLog;
  /** Section name → why it is absent. Omitted entirely when everything worked. */
  errors?: Record<string, string>;
}

export interface DiagnosticsSources {
  system: PromiseSettledResult<SystemInfo>;
  settings: PromiseSettledResult<KilnSettings>;
  log: PromiseSettledResult<DeviceLog>;
}

export interface DiagnosticsMeta {
  generatedAt: Date;
  userAgent?: string;
  href?: string;
}

/** What a configured webhook URL is replaced with in the bundle. */
export const REDACTED = "[redacted]";

/**
 * Strip the credentials out of a `/settings` response.
 *
 * `webhookUrl` is the one secret the firmware returns in full — and for every
 * service anyone actually points it at (Slack, Discord, ntfy, IFTTT) the URL
 * *is* the credential, with the token in its path. A bundle is written to be
 * pasted into a bug report, so anyone holding the file could otherwise fire the
 * kiln owner's notifications.
 *
 * The key is redacted rather than dropped: "a webhook is configured" is worth
 * knowing when the complaint is that notifications aren't arriving, and an
 * absent key would read as "not configured". `apiToken` gets the same treatment
 * defensively — build_settings_json() never emits it, and if some future
 * firmware regressed and did, this is where it must not reach a file.
 */
export function redactSettings(settings: KilnSettings): KilnSettings {
  const { apiToken: _apiToken, ...rest } = settings as KilnSettings & { apiToken?: string };
  return {
    ...rest,
    webhookUrl: settings.webhookUrl ? REDACTED : "",
  } as KilnSettings;
}

export function buildDiagnosticsBundle(
  sources: DiagnosticsSources,
  meta: DiagnosticsMeta,
): DiagnosticsBundle {
  const bundle: DiagnosticsBundle = {
    bundleVersion: DIAGNOSTICS_BUNDLE_VERSION,
    generatedAt: meta.generatedAt.toISOString(),
    client: { userAgent: meta.userAgent, href: meta.href },
  };
  const errors: Record<string, string> = {};

  /** The value if the request succeeded; otherwise records why it did not. */
  const take = <T>(result: PromiseSettledResult<T>, key: string): T | undefined => {
    if (result.status === "fulfilled") {
      return result.value;
    }
    errors[key] = toErrorMessage(result.reason);
    return undefined;
  };

  const system = take(sources.system, "system");
  if (system) bundle.system = system;
  const settings = take(sources.settings, "settings");
  if (settings) bundle.settings = redactSettings(settings);
  const log = take(sources.log, "log");
  if (log) bundle.log = log;

  if (Object.keys(errors).length > 0) {
    bundle.errors = errors;
  }
  return bundle;
}

/** Serialized bundle, indented — it is read by a person, not by a parser. */
export function serializeDiagnosticsBundle(bundle: DiagnosticsBundle): string {
  return JSON.stringify(bundle, null, 2);
}

/**
 * `bisque-diagnostics-20260812-143005.json`, in the operator's local time —
 * they are matching this against when the firing went wrong, not against UTC.
 */
export function diagnosticsFilename(at: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp =
    `${at.getFullYear()}${pad(at.getMonth() + 1)}${pad(at.getDate())}` +
    `-${pad(at.getHours())}${pad(at.getMinutes())}${pad(at.getSeconds())}`;
  return `bisque-diagnostics-${stamp}.json`;
}

/** True when at least one section is present — an all-failed bundle is not worth saving. */
export function hasAnySection(bundle: DiagnosticsBundle): boolean {
  return bundle.system !== undefined || bundle.settings !== undefined || bundle.log !== undefined;
}
