/**
 * Transport-agnostic mock kiln router.
 *
 * This module is browser-safe: it has NO Node dependencies (no `http`, no
 * streams, no `process`). `dispatch()` maps an HTTP method + API path + parsed
 * body to a plain result object. The Node entry points (`handlers.ts` →
 * `plugin.ts`/`standalone.ts`) wrap it with `IncomingMessage`/`ServerResponse`;
 * the browser demo (`src/app/mock/installDemo.ts`) wraps it with a `fetch`
 * interceptor. Keeping the routing here means one simulation core serves the
 * Vite dev server, the iOS standalone mock, and the static GitHub Pages demo.
 */
import type {
  FiringProfile,
  FiringSegment,
  HistoryRecord,
  KilnSettings,
} from "../src/app/types/kiln";
import { state, FIRING_ERR } from "./state";
import {
  startFiring,
  stopFiring,
  pauseFiring,
  skipSegment,
  tripFault,
  getStatusResponse,
  ensureTicking,
} from "./simulator";

export interface DispatchResult {
  status: number;
  /** JSON body (serialized by the caller). Mutually exclusive with `text`. */
  json?: unknown;
  /** Raw text body (e.g. CSV). Mutually exclusive with `json`. */
  text?: string;
  /** Overrides the default Content-Type (application/json for json, text/plain for text). */
  contentType?: string;
  /** Extra response headers (e.g. Content-Disposition for downloads). */
  headers?: Record<string, string>;
}

// --- Orton cone table ---
// Values are a verbatim copy of components/cone_table/cone_table.c. They drift
// easily and silently — the mock previously had 36 entries (cone 05.5 missing,
// shifting every id >= 17) and ~20 wrong temperatures, which the public demo
// showed as real cone data. `cone table matches the firmware fixture exactly`
// in test/contracts/firmwareContract.test.ts now compares this array against
// the JSON the C serializer emits, so any future edit to either side fails CI.
/** Settings fields the firmware's POST /settings handler actually reads. */
const SETTINGS_KEYS = new Set<string>([
  "tempUnit",
  "maxSafeTemp",
  "alarmEnabled",
  "autoShutdown",
  "notificationsEnabled",
  "tcOffsetC",
  "webhookUrl",
  "elementWatts",
  "electricityCostKwh",
]);

