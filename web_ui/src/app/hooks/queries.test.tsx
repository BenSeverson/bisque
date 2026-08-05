import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import type { KilnSettings, FiringProfile } from "../types/kiln";
import { withQueryClient } from "../test/queryWrapper";

/**
 * The React Query layer. Most of these hooks are one-line wrappers whose
 * behaviour is React Query's, not ours — what is tested here is the part that
 * is ours: the deliberate *absence* of a profiles fallback (#135), the
 * optimistic write and rollback in useSaveSettings, the cross-store side effect
 * in useDeleteProfile, and useSavePidGains seeding from the response rather
 * than the request.
 */

vi.mock("../services/api", () => ({
  api: {
    getProfiles: vi.fn(),
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    saveProfile: vi.fn(),
    deleteProfile: vi.fn(),
    savePidGains: vi.fn(),
    getPidGains: vi.fn(),
  },
}));

const { api } = await import("../services/api");
const {
  DEFAULT_SETTINGS,
  queryKeys,
  useProfiles,
  useSettings,
  useTempUnit,
  useSaveSettings,
  useSaveProfile,
  useDeleteProfile,
  useSavePidGains,
} = await import("./queries");
const { useKilnStore } = await import("../stores/kilnStore");

const mockApi = vi.mocked(api);

function settings(overrides: Partial<KilnSettings> = {}): KilnSettings {
  return { ...DEFAULT_SETTINGS, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
  useKilnStore.setState({ selectedProfileId: null });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useProfiles (#135)", () => {
  it("returns the device's profiles", async () => {
    const profiles = [{ id: "glaze-6", name: "Glaze 6" }] as FiringProfile[];
    mockApi.getProfiles.mockResolvedValue(profiles);
    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useProfiles(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBe(profiles);
  });

  it("surfaces a failure instead of substituting bundled demo profiles", async () => {
    // The old catch-and-fall-back made a 401 (an API-token lockout) or a
    // transient network error look like a successful fetch, so the user's own
    // saved profiles appeared to have vanished and been replaced by five they
    // never created. An error state is the honest answer.
    mockApi.getProfiles.mockRejectedValue(new Error("API error 401: Unauthorized"));
    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useProfiles(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
    expect(result.current.error?.message).toContain("401");
  });
});

describe("useSettings / useTempUnit", () => {
  it("serves defaults as placeholder data until the device answers", async () => {
    // Every temperature on screen is formatted through the unit, so components
    // must not have to handle an undefined settings object on first paint.
    let resolve!: (v: KilnSettings) => void;
    mockApi.getSettings.mockReturnValue(new Promise<KilnSettings>((r) => (resolve = r)));
    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useSettings(), { wrapper });

    expect(result.current.data).toEqual(DEFAULT_SETTINGS);
    await act(async () => {
      resolve(settings({ tempUnit: "C" }));
    });
    await waitFor(() => expect(result.current.data?.tempUnit).toBe("C"));
  });

  it("follows the saved unit once settings load", async () => {
    mockApi.getSettings.mockResolvedValue(settings({ tempUnit: "C" }));
    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useTempUnit(), { wrapper });
    expect(result.current).toBe("F"); // the placeholder
    await waitFor(() => expect(result.current).toBe("C"));
  });
});

describe("useSaveSettings", () => {
  it("shows the new value before the device has confirmed it", async () => {
    // Switches and selects here save on change. Waiting for the round trip
    // makes them visibly lag the tap, so the cache is written first.
    let resolveSave!: (v: { ok: boolean }) => void;
    mockApi.saveSettings.mockReturnValue(new Promise((r) => (resolveSave = r)));

    const { client, wrapper } = withQueryClient();
    client.setQueryData(queryKeys.settings, settings({ alarmEnabled: true }));
    const { result } = renderHook(() => useSaveSettings(), { wrapper });

    act(() => {
      result.current.mutate(settings({ alarmEnabled: false }));
    });
    await waitFor(() =>
      expect(client.getQueryData<KilnSettings>(queryKeys.settings)?.alarmEnabled).toBe(false),
    );

    await act(async () => {
      resolveSave({ ok: true });
    });
    expect(client.getQueryData<KilnSettings>(queryKeys.settings)?.alarmEnabled).toBe(false);
  });

  it("rolls back to the previous settings when the save fails", async () => {
    // Otherwise the control keeps showing a state the controller never took —
    // and for maxSafeTemp that means the UI claims a safety limit that is not
    // the one being enforced.
    mockApi.saveSettings.mockRejectedValue(new Error("API error 409: Firing in progress"));

    const { client, wrapper } = withQueryClient();
    client.setQueryData(queryKeys.settings, settings({ maxSafeTemp: 1400 }));
    const { result } = renderHook(() => useSaveSettings(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(settings({ maxSafeTemp: 200 })).catch(() => {});
    });

    expect(client.getQueryData<KilnSettings>(queryKeys.settings)?.maxSafeTemp).toBe(1400);
    // And the caller is told, so it can toast rather than silently reverting.
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("has nothing to roll back to when the save beat the first fetch", async () => {
    // The rollback is guarded on `context.previous`, so a save issued before
    // the settings query ever resolved leaves the optimistic value in place
    // rather than substituting a default the device never sent. Documented
    // rather than fixed: the next refetch overwrites it, and inventing a value
    // to "restore" would be worse than keeping the one the user chose.
    mockApi.saveSettings.mockRejectedValue(new Error("boom"));

    const { client, wrapper } = withQueryClient();
    const { result } = renderHook(() => useSaveSettings(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(settings({ maxSafeTemp: 200 })).catch(() => {});
    });

    expect(client.getQueryData<KilnSettings>(queryKeys.settings)?.maxSafeTemp).toBe(200);
  });

  it("leaves the last successful save in place", async () => {
    mockApi.saveSettings.mockResolvedValue({ ok: true });

    const { client, wrapper } = withQueryClient();
    client.setQueryData(queryKeys.settings, settings({ tempUnit: "F" }));
    const { result } = renderHook(() => useSaveSettings(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(settings({ tempUnit: "C" }));
    });
    expect(client.getQueryData<KilnSettings>(queryKeys.settings)?.tempUnit).toBe("C");
  });
});

describe("useDeleteProfile", () => {
  it("clears the selection when the deleted profile was the selected one", async () => {
    // The dashboard resolves segment names through selectedProfileId; a
    // dangling id leaves it rendering a profile that no longer exists.
    useKilnStore.setState({ selectedProfileId: "glaze-6" });
    mockApi.deleteProfile.mockResolvedValue({ ok: true });

    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useDeleteProfile(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("glaze-6");
    });

    expect(useKilnStore.getState().selectedProfileId).toBeNull();
  });

  it("leaves an unrelated selection alone", async () => {
    useKilnStore.setState({ selectedProfileId: "bisque-04" });
    mockApi.deleteProfile.mockResolvedValue({ ok: true });

    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useDeleteProfile(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("glaze-6");
    });

    expect(useKilnStore.getState().selectedProfileId).toBe("bisque-04");
  });

  it("reads the selection at delete time, not at render time", async () => {
    // The hook deliberately uses getState() rather than subscribing, so that
    // ProfileBuilder does not re-render once a second for the length of a
    // firing (#162). That means the value must be read late.
    useKilnStore.setState({ selectedProfileId: null });
    mockApi.deleteProfile.mockResolvedValue({ ok: true });

    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useDeleteProfile(), { wrapper });

    // Selected *after* the mutation object was created.
    useKilnStore.setState({ selectedProfileId: "glaze-6" });
    await act(async () => {
      await result.current.mutateAsync("glaze-6");
    });

    expect(useKilnStore.getState().selectedProfileId).toBeNull();
  });

  it("keeps the selection when the delete fails", async () => {
    useKilnStore.setState({ selectedProfileId: "glaze-6" });
    mockApi.deleteProfile.mockRejectedValue(new Error("API error 409: Firing in progress"));

    const { wrapper } = withQueryClient();
    const { result } = renderHook(() => useDeleteProfile(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("glaze-6").catch(() => {});
    });

    expect(useKilnStore.getState().selectedProfileId).toBe("glaze-6");
  });

  it("refetches the profile list", async () => {
    mockApi.deleteProfile.mockResolvedValue({ ok: true });
    mockApi.getProfiles.mockResolvedValue([]);

    const { client, wrapper } = withQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useDeleteProfile(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("glaze-6");
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.profiles });
  });
});

