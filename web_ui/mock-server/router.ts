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
import type { FiringProfile, FiringSegment, KilnSettings } from '../src/app/types/kiln';
import { state } from './state';
import { startFiring, stopFiring, pauseFiring, getStatusResponse } from './simulator';

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

// --- Mock Orton cone table ---
const CONE_TABLE = [
  { id: 0,  name: '022', slowTempC: 585,  mediumTempC: 600,  fastTempC: 630 },
  { id: 1,  name: '021', slowTempC: 602,  mediumTempC: 614,  fastTempC: 643 },
  { id: 2,  name: '020', slowTempC: 625,  mediumTempC: 635,  fastTempC: 666 },
  { id: 3,  name: '019', slowTempC: 630,  mediumTempC: 643,  fastTempC: 673 },
  { id: 4,  name: '018', slowTempC: 670,  mediumTempC: 696,  fastTempC: 720 },
  { id: 5,  name: '017', slowTempC: 720,  mediumTempC: 736,  fastTempC: 770 },
  { id: 6,  name: '016', slowTempC: 742,  mediumTempC: 769,  fastTempC: 796 },
  { id: 7,  name: '015', slowTempC: 747,  mediumTempC: 791,  fastTempC: 818 },
  { id: 8,  name: '014', slowTempC: 757,  mediumTempC: 807,  fastTempC: 836 },
  { id: 9,  name: '013', slowTempC: 807,  mediumTempC: 837,  fastTempC: 861 },
  { id: 10, name: '012', slowTempC: 843,  mediumTempC: 861,  fastTempC: 882 },
  { id: 11, name: '011', slowTempC: 857,  mediumTempC: 875,  fastTempC: 894 },
  { id: 12, name: '010', slowTempC: 891,  mediumTempC: 903,  fastTempC: 919 },
  { id: 13, name: '09',  slowTempC: 917,  mediumTempC: 920,  fastTempC: 940 },
  { id: 14, name: '08',  slowTempC: 942,  mediumTempC: 945,  fastTempC: 966 },
  { id: 15, name: '07',  slowTempC: 973,  mediumTempC: 973,  fastTempC: 984 },
  { id: 16, name: '06',  slowTempC: 991,  mediumTempC: 991,  fastTempC: 999 },
  { id: 17, name: '05',  slowTempC: 1031, mediumTempC: 1031, fastTempC: 1046 },
  { id: 18, name: '04',  slowTempC: 1063, mediumTempC: 1063, fastTempC: 1077 },
  { id: 19, name: '03',  slowTempC: 1101, mediumTempC: 1101, fastTempC: 1115 },
  { id: 20, name: '02',  slowTempC: 1120, mediumTempC: 1120, fastTempC: 1134 },
  { id: 21, name: '01',  slowTempC: 1137, mediumTempC: 1137, fastTempC: 1154 },
  { id: 22, name: '1',   slowTempC: 1154, mediumTempC: 1162, fastTempC: 1180 },
  { id: 23, name: '2',   slowTempC: 1162, mediumTempC: 1178, fastTempC: 1190 },
  { id: 24, name: '3',   slowTempC: 1168, mediumTempC: 1186, fastTempC: 1196 },
  { id: 25, name: '4',   slowTempC: 1186, mediumTempC: 1197, fastTempC: 1209 },
  { id: 26, name: '5',   slowTempC: 1196, mediumTempC: 1207, fastTempC: 1221 },
  { id: 27, name: '6',   slowTempC: 1222, mediumTempC: 1222, fastTempC: 1240 },
  { id: 28, name: '7',   slowTempC: 1240, mediumTempC: 1240, fastTempC: 1263 },
  { id: 29, name: '8',   slowTempC: 1263, mediumTempC: 1263, fastTempC: 1280 },
  { id: 30, name: '9',   slowTempC: 1280, mediumTempC: 1280, fastTempC: 1305 },
  { id: 31, name: '10',  slowTempC: 1305, mediumTempC: 1305, fastTempC: 1330 },
  { id: 32, name: '11',  slowTempC: 1315, mediumTempC: 1315, fastTempC: 1336 },
  { id: 33, name: '12',  slowTempC: 1326, mediumTempC: 1326, fastTempC: 1355 },
  { id: 34, name: '13',  slowTempC: 1346, mediumTempC: 1346, fastTempC: 1380 },
  { id: 35, name: '14',  slowTempC: 1366, mediumTempC: 1366, fastTempC: 1400 },
];