export const CONE_TABLE = [
  { id: 0, name: "022", slowTempC: 586, mediumTempC: 590, fastTempC: 605 },
  { id: 1, name: "021", slowTempC: 600, mediumTempC: 605, fastTempC: 616 },
  { id: 2, name: "020", slowTempC: 626, mediumTempC: 634, fastTempC: 638 },
  { id: 3, name: "019", slowTempC: 656, mediumTempC: 671, fastTempC: 678 },
  { id: 4, name: "018", slowTempC: 686, mediumTempC: 698, fastTempC: 715 },
  { id: 5, name: "017", slowTempC: 704, mediumTempC: 715, fastTempC: 736 },
  { id: 6, name: "016", slowTempC: 742, mediumTempC: 748, fastTempC: 769 },
  { id: 7, name: "015", slowTempC: 751, mediumTempC: 764, fastTempC: 788 },
  { id: 8, name: "014", slowTempC: 757, mediumTempC: 782, fastTempC: 807 },
  { id: 9, name: "013", slowTempC: 807, mediumTempC: 815, fastTempC: 837 },
  { id: 10, name: "012", slowTempC: 843, mediumTempC: 853, fastTempC: 861 },
  { id: 11, name: "011", slowTempC: 857, mediumTempC: 867, fastTempC: 875 },
  { id: 12, name: "010", slowTempC: 891, mediumTempC: 894, fastTempC: 903 },
  { id: 13, name: "09", slowTempC: 917, mediumTempC: 923, fastTempC: 928 },
  { id: 14, name: "08", slowTempC: 945, mediumTempC: 955, fastTempC: 983 },
  { id: 15, name: "07", slowTempC: 973, mediumTempC: 984, fastTempC: 1008 },
  { id: 16, name: "06", slowTempC: 991, mediumTempC: 999, fastTempC: 1023 },
  { id: 17, name: "05.5", slowTempC: 1011, mediumTempC: 1020, fastTempC: 1043 },
  { id: 18, name: "05", slowTempC: 1031, mediumTempC: 1046, fastTempC: 1066 },
  { id: 19, name: "04", slowTempC: 1050, mediumTempC: 1060, fastTempC: 1083 },
  { id: 20, name: "03", slowTempC: 1086, mediumTempC: 1101, fastTempC: 1115 },
  { id: 21, name: "02", slowTempC: 1101, mediumTempC: 1120, fastTempC: 1138 },
  { id: 22, name: "01", slowTempC: 1117, mediumTempC: 1137, fastTempC: 1154 },
  { id: 23, name: "1", slowTempC: 1136, mediumTempC: 1154, fastTempC: 1162 },
  { id: 24, name: "2", slowTempC: 1142, mediumTempC: 1162, fastTempC: 1173 },
  { id: 25, name: "3", slowTempC: 1152, mediumTempC: 1168, fastTempC: 1181 },
  { id: 26, name: "4", slowTempC: 1162, mediumTempC: 1182, fastTempC: 1196 },
  { id: 27, name: "5", slowTempC: 1177, mediumTempC: 1196, fastTempC: 1207 },
  { id: 28, name: "6", slowTempC: 1201, mediumTempC: 1222, fastTempC: 1240 },
  { id: 29, name: "7", slowTempC: 1215, mediumTempC: 1239, fastTempC: 1255 },
  { id: 30, name: "8", slowTempC: 1236, mediumTempC: 1252, fastTempC: 1274 },
  { id: 31, name: "9", slowTempC: 1260, mediumTempC: 1280, fastTempC: 1285 },
  { id: 32, name: "10", slowTempC: 1285, mediumTempC: 1305, fastTempC: 1315 },
  { id: 33, name: "11", slowTempC: 1294, mediumTempC: 1315, fastTempC: 1326 },
  { id: 34, name: "12", slowTempC: 1306, mediumTempC: 1326, fastTempC: 1355 },
  { id: 35, name: "13", slowTempC: 1321, mediumTempC: 1348, fastTempC: 1380 },
  { id: 36, name: "14", slowTempC: 1388, mediumTempC: 1395, fastTempC: 1410 },
];

function generateTraceCsv(record: HistoryRecord): string {
  const lines = ["time_s,temp_c"];
  const steps = Math.floor(record.durationS / 60);
  const peak = record.peakTemp;
  for (let i = 0; i <= steps; i++) {
    const t = i * 60;
    const progress = i / steps;
    // Simple ramp-up then hold-at-peak
    const rampFrac = Math.min(1, progress / 0.8);
    const temp = 20 + (peak - 20) * Math.sqrt(rampFrac) + (Math.random() - 0.5) * 3;
    lines.push(`${t},${temp.toFixed(1)}`);
  }
  return lines.join("\n");
}

interface ConeFireParams {
  coneId: number;
  speed: number;
  preheat: boolean;
  slowCool: boolean;
  save: boolean;
}

