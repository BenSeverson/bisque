import type {
  AutotuneStatus,
  DeviceLog,
  DiagThermocouple,
  OtaCheckResponse,
  OtaConfirmResponse,
  OtaStatus,
  PidGains,
  PidResponse,
  StatusResponse,
  SystemInfo,
} from "../schemas/api";
import { FiringProfile, KilnSettings, ConeEntry, HistoryRecord, WifiInfo } from "../types/kiln";
import { makeDuplicateProfileId } from "../utils/profile";
import { kilnWS } from "./websocket";

/**
 * The response shapes below are *not* declared here. They are inferred from the
 * zod schemas in ../schemas/api — the same schemas the firmware fixtures and the
 * mock-server are validated against — so a contract change fails the build at
 * every call site instead of drifting silently past it (#176). They are
 * re-exported so consumers keep importing them from the service they come from.
 */
export type {
  AutotuneState,
  AutotuneStatus,
  DeviceLog,
  DiagThermocouple,
  OtaCheckResponse,
  OtaConfirmResponse,
  OtaStatus,
  PidGains,
  PidResponse,
  StatusResponse,
  SystemInfo,
} from "../schemas/api";

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

/**
 * A reply the kiln actually sent, with a status the caller can reason about.
 *
 * The distinction that matters is not which status it was, but that there *was*
 * one: a thrown ApiHttpError proves the controller answered, where a bare Error
 * from a rejected fetch means nothing reached it. The Firmware Partitions card
 * turns on exactly that — a 404 from firmware too old to serve /ota/status says
 * the kiln is up and finished rebooting, while a transport failure says it is
 * still on its way back (#177).
 *
 * The message is unchanged, so anything reading `toErrorMessage(e)` — every
 * toast in the UI — reads what it always did.
 */
export class ApiHttpError extends Error {
  constructor(
    readonly status: number,
    body: string,
  ) {
    super(`API error ${status}: ${body}`);
    this.name = "ApiHttpError";
  }
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
    throw new ApiHttpError(res.status, await res.text());
  }
  return res.json();
}

