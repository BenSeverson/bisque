import { FiringProfile, KilnSettings, ConeEntry, HistoryRecord, WifiInfo } from "../types/kiln";
import { kilnWS } from "./websocket";

const API_BASE = "/api/v1";
const TOKEN_STORAGE_KEY = "bisque.apiToken";

// Persisted in sessionStorage so a page reload doesn't lock the user out, but
// it's still cleared when the browser/tab closes.
let _apiToken: string | null =
  typeof window !== "undefined" ? window.sessionStorage.getItem(TOKEN_STORAGE_KEY) : null;

// Propagate the persisted token to the WS client at module-load time.
if (_apiToken) kilnWS.setAuthToken(_apiToken);

export function setApiToken(token: string | null) {
  _apiToken = token;
  if (typeof window !== "undefined") {
    if (token) window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  }
  kilnWS.setAuthToken(token);
}

export function getApiToken(): string | null {
  return _apiToken;
}

function authHeaders(): Record<string, string> {
  return _apiToken ? { Authorization: `Bearer ${_apiToken}` } : {};
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(),
  };

  const res = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string> | undefined) },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

/** Authenticated fetch that returns the response Blob for download. */
async function fetchBlob(url: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}${url}`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.blob();
}

/** Authenticated fetch that returns response text. */
async function fetchText(url: string): Promise<string> {
  const res = await fetch(`${API_BASE}${url}`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.text();
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
  lastErrorCode: number;
  elementHoursS: number;
  spiffsTotal: number;
  spiffsUsed: number;
  boardTempC: number;
}

export interface AutotuneStatus {
  state: string;
  elapsedTime: number;
  targetTemp: number;
  currentTemp: number;
  currentGains: { kp: number; ki: number; kd: number };
}

export interface OtaCheckResponse {
  current: string;
  latest: string;
  updateAvailable: boolean;
  url: string;
  sha256: string;
  size: number;
  notes: string;
}

export interface OtaStatus {
  running?: { label: string; version?: string; state?: string };
  nextUpdate?: { label: string };
  bootPartition?: string;
  pendingVerify?: boolean;
  rollbackAvailable: boolean;
}

export interface DiagThermocouple {
  temperatureC: number;
  internalTempC: number;
  fault: boolean;
  openCircuit: boolean;
  shortGnd: boolean;
  shortVcc: boolean;
  readingAgeMs: number;
  temperatureAdjustedC: number;
  tcOffsetC: number;
}

export const api = {
  // Status
  getStatus: () => request<StatusResponse>("/status"),

  // Profiles
  getProfiles: () => request<FiringProfile[]>("/profiles"),
  getProfile: (id: string) => request<FiringProfile>(`/profiles/${id}`),
  saveProfile: (profile: FiringProfile) =>
    request<{ ok: boolean; id: string }>("/profiles", {
      method: "POST",
      body: JSON.stringify(profile),
    }),
  deleteProfile: (id: string) => request<{ ok: boolean }>(`/profiles/${id}`, { method: "DELETE" }),
  duplicateProfile: async (profile: FiringProfile) => {
    const copy: FiringProfile = {
      ...profile,
      id: `${profile.id}-copy-${Date.now().toString(36)}`,
      name: `${profile.name} (Copy)`,
    };
    return request<{ ok: boolean; id: string }>("/profiles", {
      method: "POST",
      body: JSON.stringify(copy),
    });
  },
  exportProfile: (id: string) => fetchBlob(`/profiles/${id}/export`),
  importProfile: (profile: FiringProfile) =>
    request<{ ok: boolean; id: string }>("/profiles/import", {
      method: "POST",
      body: JSON.stringify(profile),
    }),

  // Cone fire
  getConeTable: () => request<ConeEntry[]>("/cone-table"),
  generateConeFire: (params: {
    coneId: number;
    speed: number; // 0=slow, 1=medium, 2=fast
    preheat: boolean;
    slowCool: boolean;
    save: boolean;
  }) =>
    request<FiringProfile>("/profiles/cone-fire", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Firing control
  startFiring: (profileId: string, delayMinutes = 0) =>
    request<{ ok: boolean }>("/firing/start", {
      method: "POST",
      body: JSON.stringify({ profileId, delayMinutes }),
    }),
  stopFiring: () => request<{ ok: boolean }>("/firing/stop", { method: "POST" }),
  pauseFiring: () => request<{ ok: boolean; action: string }>("/firing/pause", { method: "POST" }),
  skipSegment: () => request<{ ok: boolean }>("/firing/skip-segment", { method: "POST" }),

  // Settings
  getSettings: () => request<KilnSettings>("/settings"),
  saveSettings: (settings: KilnSettings) =>
    request<{ ok: boolean }>("/settings", {
      method: "POST",
      body: JSON.stringify(settings),
    }),

  // System
  getSystemInfo: () => request<SystemInfo>("/system"),

  // Auto-tune
  startAutotune: (setpoint: number, hysteresis = 5) =>
    request<{ ok: boolean }>("/autotune/start", {
      method: "POST",
      body: JSON.stringify({ setpoint, hysteresis }),
    }),
  stopAutotune: () => request<{ ok: boolean }>("/autotune/stop", { method: "POST" }),
  getAutotuneStatus: () => request<AutotuneStatus>("/autotune/status"),

  // History
  getHistory: () => request<HistoryRecord[]>("/history"),
  getHistoryTrace: (recordId: number) => fetchText(`/history/${recordId}/trace`),
  getHistoryTraceBlob: (recordId: number) => fetchBlob(`/history/${recordId}/trace`),

  // OTA
  uploadOta: async (file: File, onProgress?: (pct: number) => void): Promise<{ ok: boolean }> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/ota`);
      if (_apiToken) {
        xhr.setRequestHeader("Authorization", `Bearer ${_apiToken}`);
      }
      if (onProgress) {
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
        };
      }
      xhr.onload = () => {
        if (xhr.status < 300) resolve(JSON.parse(xhr.responseText));
        else reject(new Error(`OTA error ${xhr.status}: ${xhr.responseText}`));
      };
      xhr.onerror = () => reject(new Error("OTA upload failed"));
      xhr.send(file);
    });
  },
  checkOta: () => request<OtaCheckResponse>("/ota/check", { method: "POST" }),
  installOta: () =>
    request<{ ok: boolean; version: string; message: string }>("/ota/install", { method: "POST" }),
  otaStatus: () => request<OtaStatus>("/ota/status"),

  // Wi-Fi provisioning
  getWifi: () => request<WifiInfo>("/wifi"),
  saveWifi: (ssid: string, password: string) =>
    request<{ ok: boolean; message: string }>("/wifi", {
      method: "POST",
      body: JSON.stringify({ ssid, password }),
    }),
  clearWifi: () => request<{ ok: boolean; message: string }>("/wifi", { method: "DELETE" }),

  // Diagnostics
  testRelay: (durationSeconds = 2) =>
    request<{ ok: boolean; durationSeconds: number }>("/diagnostics/relay", {
      method: "POST",
      body: JSON.stringify({ durationSeconds }),
    }),
  getThermocoupleDiag: () => request<DiagThermocouple>("/diagnostics/thermocouple"),
};