// Generate a cone fire profile from cone entry + options
function generateConeFire(params: ConeFireParams): FiringProfile | null {
  const cone = CONE_TABLE.find((c) => c.id === params.coneId);
  if (!cone) return null;

  const targetTemp =
    [cone.slowTempC, cone.mediumTempC, cone.fastTempC][params.speed] ?? cone.mediumTempC;
  const speedLabel = ["slow", "medium", "fast"][params.speed] ?? "medium";
  const rampRates = [60, 100, 150][params.speed] ?? 100;

  const segments: FiringSegment[] = [];
  let id = 1;

  if (params.preheat) {
    segments.push({
      id: `cone-seg-${id++}`,
      name: "Preheat",
      rampRate: 80,
      targetTemp: 120,
      holdTime: 30,
    });
  }

  segments.push({
    id: `cone-seg-${id++}`,
    name: "Water Smoke",
    rampRate: 60,
    targetTemp: 220,
    holdTime: 0,
  });

  segments.push({
    id: `cone-seg-${id++}`,
    name: "Quartz Zone",
    rampRate: 100,
    targetTemp: 600,
    holdTime: 0,
  });

  segments.push({
    id: `cone-seg-${id++}`,
    name: `Final Ramp to Cone ${cone.name}`,
    rampRate: rampRates,
    targetTemp,
    holdTime: 10,
  });

  if (params.slowCool) {
    segments.push({
      id: `cone-seg-${id++}`,
      name: "Slow Cool (Quartz Inv.)",
      rampRate: -150,
      targetTemp: 650,
      holdTime: 0,
    });
    segments.push({
      id: `cone-seg-${id}`,
      name: "Slow Cool 2",
      rampRate: -50,
      targetTemp: 500,
      holdTime: 0,
    });
  }

  let duration = 0;
  let currentTemp = 20;
  for (const seg of segments) {
    const dt = (Math.abs(seg.targetTemp - currentTemp) / Math.abs(seg.rampRate)) * 60;
    duration += dt + seg.holdTime;
    currentTemp = seg.targetTemp;
  }

  return {
    id: `cone-${cone.name}-${speedLabel}-${Date.now().toString(36)}`,
    name: `Cone ${cone.name} (${speedLabel})`,
    description: `Orton cone ${cone.name} firing — ${speedLabel} speed. Target: ${targetTemp}°C.`,
    segments,
    maxTemp: targetTemp,
    estimatedDuration: Math.round(duration),
  };
}

/**
 * Route an API request to a plain result. Synchronous and browser-safe — the
 * body is already parsed by the caller. Side effects on `state` (and timers for
 * firing/autotune) are intentional.
 */
