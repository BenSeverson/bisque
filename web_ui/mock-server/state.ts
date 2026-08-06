import type { WebSocketServer } from "ws";
import type { FiringProfile, HistoryRecord, KilnSettings } from "../src/app/types/kiln";
import { mockProfiles } from "../src/app/data/mockProfiles";
import { AMBIENT } from "./physics";

/** Mirrors HISTORY_MAX_RECORDS in components/history/include/firing_history.h. */
export const HISTORY_MAX_RECORDS = 20;

/** Mirrors `firing_error_code_t` (components/firing_engine/include/firing_types.h). */
export const FIRING_ERR = {
  NONE: 0,
  TC_FAULT: 1,
  OVER_TEMP: 2,
  NOT_RISING: 3,
  RUNAWAY: 4,
  EMERGENCY_STOP: 5,
  INVALID_PROFILE: 6,
} as const;

const nowS = () => Math.floor(Date.now() / 1000);

/**
 * Seeded history, newest first — the order `history_get_records()` returns,
 * since `history_firing_end()` prepends. The mock used to list them oldest
 * first, which is not what a device shows.
 *
 * One record is a real failure. Every seeded record used to carry
 * `errorCode: 0`, so the history detail's cause line (#235) was dead code in
 * dev, in the tests, and in the published demo (#239).
 */
const seedHistory = (): HistoryRecord[] => [
  {
    id: 4,
    startTime: nowS() - 3600 * 2,
    profileName: "Custom Test",
    profileId: "custom-test",
    peakTemp: 850,
    durationS: 5400,
    outcome: "aborted",
    errorCode: FIRING_ERR.NONE,
  },
  {
    id: 3,
    startTime: nowS() - 3600 * 8,
    profileName: "Glaze Cone 6",
    profileId: "glaze-6",
    peakTemp: 1043,
    durationS: 12600,
    outcome: "error",
    errorCode: FIRING_ERR.TC_FAULT,
  },
  {
    id: 2,
    startTime: nowS() - 86400,
    profileName: "Glaze Cone 6",
    profileId: "glaze-6",
    peakTemp: 1222,
    durationS: 21600,
    outcome: "complete",
    errorCode: FIRING_ERR.NONE,
  },
  {
    id: 1,
    startTime: nowS() - 86400 * 3,
    profileName: "Bisque Cone 04",
    profileId: "bisque-04",
    peakTemp: 1063,
    durationS: 14400,
    outcome: "complete",
    errorCode: FIRING_ERR.NONE,
  },
];

export interface FiringState {
  running: boolean;
  paused: boolean;
  coolingDown: boolean;
  /** Armed delayed start: firmware reports is_active=true with status "idle"
   *  while this counts down, which is the state the dashboard renders as
   *  "Scheduled". The simulator previously ignored delayMinutes and fired
   *  immediately, so that state was unreachable in dev and in the demo. */
  scheduled: boolean;
  delayRemainingS: number;
  profileId: string;
  profile: FiringProfile | null;
  currentSegmentIndex: number;
  phase: "ramping" | "holding";
  currentTemp: number;
  setpoint: number;
  simulatedElapsed: number;
  segmentStartTemp: number;
  segmentElapsed: number;
  holdElapsed: number;
  status: string;
  /** Running peak, mirroring s_state.peak_temp_c — goes into the history record. */
  peakTemp: number;
  /** Unix seconds the current firing began; 0 when nothing has begun.
   *  Doubles as "a history record is open", the mock's `s_recording`. */
  startedAtS: number;
  /** Name captured at start, so a record survives the profile being edited. */
  profileName: string;
}

export interface AutotuneState {
  running: boolean;
  setpoint: number;
  hysteresis: number;
  currentTemp: number;
  startTime: number;
  elapsed: number;
  gains: { kp: number; ki: number; kd: number };
  interval: ReturnType<typeof setInterval> | null;
  completed: boolean;
  /** Relay state of the bang-bang tuning output, mirroring `at->relay_on` in
   *  pid_autotune_update(). Latched: it only flips outside setpoint ±
   *  hysteresis, so it has to be state rather than a function of the reading. */
  relayOn: boolean;
}

export const state = {
  profiles: JSON.parse(JSON.stringify(mockProfiles)) as FiringProfile[],

  settings: {
    tempUnit: "C",
    maxSafeTemp: 1400,
    alarmEnabled: true,
    autoShutdown: true,
    notificationsEnabled: true,
    elementWatts: 5000,
    electricityCostKwh: 0.15,
    lidMode: "pause",
  } as KilnSettings,

  /* Lid/door interlock switch position. The simulated kiln always has one
     fitted — real firmware omits `lidOpen` entirely when
     CONFIG_KILN_PIN_LID_SWITCH is -1, and the mock cannot model both. A demo
     that can show the indicator is the more useful of the two, exactly as with
     ventActive; the absent case is covered by the `status_no_lid` firmware
     fixture. Toggled from the dev-only POST /lid route in router.ts. */
  lidOpen: false,

  firing: {
    running: false,
    paused: false,
    coolingDown: false,
    scheduled: false,
    delayRemainingS: 0,
    profileId: "",
    profile: null,
    currentSegmentIndex: 0,
    phase: "ramping",
    currentTemp: AMBIENT,
    setpoint: AMBIENT,
    simulatedElapsed: 0,
    segmentStartTemp: AMBIENT,
    segmentElapsed: 0,
    holdElapsed: 0,
    status: "idle",
    peakTemp: AMBIENT,
    startedAtS: 0,
    profileName: "",
  } as FiringState,

  /** Newest first, like history_get_records(). */
  history: seedHistory(),
  nextHistoryId: 5,

  /** `safety_is_emergency()` — latched until the next successful start. */
  emergencyStop: false,
  /** `firing_engine_get_error_code()` — outlives the firing that set it. */
  lastErrorCode: FIRING_ERR.NONE as number,

  autotune: {
    running: false,
    setpoint: 0,
    hysteresis: 5,
    currentTemp: AMBIENT,
    startTime: 0,
    elapsed: 0,
    gains: { kp: 2.0, ki: 0.5, kd: 1.0 },
    interval: null,
    completed: false,
    relayOn: false,
  } as AutotuneState,

  wifi: {
    connected: true,
    apMode: false,
    ip: "192.168.1.50",
    savedSsid: "HomeNetwork" as string | undefined,
  },

  wss: null as WebSocketServer | null,
  interval: null as ReturnType<typeof setInterval> | null,
  startupTime: Date.now(),

  // Simulation speed multiplier (real-seconds per tick). Node adapters set this
  // from VITE_MOCK_SPEED/MOCK_SPEED; the browser demo sets it in installDemo().
  speed: 60,

  // Transport-agnostic broadcast fan-out. Each subscriber receives the
  // already-serialized WS message string. The Node adapters register a
  // subscriber that forwards to wss.clients; the browser demo registers one
  // that feeds its in-page fake WebSocket. This is what lets a single
  // simulator core drive the dev server, the iOS standalone mock, and the
  // serverless GitHub Pages demo.
  subscribers: new Set<(msg: string) => void>(),
};
