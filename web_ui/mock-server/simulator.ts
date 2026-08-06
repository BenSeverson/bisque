import { state, FIRING_ERR, HISTORY_MAX_RECORDS } from "./state";
import { AMBIENT, updateTemperature, coolingTemperature, elementDuty } from "./physics";
import { HOLD_UNTIL_SKIP } from "../src/app/types/kiln";
import type { HistoryRecord } from "../src/app/types/kiln";

const speed = () => state.speed;

/**
 * Close out the open history record, mirroring `history_firing_end()`.
 *
 * The firmware writes a record on every terminal transition — complete,
 * aborted, and error alike — and prepends it, capping at HISTORY_MAX_RECORDS.
 * The mock used to serve a frozen three-record list, so a firing you ran in the
 * demo left no trace and the error outcome was unreachable (#239).
 *
 * `startedAtS` stands in for the firmware's `s_recording`: it is only set in
 * beginFiring(), so an armed-but-never-started delayed firing records nothing,
 * matching the early return in history_firing_end().
 */
function recordHistoryEnd(outcome: HistoryRecord["outcome"], errorCode: number): void {
  const f = state.firing;
  if (f.startedAtS === 0) return;

  state.history.unshift({
    id: state.nextHistoryId++,
    startTime: f.startedAtS,
    profileName: f.profileName,
    profileId: f.profileId,
    peakTemp: Math.round(f.peakTemp),
    durationS: Math.round(f.simulatedElapsed),
    outcome,
    errorCode,
  });
  state.history.length = Math.min(state.history.length, HISTORY_MAX_RECORDS);
  f.startedAtS = 0;
}

/**
 * Start the 1 Hz telemetry ticker.
 *
 * The firmware broadcasts a temp_update every second unconditionally
 * (`esp_timer_start_periodic(ws_timer, 1000000)` in main.c) — including while
 * idle. The simulator previously only ticked during a firing, so an idle kiln
 * sent nothing and the UI could not distinguish "idle" from "device gone",
 * which made the connection banner fire a permanent false alarm in dev and in
 * the published demo.
 */
export function ensureTicking(): void {
  if (!state.interval) {
    state.interval = setInterval(() => tick(), 1000);
  }
}

export function startFiring(profileId: string, delayMinutes = 0): boolean {
  const profile = state.profiles.find((p) => p.id === profileId);
  if (!profile) return false;

  // A START releases any latched trip (safety_clear_emergency(),
  // firing_engine.c:858) and clears the recorded cause
  // (s_last_error_code = FIRING_ERR_NONE, :925) — for a delayed arm too. This
  // is the *only* way out of an emergency stop, which is what the Settings copy
  // added in #235 tells the operator.
  state.emergencyStop = false;
  state.lastErrorCode = FIRING_ERR.NONE;

  const f0 = state.firing;
  if (delayMinutes > 0) {
    // Arm only. Mirrors the firmware, which reports is_active=true with an
    // IDLE status until the delay expires.
    f0.scheduled = true;
    f0.delayRemainingS = delayMinutes * 60;
    f0.profileId = profileId;
    f0.profile = profile;
    f0.running = false;
    f0.paused = false;
    f0.coolingDown = false;
    f0.status = "idle";
    f0.simulatedElapsed = 0;
    f0.currentSegmentIndex = 0;
    ensureTicking();
    return true;
  }
  return beginFiring(profileId);
}

function beginFiring(profileId: string): boolean {
  const profile = state.profiles.find((p) => p.id === profileId);
  if (!profile) return false;

  const f = state.firing;
  f.scheduled = false;
  f.delayRemainingS = 0;
  f.running = true;
  f.paused = false;
  f.coolingDown = false;
  f.profileId = profileId;
  f.profile = profile;
  f.currentSegmentIndex = 0;
  f.phase = "ramping";
  f.segmentStartTemp = f.currentTemp;
  f.setpoint = f.currentTemp;
  f.simulatedElapsed = 0;
  f.segmentElapsed = 0;
  f.holdElapsed = 0;
  f.status = "heating";
  f.peakTemp = f.currentTemp;
  f.profileName = profile.name;
  f.startedAtS = Math.floor(Date.now() / 1000);

  ensureTicking();
  return true;
}

export function stopFiring(): void {
  const f = state.firing;
  const wasScheduled = f.scheduled;
  recordHistoryEnd("aborted", FIRING_ERR.NONE);
  f.scheduled = false;
  f.delayRemainingS = 0;
  f.running = false;
  f.paused = false;
  f.status = "idle";
  f.profileId = "";
  f.profile = null;
  f.coolingDown = !wasScheduled; // an armed-but-unstarted firing never heated

  // Keep interval running for passive cooling
  if (!state.interval) {
    state.interval = setInterval(() => tick(), 1000);
  }
}