export function dispatch(method: string, apiPath: string, body: unknown): DispatchResult {
  // GET /status
  if (method === "GET" && apiPath === "/status") {
    return { status: 200, json: getStatusResponse() };
  }

  // GET /cone-table
  if (method === "GET" && apiPath === "/cone-table") {
    return { status: 200, json: CONE_TABLE };
  }

  // GET /profiles
  if (method === "GET" && apiPath === "/profiles") {
    return { status: 200, json: state.profiles };
  }

  // POST /profiles/import
  if (method === "POST" && apiPath === "/profiles/import") {
    const profile = body as FiringProfile;
    const idx = state.profiles.findIndex((p) => p.id === profile.id);
    if (idx >= 0) {
      state.profiles[idx] = profile;
    } else {
      state.profiles.push(profile);
    }
    return { status: 200, json: { ok: true, id: profile.id } };
  }

  // POST /profiles/cone-fire
  if (method === "POST" && apiPath === "/profiles/cone-fire") {
    const params = body as ConeFireParams;
    const profile = generateConeFire(params);
    if (!profile) return { status: 400, json: { error: "Invalid cone ID" } };
    if (params.save) {
      state.profiles.push(profile);
    }
    return { status: 200, json: profile };
  }

  // Match /profiles/:id or /profiles/:id/export
  const profileExportMatch = apiPath.match(/^\/profiles\/(.+)\/export$/);
  const profileMatch = apiPath.match(/^\/profiles\/([^/]+)$/);

  // GET /profiles/:id/export
  if (method === "GET" && profileExportMatch) {
    const profile = state.profiles.find((p) => p.id === profileExportMatch[1]);
    if (!profile) return { status: 404, json: { error: "Not found" } };
    return {
      status: 200,
      text: JSON.stringify(profile, null, 2),
      contentType: "application/json",
      headers: { "Content-Disposition": `attachment; filename="${profile.id}.json"` },
    };
  }

  // GET /profiles/:id
  if (method === "GET" && profileMatch) {
    const profile = state.profiles.find((p) => p.id === profileMatch[1]);
    if (!profile) return { status: 404, json: { error: "Not found" } };
    return { status: 200, json: profile };
  }

  // POST /profiles (upsert)
  if (method === "POST" && apiPath === "/profiles") {
    const profile = body as FiringProfile;
    const idx = state.profiles.findIndex((p) => p.id === profile.id);
    if (idx >= 0) {
      state.profiles[idx] = profile;
    } else {
      state.profiles.push(profile);
    }
    return { status: 200, json: { ok: true, id: profile.id } };
  }

  // DELETE /profiles/:id
  if (method === "DELETE" && profileMatch) {
    state.profiles = state.profiles.filter((p) => p.id !== profileMatch[1]);
    return { status: 200, json: { ok: true } };
  }

  // POST /firing/start
  if (method === "POST" && apiPath === "/firing/start") {
    const req = body as { profileId: string; delayMinutes?: number };
    const ok = startFiring(req.profileId, req.delayMinutes ?? 0);
    if (!ok) return { status: 400, json: { ok: false, error: "Profile not found" } };
    return { status: 200, json: { ok: true } };
  }

  // POST /firing/stop
  if (method === "POST" && apiPath === "/firing/stop") {
    stopFiring();
    return { status: 200, json: { ok: true } };
  }

  // POST /firing/pause
  if (method === "POST" && apiPath === "/firing/pause") {
    const action = pauseFiring();
    return { status: 200, json: { ok: true, action } };
  }

  // POST /firing/skip-segment
  if (method === "POST" && apiPath === "/firing/skip-segment") {
    skipSegment();
    return { status: 200, json: { ok: true } };
  }

  // GET /history
  if (method === "GET" && apiPath === "/history") {
    return { status: 200, json: state.history };
  }

  // GET /history/:id/trace
  const historyTraceMatch = apiPath.match(/^\/history\/(\d+)\/trace$/);
  if (method === "GET" && historyTraceMatch) {
    const id = parseInt(historyTraceMatch[1], 10);
    const record = state.history.find((r) => r.id === id);
    if (!record) return { status: 404, json: { error: "Not found" } };
    return { status: 200, text: generateTraceCsv(record), contentType: "text/csv" };
  }

  // GET /settings
  if (method === "GET" && apiPath === "/settings") {
    return {
      status: 200,
      json: {
        ...state.settings,
        tcOffsetC: state.settings.tcOffsetC ?? 0,
        webhookUrl: state.settings.webhookUrl ?? "",
        apiTokenSet: false,
        elementWatts: state.settings.elementWatts ?? 5000,
        electricityCostKwh: state.settings.electricityCostKwh ?? 0.15,
      },
    };
  }

  // POST /settings
  if (method === "POST" && apiPath === "/settings") {
    // Never store the raw api token in state — just note it's been set
    const { apiToken, ...rest } = body as Partial<KilnSettings> & { apiToken?: string };

    // The firmware reads named fields out of the request body with
    // cJSON_GetObjectItem and ignores everything else (handle_post_settings,
    // api_handlers.c:632) — it never rejects an unknown key, and it never
    // grows one either.
    //
    // The bug in #166 was the second half of that: the mock used to
    // Object.assign the whole body, so a misspelled field (`temperatureUnit`)
    // was merged into stored settings and echoed back on every later GET,
    // hiding exactly the kind of contract drift this mock exists to expose.
    // Dropping unknown keys fixes that while staying faithful.
    //
    // Rejecting them, which is what this did first, is *less* faithful than
    // the old behaviour rather than more — and it broke every settings save in
    // the demo, because the client legitimately posts the read-only
    // `apiTokenSet` back with the rest of the form (Settings.tsx:191, and the
    // form resets from a GET that includes it).
    const known = Object.fromEntries(Object.entries(rest).filter(([k]) => SETTINGS_KEYS.has(k)));
    Object.assign(state.settings, known);
    if (apiToken !== undefined) {
      state.settings.apiTokenSet = !!apiToken;
    }
    return { status: 200, json: { ok: true } };
  }

  // GET /system
  if (method === "GET" && apiPath === "/system") {
    return {
      status: 200,
      json: {
        firmware: "2.0.0-mock",
        model: "Bisque ESP32-S3 (Simulated)",
        uptimeSeconds: Math.round((Date.now() - state.startupTime) / 1000),
        freeHeap: 200000 + Math.round(Math.random() * 10000),
        emergencyStop: state.emergencyStop,
        lastErrorCode: state.lastErrorCode,
        elementHoursS: 3600 * 42,
        spiffsTotal: 917504,
        spiffsUsed: 204800 + Math.round(Math.random() * 50000),
        boardTempC: 35 + Math.random() * 10,
      },
    };
  }

  // POST /autotune/start
  if (method === "POST" && apiPath === "/autotune/start") {
    const { setpoint, hysteresis } = body as { setpoint: number; hysteresis: number };
    if (!startAutotune(setpoint, hysteresis)) {
      return { status: 409, json: { error: "A firing is already active" } };
    }
    return { status: 200, json: { ok: true } };
  }

  // POST /autotune/stop
  if (method === "POST" && apiPath === "/autotune/stop") {
    stopAutotune();
    return { status: 200, json: { ok: true } };
  }

  // GET /autotune/status
  if (method === "GET" && apiPath === "/autotune/status") {
    return { status: 200, json: getAutotuneStatus() };
  }

  // POST /ota
  if (method === "POST" && apiPath === "/ota") {
    return { status: 200, json: { ok: true } };
  }

  // GET /wifi
  if (method === "GET" && apiPath === "/wifi") {
    const w = state.wifi;
    const hasSaved = !!w.savedSsid;
    return {
      status: 200,
      json: {
        connected: w.connected,
        apMode: w.apMode,
        ip: w.ip,
        hasSavedCredentials: hasSaved,
        ...(hasSaved ? { savedSsid: w.savedSsid } : {}),
      },
    };
  }

  // POST /wifi
  if (method === "POST" && apiPath === "/wifi") {
    const { ssid } = body as { ssid?: string };
    if (!ssid) {
      return { status: 400, json: { error: "Missing ssid" } };
    }
    state.wifi.savedSsid = ssid;
    return {
      status: 200,
      json: { ok: true, message: "Wi-Fi credentials saved. Reboot to connect." },
    };
  }

  // DELETE /wifi
  if (method === "DELETE" && apiPath === "/wifi") {
    state.wifi.savedSsid = undefined;
    state.wifi.connected = false;
    state.wifi.apMode = true;
    state.wifi.ip = "192.168.4.1";
    return {
      status: 200,
      json: {
        ok: true,
        message: "Wi-Fi credentials cleared. Will start in AP mode after reboot.",
      },
    };
  }

  // POST /reboot
  if (method === "POST" && apiPath === "/reboot") {
    return { status: 200, json: { ok: true, message: "Rebooting..." } };
  }

  // POST /diagnostics/relay
  if (method === "POST" && apiPath === "/diagnostics/relay") {
    const durationSeconds = (body as { durationSeconds?: number }).durationSeconds ?? 2;
    return { status: 200, json: { ok: true, durationSeconds } };
  }

  // POST /mock/fault — simulator-only, no firmware counterpart
  //
  // The kiln has no "fail now" command; a real one fails on its own. Everything
  // downstream of a fault was therefore unreachable in the mock — the dashboard
  // error banner, the history detail cause, Settings' Last Error and
  // emergency-stop guidance (all #235) — in dev, in Vitest, and in the
  // published demo (#239). This is the lever that makes them exercisable.
  //
  // The `/mock/` prefix marks it as a simulator affordance rather than API
  // surface a client may depend on. It cannot leak into a device build: the
  // whole mock-server tree is dev/demo-only, and a real controller 404s it.
  if (method === "POST" && apiPath === "/mock/fault") {
    const code = (body as { code?: number }).code ?? FIRING_ERR.TC_FAULT;
    if (!Number.isInteger(code) || code < 1) {
      return { status: 400, json: { ok: false, error: "code must be a positive integer" } };
    }
    tripFault(code);
    return {
      status: 200,
      json: { ok: true, lastErrorCode: state.lastErrorCode, status: state.firing.status },
    };
  }

  // GET /diagnostics/thermocouple
  if (method === "GET" && apiPath === "/diagnostics/thermocouple") {
    const temp = state.firing.currentTemp;
    return {
      status: 200,
      json: {
        temperatureC: temp + (Math.random() - 0.5) * 0.5,
        internalTempC: 24.5 + (Math.random() - 0.5),
        fault: false,
        openCircuit: false,
        shortGnd: false,
        shortVcc: false,
        readingAgeMs: Math.round(Math.random() * 250),
        tcOffsetC: state.settings.tcOffsetC ?? 0,
        temperatureAdjustedC: temp + (state.settings.tcOffsetC ?? 0),
      },
    };
  }

  return { status: 404, json: { error: "Not found" } };
}

