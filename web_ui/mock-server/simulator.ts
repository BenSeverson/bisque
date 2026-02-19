import { state } from './state';
import { AMBIENT, updateTemperature, coolingTemperature } from './physics';

const speed = () => parseInt(process.env.VITE_MOCK_SPEED || '60', 10);

export function startFiring(profileId: string): boolean {
  const profile = state.profiles.find((p) => p.id === profileId);
  if (!profile) return false;

  // Stop any existing interval
  if (state.interval) {
    clearInterval(state.interval);
    state.interval = null;
  }

  const f = state.firing;
  f.running = true;
  f.paused = false;
  f.coolingDown = false;
  f.profileId = profileId;
  f.profile = profile;
  f.currentSegmentIndex = 0;
  f.phase = 'ramping';
  f.segmentStartTemp = f.currentTemp;
  f.setpoint = f.currentTemp;
  f.simulatedElapsed = 0;
  f.segmentElapsed = 0;
  f.holdElapsed = 0;
  f.status = 'heating';

  state.interval = setInterval(() => tick(), 1000);
  return true;
}

export function stopFiring(): void {
  const f = state.firing;
  f.running = false;
  f.paused = false;
  f.status = 'idle';
  f.profileId = '';
  f.profile = null;
  f.coolingDown = true;

  // Keep interval running for passive cooling
  if (!state.interval) {
    state.interval = setInterval(() => tick(), 1000);
  }
}

export function pauseFiring(): string {
  const f = state.firing;
  if (!f.running) return 'not_active';
  f.paused = !f.paused;
  f.status = f.paused ? 'paused' : determineStatus();
  broadcast();
  return f.paused ? 'paused' : 'resumed';
}

function determineStatus(): string {
  const f = state.firing;
  if (!f.running) return 'idle';
  if (f.paused) return 'paused';
  if (f.phase === 'holding') return 'holding';
  const seg = f.profile!.segments[f.currentSegmentIndex];
  return seg.rampRate < 0 ? 'cooling' : 'heating';
}

function estimateTimeRemaining(): number {
  const f = state.firing;
  if (!f.running || !f.profile) return 0;

  let remaining = 0;
  const segments = f.profile.segments;

  // Current segment
  const seg = segments[f.currentSegmentIndex];
  const rampDelta = Math.abs(seg.targetTemp - f.segmentStartTemp);
  const rampTime =
    seg.rampRate !== 0 ? (rampDelta / Math.abs(seg.rampRate)) * 3600 : 0;

  if (f.phase === 'ramping') {
    remaining += Math.max(0, rampTime - f.segmentElapsed);
    remaining += seg.holdTime * 60;
  } else {
    remaining += Math.max(0, seg.holdTime * 60 - f.holdElapsed);
  }

  // Subsequent segments
  for (let i = f.currentSegmentIndex + 1; i < segments.length; i++) {
    const s = segments[i];
    const startTemp = segments[i - 1].targetTemp;
    const segRampTime =
      s.rampRate !== 0
        ? (Math.abs(s.targetTemp - startTemp) / Math.abs(s.rampRate)) * 3600
        : 0;
    remaining += segRampTime + s.holdTime * 60;
  }

  return remaining;
}

function tick(): void {
  const f = state.firing;
  const dt = speed();

  // Passive cooling after stop/complete
  if (f.coolingDown && !f.running) {
    f.currentTemp = coolingTemperature(f.currentTemp, dt);
    f.setpoint = AMBIENT;
    if (f.currentTemp < AMBIENT + 1) {
      f.currentTemp = AMBIENT;
      f.coolingDown = false;
      if (state.interval) {
        clearInterval(state.interval);
        state.interval = null;
      }
    }
    broadcast();
    return;
  }

  if (!f.running || f.paused || !f.profile) {
    broadcast();
    return;
  }

  f.simulatedElapsed += dt;

  const seg = f.profile.segments[f.currentSegmentIndex];

  if (f.phase === 'ramping') {
    f.segmentElapsed += dt;

    if (seg.rampRate === 0) {
      // Instant ramp — jump to target
      f.setpoint = seg.targetTemp;
      transitionToHoldOrAdvance(seg.holdTime);
    } else {
      f.setpoint =
        f.segmentStartTemp + (seg.rampRate / 3600) * f.segmentElapsed;

      // Clamp to target
      if (seg.rampRate > 0) {
        f.setpoint = Math.min(f.setpoint, seg.targetTemp);
      } else {
        f.setpoint = Math.max(f.setpoint, seg.targetTemp);
      }

      // Check if setpoint reached target
      if (Math.abs(f.setpoint - seg.targetTemp) < 0.1) {
        f.setpoint = seg.targetTemp;
        transitionToHoldOrAdvance(seg.holdTime);
      }
    }
  } else {
    // Holding
    f.holdElapsed += dt;
    f.setpoint = seg.targetTemp;

    if (f.holdElapsed >= seg.holdTime * 60) {
      advanceSegment();
    }
  }

  // Update temperature via physics model
  f.currentTemp = updateTemperature(f.currentTemp, f.setpoint, dt);
  f.status = determineStatus();

  broadcast();
}

function transitionToHoldOrAdvance(holdTime: number): void {
  const f = state.firing;
  if (holdTime > 0) {
    f.phase = 'holding';
    f.holdElapsed = 0;
  } else {
    advanceSegment();
  }
}

function advanceSegment(): void {
  const f = state.firing;
  if (!f.profile) return;

  f.currentSegmentIndex++;
  if (f.currentSegmentIndex >= f.profile.segments.length) {
    // Firing complete
    f.running = false;
    f.status = 'complete';
    f.coolingDown = true;
    return;
  }

  f.phase = 'ramping';
  f.segmentStartTemp = f.currentTemp;
  f.setpoint = f.currentTemp;
  f.segmentElapsed = 0;
  f.holdElapsed = 0;
}

function broadcast(): void {
  const f = state.firing;
  if (!state.wss) return;

  const msg = JSON.stringify({
    type: 'temp_update',
    data: {
      currentTemp: Math.round(f.currentTemp * 10) / 10,
      targetTemp: Math.round(f.setpoint * 10) / 10,
      status: f.status,
      currentSegment: f.currentSegmentIndex,
      totalSegments: f.profile?.segments.length ?? 0,
      elapsedTime: Math.round(f.simulatedElapsed),
      estimatedTimeRemaining: Math.round(estimateTimeRemaining()),
      isActive: f.running,
    },
  });

  for (const client of state.wss.clients) {
    if (client.readyState === 1 /* OPEN */) {
      client.send(msg);
    }
  }
}

export function getStatusResponse() {
  const f = state.firing;
  return {
    isActive: f.running,
    profileId: f.profileId || '',
    currentTemp: Math.round(f.currentTemp * 10) / 10,
    targetTemp: Math.round(f.setpoint * 10) / 10,
    currentSegment: f.currentSegmentIndex,
    totalSegments: f.profile?.segments.length ?? 0,
    elapsedTime: Math.round(f.simulatedElapsed),
    estimatedTimeRemaining: Math.round(estimateTimeRemaining()),
    status: f.status,
    thermocouple: {
      temperature: Math.round(f.currentTemp * 10) / 10,
      internalTemp: 25 + Math.random() * 5,
      fault: false,
      openCircuit: false,
      shortGnd: false,
      shortVcc: false,
    },
  };
}