// --- Mock firing history ---
const mockHistory = [
  {
    id: 1,
    startTime: Math.floor(Date.now() / 1000) - 86400 * 3,
    profileName: 'Bisque Cone 04',
    profileId: 'bisque-cone-04',
    peakTemp: 1063,
    durationS: 14400,
    outcome: 'complete',
    errorCode: 0,
  },
  {
    id: 2,
    startTime: Math.floor(Date.now() / 1000) - 86400,
    profileName: 'Glaze Cone 6',
    profileId: 'glaze-cone-6',
    peakTemp: 1222,
    durationS: 21600,
    outcome: 'complete',
    errorCode: 0,
  },
  {
    id: 3,
    startTime: Math.floor(Date.now() / 1000) - 3600 * 2,
    profileName: 'Custom Test',
    profileId: 'custom-test',
    peakTemp: 850,
    durationS: 5400,
    outcome: 'aborted',
    errorCode: 0,
  },
];

function generateTraceCsv(record: typeof mockHistory[0]): string {
  const lines = ['time_s,temp_c'];
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
  return lines.join('\n');
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

  const targetTemp = [cone.slowTempC, cone.mediumTempC, cone.fastTempC][params.speed] ?? cone.mediumTempC;
  const speedLabel = ['slow', 'medium', 'fast'][params.speed] ?? 'medium';
  const rampRates = [60, 100, 150][params.speed] ?? 100;

  const segments: FiringSegment[] = [];
  let id = 1;

  if (params.preheat) {
    segments.push({
      id: `cone-seg-${id++}`,
      name: 'Preheat',
      rampRate: 80,
      targetTemp: 120,
      holdTime: 30,
    });
  }

  segments.push({
    id: `cone-seg-${id++}`,
    name: 'Water Smoke',
    rampRate: 60,
    targetTemp: 220,
    holdTime: 0,
  });

  segments.push({
    id: `cone-seg-${id++}`,
    name: 'Quartz Zone',
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
      name: 'Slow Cool (Quartz Inv.)',
      rampRate: -150,
      targetTemp: 650,
      holdTime: 0,
    });
    segments.push({
      id: `cone-seg-${id}`,
      name: 'Slow Cool 2',
      rampRate: -50,
      targetTemp: 500,
      holdTime: 0,
    });
  }

  let duration = 0;
  let currentTemp = 20;
  for (const seg of segments) {
    const dt = Math.abs(seg.targetTemp - currentTemp) / Math.abs(seg.rampRate) * 60;
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
  if (method === 'GET' && apiPath === '/status') {
    return { status: 200, json: getStatusResponse() };
  }

  // GET /cone-table
  if (method === 'GET' && apiPath === '/cone-table') {
    return { status: 200, json: CONE_TABLE };
  }

  // GET /profiles
  if (method === 'GET' && apiPath === '/profiles') {
    return { status: 200, json: state.profiles };
  }

  // POST /profiles/import
  if (method === 'POST' && apiPath === '/profiles/import') {
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
  if (method === 'POST' && apiPath === '/profiles/cone-fire') {
    const params = body as ConeFireParams;
    const profile = generateConeFire(params);
    if (!profile) return { status: 400, json: { error: 'Invalid cone ID' } };
    if (params.save) {
      state.profiles.push(profile);
    }
    return { status: 200, json: profile };
  }

  // Match /profiles/:id or /profiles/:id/export
  const profileExportMatch = apiPath.match(/^\/profiles\/(.+)\/export$/);
  const profileMatch = apiPath.match(/^\/profiles\/([^/]+)$/);

  // GET /profiles/:id/export
  if (method === 'GET' && profileExportMatch) {
    const profile = state.profiles.find((p) => p.id === profileExportMatch[1]);
    if (!profile) return { status: 404, json: { error: 'Not found' } };
    return {
      status: 200,
      text: JSON.stringify(profile, null, 2),
      contentType: 'application/json',
      headers: { 'Content-Disposition': `attachment; filename="${profile.id}.json"` },
    };
  }

  // GET /profiles/:id
  if (method === 'GET' && profileMatch) {
    const profile = state.profiles.find((p) => p.id === profileMatch[1]);
    if (!profile) return { status: 404, json: { error: 'Not found' } };
    return { status: 200, json: profile };
  }

  // POST /profiles (upsert)
  if (method === 'POST' && apiPath === '/profiles') {
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
  if (method === 'DELETE' && profileMatch) {
    state.profiles = state.profiles.filter((p) => p.id !== profileMatch[1]);
    return { status: 200, json: { ok: true } };
  }

  // POST /firing/start
  if (method === 'POST' && apiPath === '/firing/start') {
    const ok = startFiring((body as { profileId: string }).profileId);
    if (!ok) return { status: 400, json: { ok: false, error: 'Profile not found' } };
    return { status: 200, json: { ok: true } };
  }

  // POST /firing/stop
  if (method === 'POST' && apiPath === '/firing/stop') {
    stopFiring();
    return { status: 200, json: { ok: true } };
  }

  // POST /firing/pause
  if (method === 'POST' && apiPath === '/firing/pause') {
    const action = pauseFiring();
    return { status: 200, json: { ok: true, action } };
  }

  // POST /firing/skip-segment
  if (method === 'POST' && apiPath === '/firing/skip-segment') {
    // Advance segment index in simulator
    const f = state.firing;
    if (f.running && f.profile) {
      f.currentSegmentIndex = Math.min(
        f.currentSegmentIndex + 1,
        f.profile.segments.length - 1,
      );
      f.phase = 'ramping';
      f.segmentElapsed = 0;
      f.holdElapsed = 0;
      f.segmentStartTemp = f.currentTemp;
    }
    return { status: 200, json: { ok: true } };
  }

  // GET /history
  if (method === 'GET' && apiPath === '/history') {
    return { status: 200, json: mockHistory };
  }

  // GET /history/:id/trace
  const historyTraceMatch = apiPath.match(/^\/history\/(\d+)\/trace$/);
  if (method === 'GET' && historyTraceMatch) {
    const id = parseInt(historyTraceMatch[1], 10);
    const record = mockHistory.find((r) => r.id === id);
    if (!record) return { status: 404, json: { error: 'Not found' } };
    return { status: 200, text: generateTraceCsv(record), contentType: 'text/csv' };
  }

  // GET /settings
  if (method === 'GET' && apiPath === '/settings') {
    return {
      status: 200,
      json: {
        ...state.settings,
        tcOffsetC: state.settings.tcOffsetC ?? 0,
        webhookUrl: state.settings.webhookUrl ?? '',
        apiTokenSet: false,
        elementWatts: state.settings.elementWatts ?? 0,
        electricityCostKwh: state.settings.electricityCostKwh ?? 0,
      },
    };
  }

  // POST /settings
  if (method === 'POST' && apiPath === '/settings') {
    // Never store the raw api token in state — just note it's been set
    const { apiToken, ...rest } = body as Partial<KilnSettings> & { apiToken?: string };
    Object.assign(state.settings, rest);
    if (apiToken !== undefined) {
      state.settings.apiTokenSet = !!apiToken;
    }
    return { status: 200, json: { ok: true } };
  }

  // GET /system
  if (method === 'GET' && apiPath === '/system') {
    return {
      status: 200,
      json: {
        firmware: '2.0.0-mock',
        model: 'Bisque ESP32-S3 (Simulated)',
        uptimeSeconds: Math.round((Date.now() - state.startupTime) / 1000),
        freeHeap: 200000 + Math.round(Math.random() * 10000),
        emergencyStop: false,
        lastErrorCode: 0,
        elementHoursS: 3600 * 42,
        spiffsTotal: 917504,
        spiffsUsed: 204800 + Math.round(Math.random() * 50000),
        boardTempC: 35 + Math.random() * 10,
      },
    };
  }

  // POST /autotune/start
  if (method === 'POST' && apiPath === '/autotune/start') {
    const { setpoint, hysteresis } = body as { setpoint: number; hysteresis: number };
    startAutotune(setpoint, hysteresis);
    return { status: 200, json: { ok: true } };
  }

  // POST /autotune/stop
  if (method === 'POST' && apiPath === '/autotune/stop') {
    stopAutotune();
    return { status: 200, json: { ok: true } };
  }

  // GET /autotune/status
  if (method === 'GET' && apiPath === '/autotune/status') {
    return { status: 200, json: getAutotuneStatus() };
  }

  // POST /ota
  if (method === 'POST' && apiPath === '/ota') {
    return { status: 200, json: { ok: true } };
  }

  // GET /wifi
  if (method === 'GET' && apiPath === '/wifi') {
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
  if (method === 'POST' && apiPath === '/wifi') {
    const { ssid } = body as { ssid?: string };
    if (!ssid) {
      return { status: 400, json: { error: 'Missing ssid' } };
    }
    state.wifi.savedSsid = ssid;
    return { status: 200, json: { ok: true, message: 'Wi-Fi credentials saved. Reboot to connect.' } };
  }

  // DELETE /wifi
  if (method === 'DELETE' && apiPath === '/wifi') {
    state.wifi.savedSsid = undefined;
    state.wifi.connected = false;
    state.wifi.apMode = true;
    state.wifi.ip = '192.168.4.1';
    return {
      status: 200,
      json: {
        ok: true,
        message: 'Wi-Fi credentials cleared. Will start in AP mode after reboot.',
      },
    };
  }

  // POST /reboot
  if (method === 'POST' && apiPath === '/reboot') {
    return { status: 200, json: { ok: true, message: 'Rebooting...' } };
  }

  // POST /diagnostics/relay
  if (method === 'POST' && apiPath === '/diagnostics/relay') {
    const durationSeconds = (body as { durationSeconds?: number }).durationSeconds ?? 2;
    return { status: 200, json: { ok: true, durationSeconds } };
  }

  // GET /diagnostics/thermocouple
  if (method === 'GET' && apiPath === '/diagnostics/thermocouple') {
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

  return { status: 404, json: { error: 'Not found' } };
}

// --- Autotune simulation ---

function startAutotune(setpoint: number, hysteresis: number): void {
  const at = state.autotune;
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
    at.currentTemp =
      setpoint +
      Math.sin(oscillation) * hysteresis +
      (Math.random() - 0.5) * 2;
    state.firing.currentTemp = at.currentTemp;
    state.firing.status = 'autotune';

    // Complete after ~60 real seconds
    if (at.elapsed >= 60) {
      at.running = false;
      at.completed = true;
      at.gains = {
        kp: 2.0 + Math.random() * 0.5,
        ki: 0.3 + Math.random() * 0.2,
        kd: 1.0 + Math.random() * 0.3,
      };
      state.firing.status = 'idle';
      if (at.interval) {
        clearInterval(at.interval);
        at.interval = null;
      }
    }
  }, 1000);
}

function stopAutotune(): void {
  const at = state.autotune;
  if (at.interval) {
    clearInterval(at.interval);
    at.interval = null;
  }
  at.running = false;
  state.firing.status = 'idle';
}

function getAutotuneStatus() {
  const at = state.autotune;
  return {
    state: at.running ? 'running' : at.completed ? 'complete' : 'idle',
    elapsedTime: Math.round(at.elapsed),
    targetTemp: at.setpoint,
    currentTemp: Math.round(at.currentTemp * 10) / 10,
    currentGains: { ...at.gains },
  };
}
