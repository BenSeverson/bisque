import type { WebSocketServer } from 'ws';
import type { FiringProfile, KilnSettings } from '../src/app/types/kiln';
import { mockProfiles } from '../src/app/data/mockProfiles';
import { AMBIENT } from './physics';

export interface FiringState {
  running: boolean;
  paused: boolean;
  coolingDown: boolean;
  profileId: string;
  profile: FiringProfile | null;
  currentSegmentIndex: number;
  phase: 'ramping' | 'holding';
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
    tempUnit: 'C',
    maxSafeTemp: 1400,
    alarmEnabled: true,
    autoShutdown: true,
    notificationsEnabled: true,
  } as KilnSettings,

  firing: {
    running: false,
    paused: false,
    coolingDown: false,
    profileId: '',
    profile: null,
    currentSegmentIndex: 0,
    phase: 'ramping',
    currentTemp: AMBIENT,
    setpoint: AMBIENT,
    simulatedElapsed: 0,
    segmentStartTemp: AMBIENT,
    segmentElapsed: 0,
    holdElapsed: 0,
    status: 'idle',
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

  wss: null as WebSocketServer | null,
  interval: null as ReturnType<typeof setInterval> | null,
  startupTime: Date.now(),
};
