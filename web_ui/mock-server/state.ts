import type { WebSocketServer } from "ws";
import type { FiringProfile, KilnSettings } from "../src/app/types/kiln";
import { mockProfiles } from "../src/app/data/mockProfiles";
import { AMBIENT } from "./physics";

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
}

export const state = {
  profiles: JSON.parse(JSON.stringify(mockProfiles)) as FiringProfile[],

  settings: {
    tempUnit: "C",
    maxSafeTemp: 1400,
    alarmEnabled: true,
    autoShutdown: true,
    notificationsEnabled: true,
  } as KilnSettings,

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
  } as FiringState,

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