// --- Autotune simulation ---

/**
 * Returns false if the firmware would have rejected the start.
 *
 * FIRING_CMD_AUTOTUNE_START refuses while a firing is active or a delayed start
 * is armed. The mock had no such guard, so both intervals wrote
 * state.firing.currentTemp and .status every second and the demo dashboard
 * flickered between the firing and the tune (#131).
 */
function startAutotune(setpoint: number, hysteresis: number): boolean {
  const at = state.autotune;
  if (state.firing.running || state.firing.scheduled) return false;
  if (at.interval) clearInterval(at.interval);

  at.running = true;
  at.completed = false;
  at.setpoint = setpoint;
  at.hysteresis = hysteresis;
  at.currentTemp = state.firing.currentTemp;
  at.startTime = Date.now();
  at.elapsed = 0;

  let oscillation = 0;
  at.interval = setInterval(() => {
    at.elapsed = (Date.now() - at.startTime) / 1000;
    oscillation += 0.1;
    at.currentTemp = setpoint + Math.sin(oscillation) * hysteresis + (Math.random() - 0.5) * 2;
    state.firing.currentTemp = at.currentTemp;
    state.firing.status = "autotune";

    // Complete after ~60 real seconds
    if (at.elapsed >= 60) {
      at.running = false;
      at.completed = true;
      at.gains = {
        kp: 2.0 + Math.random() * 0.5,
        ki: 0.3 + Math.random() * 0.2,
        kd: 1.0 + Math.random() * 0.3,
      };
      state.firing.status = "idle";
      // Hand the kiln back to the passive-cooling tick. Without this the demo
      // kiln sat pinned at the autotune setpoint indefinitely, since nothing
      // else was driving its temperature down (#131).
      state.firing.coolingDown = true;
      ensureTicking();
      if (at.interval) {
        clearInterval(at.interval);
        at.interval = null;
      }
    }
  }, 1000);
  return true;
}

function stopAutotune(): void {
  const at = state.autotune;
  const wasRunning = at.running;
  if (at.interval) {
    clearInterval(at.interval);
    at.interval = null;
  }
  at.running = false;
  state.firing.status = "idle";
  // A cancelled tune leaves the kiln hot too — cool it down like a completed one.
  if (wasRunning) {
    state.firing.coolingDown = true;
    ensureTicking();
  }
}

function getAutotuneStatus() {
  const at = state.autotune;
  return {
    state: at.running ? "running" : at.completed ? "complete" : "idle",
    elapsedTime: Math.round(at.elapsed),
    targetTemp: at.setpoint,
    currentTemp: Math.round(at.currentTemp * 10) / 10,
    currentGains: { ...at.gains },
  };
}
