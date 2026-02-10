import { FiringProfile, KilnSettings } from '../types/kiln';

const API_BASE = '/api/v1';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

export interface StatusResponse {
  isActive: boolean;
  profileId: string;
  currentTemp: number;
  targetTemp: number;
  currentSegment: number;
  totalSegments: number;
  elapsedTime: number;
  estimatedTimeRemaining: number;
  status: string;
  thermocouple: {
    temperature: number;
    internalTemp: number;
    fault: boolean;
    openCircuit: boolean;
    shortGnd: boolean;
    shortVcc: boolean;
  };
}

export interface SystemInfo {
  firmware: string;
  model: string;
  uptimeSeconds: number;
  freeHeap: number;
  emergencyStop: boolean;
}

export interface AutotuneStatus {
  state: string;
  elapsedTime: number;
  targetTemp: number;
  currentTemp: number;
  currentGains: { kp: number; ki: number; kd: number };
}

export const api = {
  getStatus: () => request<StatusResponse>('/status'),

  getProfiles: () => request<FiringProfile[]>('/profiles'),

  getProfile: (id: string) => request<FiringProfile>(`/profiles/${id}`),

  saveProfile: (profile: FiringProfile) =>
    request<{ ok: boolean; id: string }>('/profiles', {
      method: 'POST',
      body: JSON.stringify(profile),
    }),

  deleteProfile: (id: string) =>
    request<{ ok: boolean }>(`/profiles/${id}`, { method: 'DELETE' }),

  startFiring: (profileId: string) =>
    request<{ ok: boolean }>('/firing/start', {
      method: 'POST',
      body: JSON.stringify({ profileId }),
    }),

  stopFiring: () =>
    request<{ ok: boolean }>('/firing/stop', { method: 'POST' }),

  pauseFiring: () =>
    request<{ ok: boolean; action: string }>('/firing/pause', { method: 'POST' }),

  getSettings: () => request<KilnSettings>('/settings'),

  saveSettings: (settings: KilnSettings) =>
    request<{ ok: boolean }>('/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
    }),

  getSystemInfo: () => request<SystemInfo>('/system'),

  startAutotune: (setpoint: number, hysteresis = 5) =>
    request<{ ok: boolean }>('/autotune/start', {
      method: 'POST',
      body: JSON.stringify({ setpoint, hysteresis }),
    }),

  stopAutotune: () =>
    request<{ ok: boolean }>('/autotune/stop', { method: 'POST' }),

  getAutotuneStatus: () => request<AutotuneStatus>('/autotune/status'),
};