/** Authenticated fetch that returns the response Blob for download. */
async function fetchBlob(url: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}${url}`, { headers: authHeaders() });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await res.text());
  }
  return res.blob();
}

/** Authenticated fetch that returns response text. */
async function fetchText(url: string): Promise<string> {
  const res = await fetch(`${API_BASE}${url}`, { headers: authHeaders() });
  if (!res.ok) {
    throw new ApiHttpError(res.status, await res.text());
  }
  return res.text();
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
      id: makeDuplicateProfileId(profile.id),
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

  /** Recent controller log lines, for the diagnostics bundle (#189). */
  getLog: () => request<DeviceLog>("/log"),

  // Auto-tune
  startAutotune: (setpoint: number, hysteresis = 5) =>
    request<{ ok: boolean }>("/autotune/start", {
      method: "POST",
      body: JSON.stringify({ setpoint, hysteresis }),
    }),
  stopAutotune: () => request<{ ok: boolean }>("/autotune/stop", { method: "POST" }),
  getAutotuneStatus: () => request<AutotuneStatus>("/autotune/status"),

  // PID gains — the manual alternative to running a tune (#182)
  getPidGains: () => request<PidResponse>("/pid"),
  /** Returns the gains the controller kept, which NVS rounds to 4 decimals. */
  savePidGains: (gains: PidGains) =>
    request<PidResponse>("/pid", { method: "POST", body: JSON.stringify(gains) }),

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
        if (xhr.status >= 300) {
          reject(new Error(`OTA error ${xhr.status}: ${xhr.responseText}`));
          return;
        }
        // A 2xx with a non-JSON body — a captive portal or an interposing proxy
        // page — used to throw synchronously out of onload, so neither settler
        // ever ran and the caller awaited forever with the progress UI stuck at
        // "Uploading firmware..." (#135).
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(
            new Error("OTA upload returned a non-JSON response; the update may not have applied"),
          );
        }
      };
      xhr.onerror = () => reject(new Error("OTA upload failed"));
      xhr.send(file);
    });
  },
  checkOta: () => request<OtaCheckResponse>("/ota/check", { method: "POST" }),
  installOta: () =>
    request<{ ok: boolean; version: string; message: string }>("/ota/install", { method: "POST" }),
  otaStatus: () => request<OtaStatus>("/ota/status"),
  /**
   * Reverts to the previously-booted image (#177).
   *
   * handle_ota_rollback() calls esp_ota_mark_app_invalid_rollback_and_reboot(),
   * so the controller is gone before it can answer: the fetch rejects on a
   * dropped connection far more often than it resolves. Only a real HTTP status
   * — 400 "Rollback not available", 409 while a firing is running, 401 — is a
   * refusal, and those still throw.
   *
   * `acknowledged` is what the browser can honestly say about the rest. A
   * rejected fetch is a `TypeError` whether the kiln died mid-reply (the
   * expected case) or was already unreachable and never received the POST
   * (DNS, refused, no route) — the Fetch spec gives no way to tell those apart,
   * deliberately. So the caller is told which of the two stories it is in
   * rather than being handed a "success" that might be a lie: `true` only when
   * the controller answered.
   */
  rollbackOta: async (): Promise<{ acknowledged: boolean }> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/ota/rollback`, {
        method: "POST",
        headers: authHeaders(),
        /* A captive portal answers by redirecting somewhere that returns 200.
           Following it and reading that as an acknowledgement would credit the
           portal with a rollback the kiln never performed.

           "manual" rather than "error": an error would reject, landing in the
           catch below and reporting the redirect as "the kiln stopped
           answering, expected while it reboots" — a sentence about a kiln that
           was never even reached. Resolving to an opaque response instead lets
           it fall through to the not-from-the-kiln error, which is what
           actually happened. */
        redirect: "manual",
      });
    } catch {
      return { acknowledged: false };
    }
    /* An opaque redirect: status 0, headers stripped, body unreadable. Not the
       kiln — its handler never redirects. */
    if (res.type === "opaqueredirect" || res.status === 0) {
      throw new Error("Rollback was answered by a redirect, not the kiln; nothing was changed");
    }
    if (!res.ok) {
      throw new ApiHttpError(res.status, await res.text());
    }
    /* A 2xx is not enough on its own. Anything on the network that answers this
       address — a portal, a proxy, or whatever took the kiln's DHCP lease while
       the tab sat open — produces one, and "Rolling back" is a claim worth more
       than a status code. The upload path already refuses a non-JSON 2xx for
       the same reason (#135); this additionally wants the kiln's own shape. */
    const body = await res.text();
    let ok: boolean;
    try {
      ok = (JSON.parse(body) as { ok?: unknown }).ok === true;
    } catch {
      ok = false;
    }
    if (!ok) {
      throw new Error("Rollback got a reply that did not come from the kiln; nothing was changed");
    }
    return { acknowledged: true };
  },
  confirmOta: () => request<OtaConfirmResponse>("/ota/confirm", { method: "POST" }),

  // Wi-Fi provisioning
  getWifi: () => request<WifiInfo>("/wifi"),
  saveWifi: (ssid: string, password: string) =>
    request<{ ok: boolean; message: string }>("/wifi", {
      method: "POST",
      body: JSON.stringify({ ssid, password }),
    }),
  clearWifi: () => request<{ ok: boolean; message: string }>("/wifi", { method: "DELETE" }),

  // Reboot the controller (e.g. to apply newly-saved Wi-Fi credentials).
  reboot: () => request<{ ok: boolean; message: string }>("/reboot", { method: "POST" }),

  // Diagnostics
  testRelay: (durationSeconds = 2) =>
    request<{ ok: boolean; durationSeconds: number }>("/diagnostics/relay", {
      method: "POST",
      body: JSON.stringify({ durationSeconds }),
    }),
  getThermocoupleDiag: () => request<DiagThermocouple>("/diagnostics/thermocouple"),

  /**
   * Trip a simulated safety fault. Mock-server only — a real controller has no
   * such route and answers 404, so every call site must be `__DEMO__`-gated.
   *
   * It exists because a kiln that never fails leaves the whole error path
   * (banner, history cause, Last Error, emergency-stop guidance) unreachable in
   * the demo, which is the only place most people will ever see this UI (#239).
   */
  simulateFault: (code: number) =>
    request<{ ok: boolean; lastErrorCode: number; status: string }>("/mock/fault", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
};