/**
 * Skip to the next segment, mirroring FIRING_CMD_SKIP_SEGMENT in
 * firing_engine.c.
 *
 * The router used to clamp with `Math.min(idx + 1, len - 1)`, so a skip on the
 * final segment was a no-op. The firmware completes the firing instead — which
 * makes a HOLD_UNTIL_SKIP final segment, the exact case Skip exists for,
 * unfinishable in the demo (#131). The paused and scheduled guards come from the
 * same handler: skipping while paused would re-energize the elements without
 * going through RESUME, and no segment is running yet during an armed delay.
 */
export function skipSegment(): void {
  const f = state.firing;
  if (f.scheduled) return;
  if (!f.running || !f.profile) return;
  if (f.paused) return;

  if (f.currentSegmentIndex + 1 >= f.profile.segments.length) {
    f.running = false;
    f.status = "complete";
    f.coolingDown = true;
    recordHistoryEnd("complete", FIRING_ERR.NONE);
    return;
  }

  f.currentSegmentIndex++;
  f.phase = "ramping";
  f.segmentElapsed = 0;
  f.holdElapsed = 0;
  f.segmentStartTemp = f.currentTemp;
  f.status = determineStatus();
}

export function pauseFiring(): string {
  const f = state.firing;
  if (!f.running) return "not_active";
  f.paused = !f.paused;
  f.status = f.paused ? "paused" : determineStatus();
  broadcast();
  return f.paused ? "paused" : "resumed";
}

/** Set the paused flag to a specific value rather than toggling it.
 *
 *  pauseFiring() is a toggle because POST /firing/pause is one; the lid policy
 *  needs "paused because the lid is up" to track the switch, where a toggle
 *  would invert on a repeated open. */
export function setFiringPaused(paused: boolean): void {
  const f = state.firing;
  if (!f.running || f.paused === paused) return;
  f.paused = paused;
  f.status = paused ? "paused" : determineStatus();
  broadcast();
}

function determineStatus(): string {
  const f = state.firing;
  if (!f.running) return "idle";
  if (f.paused) return "paused";
  if (f.phase === "holding") return "holding";
  const seg = f.profile!.segments[f.currentSegmentIndex];
  return seg.rampRate < 0 ? "cooling" : "heating";
}

/** Hold length in seconds, treating HOLD_UNTIL_SKIP as unknown (0).
 *  The sentinel is "hold until the operator skips", not a 65,535-minute hold;
 *  counting it verbatim produced ETAs around 45 days. Mirrors
 *  computeSegmentDurationMinutes in the client. */
function holdSeconds(holdTime: number): number {
  return holdTime === HOLD_UNTIL_SKIP ? 0 : holdTime * 60;
}

function estimateTimeRemaining(): number {
  const f = state.firing;
  if (!f.running || !f.profile) return 0;

  let remaining = 0;
  const segments = f.profile.segments;

  // Current segment
  const seg = segments[f.currentSegmentIndex];
  const rampDelta = Math.abs(seg.targetTemp - f.segmentStartTemp);
  const rampTime = seg.rampRate !== 0 ? (rampDelta / Math.abs(seg.rampRate)) * 3600 : 0;

  if (f.phase === "ramping") {
    remaining += Math.max(0, rampTime - f.segmentElapsed);
    remaining += holdSeconds(seg.holdTime);
  } else {
    remaining += Math.max(0, holdSeconds(seg.holdTime) - f.holdElapsed);
  }

  // Subsequent segments
  for (let i = f.currentSegmentIndex + 1; i < segments.length; i++) {
    const s = segments[i];
    const startTemp = segments[i - 1].targetTemp;
    const segRampTime =
      s.rampRate !== 0 ? (Math.abs(s.targetTemp - startTemp) / Math.abs(s.rampRate)) * 3600 : 0;
    remaining += segRampTime + holdSeconds(s.holdTime);
  }

  return remaining;
}