describe("useSaveProfile", () => {
  it("refetches the profile list on success", async () => {
    mockApi.saveProfile.mockResolvedValue({ ok: true, id: "glaze-6" });
    const { client, wrapper } = withQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSaveProfile(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ id: "glaze-6" } as FiringProfile);
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.profiles });
  });

  it("does not refetch when the save was refused", async () => {
    mockApi.saveProfile.mockRejectedValue(new Error("API error 400: Invalid profile"));
    const { client, wrapper } = withQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSaveProfile(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ id: "glaze-6" } as FiringProfile).catch(() => {});
    });
    expect(invalidate).not.toHaveBeenCalled();
  });
});

describe("useSavePidGains (#182)", () => {
  const submitted = { kp: 12.34567, ki: 0.98765, kd: 4.44444 };
  // NVS holds four decimals, so the controller answers with what it kept —
  // alongside the defaults and limits it serves on every /pid response.
  const stored = {
    kp: 12.3457,
    ki: 0.9877,
    kd: 4.4444,
    defaults: { kp: 10, ki: 1, kd: 5 },
    limits: { min: 0, max: 100 },
  };

  it("caches the gains the controller kept, not the ones submitted", async () => {
    // Echoing the request would show a precision the device is not using, and
    // the next save would submit that phantom value straight back.
    mockApi.savePidGains.mockResolvedValue(stored);
    const { client, wrapper } = withQueryClient();
    const { result } = renderHook(() => useSavePidGains(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(submitted);
    });
    expect(client.getQueryData(queryKeys.pidGains)).toEqual(stored);
  });

  it("refetches auto-tune status, which carries the same gains", async () => {
    mockApi.savePidGains.mockResolvedValue(stored);
    const { client, wrapper } = withQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSavePidGains(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(submitted);
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.autotuneStatus });
  });

  it("leaves the cached gains untouched when the controller refuses", async () => {
    // POST /pid answers 409 while the loop is running, because the integrator
    // wound up under the old Ki. The card must keep showing the live gains.
    mockApi.savePidGains.mockRejectedValue(new Error("API error 409: Firing in progress"));
    const { client, wrapper } = withQueryClient();
    client.setQueryData(queryKeys.pidGains, stored);
    const { result } = renderHook(() => useSavePidGains(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync(submitted).catch(() => {});
    });
    expect(client.getQueryData(queryKeys.pidGains)).toEqual(stored);
  });
});
