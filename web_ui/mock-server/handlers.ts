import type { IncomingMessage, ServerResponse } from 'http';
import { state } from './state';
import { startFiring, stopFiring, pauseFiring, getStatusResponse } from './simulator';
import { AMBIENT } from './physics';

function json(res: ServerResponse, data: unknown, status = 200): void {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function parseBody(req: IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk: Buffer) => {
      body += chunk.toString();
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error('Invalid JSON'));
      }
    });
  });
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

// Generate a cone fire profile from cone entry + options
function generateConeFire(params: {
  coneId: number;
  speed: number;
  preheat: boolean;
  slowCool: boolean;
  save: boolean;
}): any {
  const cone = CONE_TABLE.find((c) => c.id === params.coneId);
  if (!cone) return null;

  const targetTemp = [cone.slowTempC, cone.mediumTempC, cone.fastTempC][params.speed] ?? cone.mediumTempC;
  const speedLabel = ['slow', 'medium', 'fast'][params.speed] ?? 'medium';
  const rampRates = [60, 100, 150][params.speed] ?? 100;

  const segments: any[] = [];
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
      id: `cone-seg-${id++}`,
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

export async function handleRequest(
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const method = req.method || 'GET';
  const url = req.url || '';
  const apiPath = url.split('?')[0].replace('/api/v1', '');

  try {
    // GET /status
    if (method === 'GET' && apiPath === '/status') {
      return json(res, getStatusResponse());
    }

    // GET /cone-table
    if (method === 'GET' && apiPath === '/cone-table') {
      return json(res, CONE_TABLE);
    }

    // GET /profiles
    if (method === 'GET' && apiPath === '/profiles') {
      return json(res, state.profiles);
    }

    // POST /profiles/import
    if (method === 'POST' && apiPath === '/profiles/import') {
      const body = await parseBody(req);
      const idx = state.profiles.findIndex((p) => p.id === body.id);
      if (idx >= 0) {
        state.profiles[idx] = body;
      } else {
        state.profiles.push(body);
      }
      return json(res, { ok: true, id: body.id });
    }

    // POST /profiles/cone-fire
    if (method === 'POST' && apiPath === '/profiles/cone-fire') {
      const body = await parseBody(req);
      const profile = generateConeFire(body);
      if (!profile) return json(res, { error: 'Invalid cone ID' }, 400);
      if (body.save) {
        state.profiles.push(profile);
      }
      return json(res, profile);
    }

    // Match /profiles/:id or /profiles/:id/export
    const profileExportMatch = apiPath.match(/^\/profiles\/(.+)\/export$/);
    const profileMatch = apiPath.match(/^\/profiles\/([^/]+)$/);

    // GET /profiles/:id/export
    if (method === 'GET' && profileExportMatch) {
      const profile = state.profiles.find((p) => p.id === profileExportMatch[1]);
      if (!profile) return json(res, { error: 'Not found' }, 404);
      res.writeHead(200, {
        'Content-Type': 'application/json',
        'Content-Disposition': `attachment; filename="${profile.id}.json"`,
      });
      res.end(JSON.stringify(profile, null, 2));
      return;
    }

    // GET /profiles/:id
    if (method === 'GET' && profileMatch) {
      const profile = state.profiles.find((p) => p.id === profileMatch[1]);
      if (!profile) return json(res, { error: 'Not found' }, 404);
      return json(res, profile);
    }

    // POST /profiles (upsert)
    if (method === 'POST' && apiPath === '/profiles') {
      const body = await parseBody(req);
      const idx = state.profiles.findIndex((p) => p.id === body.id);
      if (idx >= 0) {
        state.profiles[idx] = body;
      } else {
        state.profiles.push(body);
      }
      return json(res, { ok: true, id: body.id });
    }

    // DELETE /profiles/:id
    if (method === 'DELETE' && profileMatch) {
      state.profiles = state.profiles.filter((p) => p.id !== profileMatch[1]);
      return json(res, { ok: true });
    }

    // POST /firing/start
    if (method === 'POST' && apiPath === '/firing/start') {
      const body = await parseBody(req);
      const ok = startFiring(body.profileId);
      if (!ok) return json(res, { ok: false, error: 'Profile not found' }, 400);
      return json(res, { ok: true });
    }

    // POST /firing/stop
    if (method === 'POST' && apiPath === '/firing/stop') {
      stopFiring();
      return json(res, { ok: true });
    }

    // POST /firing/pause
    if (method === 'POST' && apiPath === '/firing/pause') {
      const action = pauseFiring();
      return json(res, { ok: true, action });
    }

    // POST /firing/skip-segment
    if (method === 'POST' && apiPath === '/firing/skip-segment') {
      // Advance segment index in simulator
      const f = state.firing;
      if (f.running && f.profile) {
        f.currentSegmentIndex = Math.min(
          f.currentSegmentIndex + 1,
          f.profile.segments.length - 1
        );
        f.phase = 'ramping';
        f.segmentElapsed = 0;
        f.holdElapsed = 0;
        f.segmentStartTemp = f.currentTemp;
      }
      return json(res, { ok: true });
    }

    // GET /history
    if (method === 'GET' && apiPath === '/history') {
      return json(res, mockHistory);
    }

    // GET /history/:id/trace
    const historyTraceMatch = apiPath.match(/^\/history\/(\d+)\/trace$/);
    if (method === 'GET' && historyTraceMatch) {
      const id = parseInt(historyTraceMatch[1], 10);
      const record = mockHistory.find((r) => r.id === id);
      if (!record) return json(res, { error: 'Not found' }, 404);
      const csv = generateTraceCsv(record);
      res.writeHead(200, { 'Content-Type': 'text/csv' });
      res.end(csv);
      return;
    }

    // GET /settings
    if (method === 'GET' && apiPath === '/settings') {
      return json(res, {
        ...state.settings,
        tcOffsetC: (state.settings as any).tcOffsetC ?? 0,
        webhookUrl: (state.settings as any).webhookUrl ?? '',
        apiTokenSet: false,
        elementWatts: (state.settings as any).elementWatts ?? 0,
        electricityCostKwh: (state.settings as any).electricityCostKwh ?? 0,
      });
    }

    // POST /settings
    if (method === 'POST' && apiPath === '/settings') {
      const body = await parseBody(req);
      // Never store the raw api token in state — just note it's been set
      const { apiToken, ...rest } = body;
      Object.assign(state.settings, rest);
      if (apiToken !== undefined) {
        (state.settings as any).apiTokenSet = !!apiToken;
      }
      return json(res, { ok: true });
    }

    // GET /system
    if (method === 'GET' && apiPath === '/system') {
      return json(res, {
        firmware: '2.0.0-mock',
        model: 'Bisque ESP32-S3 (Simulated)',
        uptimeSeconds: Math.round((Date.now() - state.startupTime) / 1000),
        freeHeap: 200000 + Math.round(Math.random() * 10000),
        emergencyStop: false,
        lastErrorCode: 0,
        elementHoursS: 3600 * 42,
        spiffsTotal: 917504,
        spiffsUsed: 204800 + Math.round(Math.random() * 50000),
      });
    }

    // POST /autotune/start
    if (method === 'POST' && apiPath === '/autotune/start') {
      const body = await parseBody(req);
      startAutotune(body.setpoint, body.hysteresis);
      return json(res, { ok: true });
    }

    // POST /autotune/stop
    if (method === 'POST' && apiPath === '/autotune/stop') {
      stopAutotune();
      return json(res, { ok: true });
    }

    // GET /autotune/status
    if (method === 'GET' && apiPath === '/autotune/status') {
      return json(res, getAutotuneStatus());
    }

    // POST /ota
    if (method === 'POST' && apiPath === '/ota') {
      // Simulate upload delay then success
      await new Promise((r) => setTimeout(r, 1000));
      return json(res, { ok: true });
    }

    // POST /diagnostics/relay
    if (method === 'POST' && apiPath === '/diagnostics/relay') {
      const body = await parseBody(req);
      const durationSeconds = body.durationSeconds ?? 2;
      return json(res, { ok: true, durationSeconds });
    }

    // GET /diagnostics/thermocouple
    if (method === 'GET' && apiPath === '/diagnostics/thermocouple') {
      const temp = state.firing.currentTemp;
      return json(res, {
        temperatureC: temp + (Math.random() - 0.5) * 0.5,
        internalTempC: 24.5 + (Math.random() - 0.5),
        fault: false,
        openCircuit: false,
        shortGnd: false,
        shortVcc: false,
        readingAgeMs: Math.round(Math.random() * 250),
        tcOffsetC: (state.settings as any).tcOffsetC ?? 0,
        temperatureAdjustedC: temp + ((state.settings as any).tcOffsetC ?? 0),
      });
    }

    json(res, { error: 'Not found' }, 404);
  } catch (err: any) {
    json(res, { error: err.message }, 500);
  }
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