function tick(): void {
  const f = state.firing;
  const dt = speed();

  if (f.scheduled) {
    f.delayRemainingS = Math.max(0, f.delayRemainingS - dt);
    if (f.delayRemainingS === 0) {
      beginFiring(f.profileId);
    }
    broadcast();
    return;
  }

  // Passive cooling after stop/complete
  if (f.coolingDown && !f.running) {
    f.currentTemp = coolingTemperature(f.currentTemp, dt);
    f.setpoint = AMBIENT;
    if (f.currentTemp < AMBIENT + 1) {
      f.currentTemp = AMBIENT;
      f.coolingDown = false;
      // Keep ticking: the device keeps broadcasting when idle, and stopping
      // here would make the UI treat a healthy idle kiln as disconnected.
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

  if (f.phase === "ramping") {
    f.segmentElapsed += dt;

    if (seg.rampRate === 0) {
      // Instant ramp — jump to target
      f.setpoint = seg.targetTemp;
      transitionToHoldOrAdvance(seg.holdTime);
    } else {
      f.setpoint = f.segmentStartTemp + (seg.rampRate / 3600) * f.segmentElapsed;

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

    // An indefinite hold ends only when the operator skips, as the firmware
    // requires (firing_engine.c: FIRING_HOLD_INDEFINITE waits for
    // SKIP_SEGMENT). Comparing against the raw sentinel would quietly advance
    // the demo after 65,535 simulated minutes — about 18 hours at the default
    // 60x speed — without anyone pressing Skip.
    if (seg.holdTime !== HOLD_UNTIL_SKIP && f.holdElapsed >= seg.holdTime * 60) {
      advanceSegment();
    }
  }

  // Update temperature via physics model
  f.currentTemp = updateTemperature(f.currentTemp, f.setpoint, dt);
  if (f.currentTemp > f.peakTemp) f.peakTemp = f.currentTemp;

  if (f.running) {
    f.status = determineStatus();
  } else {
    // The segment logic above finished the firing. Close the record here, not
    // inside advanceSegment(), so this tick's reading is folded in first —
    // complete_firing() is called with s_state.peak_temp_c as of the current
    // loop iteration, and recording a tick early under-reports the peak of a
    // no-hold final ramp.
    //
    // determineStatus() is also skipped deliberately: it answers "idle" for
    // anything not running, so calling it here overwrote the "complete" that
    // advanceSegment() had just set. Skip-to-complete returns before reaching
    // this line, which is why that path alone ever showed the status.
    recordHistoryEnd("complete", FIRING_ERR.NONE);
  }

  broadcast();
}

/**
 * Trip a safety fault, the way `firing_loop()` handles `safety_is_emergency()`.
 *
 * There is no firmware endpoint behind this — a real kiln fails on its own, and
 * a simulated one has to be told to. Without it none of the error UI (#235) was
 * reachable in `npm run dev`, in Vitest, or in the published demo (#239);
 * verifying it meant stubbing `window.fetch` in the browser by hand.
 *
 * The outcomes match firing_engine.c, and turn on `s_progress.is_active` —
 * which an auto-tune raises too (FIRING_CMD_AUTOTUNE_START, :1107):
 *  - firing in progress → status ERROR, elements off, an `error` history record
 *    carrying the code, and the kiln cools passively (:1240-1262)
 *  - auto-tune running → the same ERROR branch and the same recorded cause, but
 *    no history record: history_firing_start() runs only in begin_firing(), so
 *    history_firing_end() returns early on `!s_recording`
 *  - delayed start armed → the arm is cancelled with no history record, since
 *    none was ever opened (:1169-1184)
 *  - idle → the trip latches with no recorded cause, which is the one case the
 *    "start a firing to clear it" copy is accurate for
 */
export function tripFault(code: number): void {
  const f = state.firing;
  const at = state.autotune;
  const wasActive = f.running || f.scheduled || at.running;
  const wasFiring = f.running;

  state.emergencyStop = true;
  f.scheduled = false;
  f.delayRemainingS = 0;

  // On the device the emergency branch returns before the tune is stepped, so
  // it simply stops progressing. Here the tune is a separate interval that
  // would otherwise keep heating and rewriting the status to "autotune" every
  // second, overwriting the error the operator just asked for.
  if (at.running) {
    at.running = false;
    if (at.interval) {
      clearInterval(at.interval);
      at.interval = null;
    }
  }

  if (wasActive) {
    // Matches the firmware's precedence: NOT_RISING/RUNAWAY assign their code
    // before tripping, so an already-recorded cause is never overwritten.
    if (state.lastErrorCode === FIRING_ERR.NONE) state.lastErrorCode = code;
    f.running = false;
    f.paused = false;
    // is_active goes false while the status latches on ERROR — the pair the
    // dashboard banner keys off.
    f.status = "error";
  }
  // An idle kiln keeps its idle status and records no cause: both assignments
  // live under `if (s_progress.is_active)`, and s_last_error_code is only ever
  // written inside the firing loop. The trip is still visible — as the bare
  // emergencyStop flag Settings renders, which is the one case where "start a
  // firing to clear it" is the whole truth.
  if (wasFiring) {
    recordHistoryEnd("error", state.lastErrorCode);
  }
  // Either way the elements are off and the kiln is hot — hand it to the
  // passive-cooling tick, as stopAutotune() already does for a cancelled tune.
  if (wasActive) {
    f.coolingDown = true;
  }

  ensureTicking();
}

function transitionToHoldOrAdvance(holdTime: number): void {
  const f = state.firing;
  if (holdTime > 0) {
    f.phase = "holding";
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
    f.status = "complete";
    f.coolingDown = true;
    // tick() writes the record, once this tick's reading has been folded in.
    return;
  }

  f.phase = "ramping";
  f.segmentStartTemp = f.currentTemp;
  f.setpoint = f.currentTemp;
  f.segmentElapsed = 0;
  f.holdElapsed = 0;
}

/**
 * The published temperature, offset-corrected the way the firmware does it.
 *
 * `build_status_json` (api_json.c) and the WS broadcast both add tcOffsetC to
 * the top-level `currentTemp` while leaving `thermocouple.temperature` raw. The
 * simulator never referenced the setting, so changing the thermocouple offset in
 * the demo visibly did nothing on the dashboard even though the diagnostics
 * endpoint applied it correctly (#166).
 */
function publishedTemp(): number {
  const raw = state.firing.currentTemp + (state.settings.tcOffsetC ?? 0);
  return Math.round(raw * 10) / 10;
}

/**
 * Element power as the firmware publishes it: whole percent, and 0 whenever the
 * SSR is not being driven.
 *
 * The firmware reports safety_get_ssr_duty(), i.e. what is actually applied to
 * the element — and firing_engine.c calls safety_set_ssr(0) on every path that
 * isn't an active control tick (paused, armed-but-not-started, idle, complete,
 * error). Deriving this from the thermal model alone would keep showing power
 * to a kiln that had been stopped.
 *
 * Auto-tune is checked first and separately: it runs on its own interval with
 * state.firing.running still false, and the firmware's tune branch drives the
 * SSR bang-bang (`safety_set_ssr(output)`), not from the firing PID.
 */
function publishedDutyPercent(): number {
  if (state.autotune.running) return state.autotune.relayOn ? 100 : 0;
  const f = state.firing;
  if (!f.running || f.paused || f.scheduled) return 0;
  return Math.round(elementDuty(f.currentTemp, f.setpoint) * 100);
}

/** Vent-off threshold, mirroring VENT_MAX_TEMP_C in components/safety/safety.c. */
const VENT_MAX_TEMP_C = 700;

/**
 * Downdraft vent relay, as safety_update_vent() drives it: on while a firing is
 * active and the kiln is below 700°C, clearing combustion gases through the
 * smoky early hours.
 *
 * The simulated kiln always has a vent fitted, so this never returns undefined.
 * Real firmware omits `ventActive` entirely when CONFIG_KILN_PIN_VENT is -1 —
 * the mock cannot model both, and a demo that shows the indicator is the more
 * useful of the two. The absent case is covered by the `status_no_vent` firmware
 * fixture instead.
 *
 * Note this follows `isActive`, not `running`: firing_engine.c keeps the vent
 * turning while a delayed start is armed.
 */
function publishedVentActive(): boolean {
  const f = state.firing;
  return (f.running || f.scheduled) && f.currentTemp < VENT_MAX_TEMP_C;
}

function broadcast(): void {
  const f = state.firing;
  if (state.subscribers.size === 0) return;

  const msg = JSON.stringify({
    type: "temp_update",
    data: {
      currentTemp: publishedTemp(),
      targetTemp: Math.round(f.setpoint * 10) / 10,
      status: f.status,
      currentSegment: f.currentSegmentIndex,
      totalSegments: f.profile?.segments.length ?? 0,
      elapsedTime: Math.round(f.simulatedElapsed),
      estimatedTimeRemaining: Math.round(estimateTimeRemaining()),
      delayRemaining: Math.round(f.scheduled ? f.delayRemainingS : 0),
      dutyPercent: publishedDutyPercent(),
      ventActive: publishedVentActive(),
      lidOpen: state.lidOpen,
      isActive: f.running || f.scheduled,
      // The firmware includes profileId in every frame; omitting it here meant
      // a client could never adopt a firing started elsewhere.
      profileId: f.profileId || "",
    },
  });

  for (const send of state.subscribers) {
    send(msg);
  }
}

export function getStatusResponse() {
  const f = state.firing;
  return {
    isActive: f.running || f.scheduled,
    profileId: f.profileId || "",
    currentTemp: publishedTemp(),
    targetTemp: Math.round(f.setpoint * 10) / 10,
    currentSegment: f.currentSegmentIndex,
    totalSegments: f.profile?.segments.length ?? 0,
    elapsedTime: Math.round(f.simulatedElapsed),
    estimatedTimeRemaining: Math.round(estimateTimeRemaining()),
    delayRemaining: Math.round(f.scheduled ? f.delayRemainingS : 0),
    dutyPercent: publishedDutyPercent(),
    ventActive: publishedVentActive(),
    lidOpen: state.lidOpen,
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
