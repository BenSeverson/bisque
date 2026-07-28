import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";
import { FiringProfile, KilnSettings } from "../types/kiln";
import { useKilnStore } from "../stores/kilnStore";
import { TempUnit } from "../utils/temperature";

export const DEFAULT_SETTINGS: KilnSettings = {
  tempUnit: "F",
  maxSafeTemp: 1400,
  alarmEnabled: true,
  autoShutdown: true,
  notificationsEnabled: true,
  tcOffsetC: 0,
  webhookUrl: "",
  apiTokenSet: false,
  elementWatts: 0,
  electricityCostKwh: 0,
};

// Query keys
export const queryKeys = {
  profiles: ["profiles"] as const,
  settings: ["settings"] as const,
  systemInfo: ["systemInfo"] as const,
  autotuneStatus: ["autotuneStatus"] as const,
  history: ["history"] as const,
  coneTable: ["coneTable"] as const,
  thermocoupleDiag: ["thermocoupleDiag"] as const,
  wifi: ["wifi"] as const,
};

// --- Queries ---

export function useProfiles() {
  // Deliberately no catch. Substituting the five bundled demo profiles on any
  // failure made a 401 (the API-token lockout) or a transient network error look
  // like a successful fetch, so the user's own saved profiles appeared to have
  // vanished and been replaced by ones they never created (#135). Both the dev
  // server and the demo build serve real profiles from the mock kiln, so the
  // bundled fallback bought nothing that hiding errors did not cost more.
  return useQuery({
    queryKey: queryKeys.profiles,
    queryFn: () => api.getProfiles(),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => api.getSettings(),
    placeholderData: DEFAULT_SETTINGS,
  });
}

/**
 * The active temperature display unit. Convenience wrapper over useSettings()
 * for the many components that only need the unit to format temperatures.
 * Falls back to the default until settings load.
 */
export function useTempUnit(): TempUnit {
  const { data } = useSettings();
  return data?.tempUnit ?? DEFAULT_SETTINGS.tempUnit;
}

export function useSystemInfo() {
  return useQuery({
    queryKey: queryKeys.systemInfo,
    queryFn: () => api.getSystemInfo(),
    retry: false,
  });
}

export function useAutotuneStatus(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.autotuneStatus,
    queryFn: () => api.getAutotuneStatus(),
    refetchInterval: enabled ? 2000 : false,
    // React Query pauses interval refetches in a hidden tab by default, so
    // switching away for the length of a tune meant the terminal frame was
    // never observed and the run came back "unconfirmed" (#217). Auto-tune is
    // bounded and user-initiated, and only polls while `enabled`, so keeping it
    // running in the background is cheap; other queries keep the default.
    refetchIntervalInBackground: true,
    retry: false,
  });
}

export function useHistory() {
  return useQuery({
    queryKey: queryKeys.history,
    queryFn: () => api.getHistory(),
    retry: false,
  });
}

export function useConeTable() {
  return useQuery({
    queryKey: queryKeys.coneTable,
    queryFn: () => api.getConeTable(),
    retry: false,
    staleTime: Infinity,
  });
}

export function useWifi() {
  return useQuery({
    queryKey: queryKeys.wifi,
    queryFn: () => api.getWifi(),
    refetchInterval: 10000,
    retry: false,
  });
}

// --- Mutations ---

export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: FiringProfile) => api.saveProfile(profile),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
  });
}

export function useDeleteProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profileId: string) => api.deleteProfile(profileId),
    onSuccess: (_data, profileId) => {
      /* Read the store here instead of subscribing to it. A selector-less
         `useKilnStore()` subscribes to the whole state object, which is
         replaced on every temp_update frame (~1 Hz during a firing), so every
         consumer of this hook re-rendered once a second for the length of a
         firing — including ProfileBuilder, which App.tsx force-mounts to keep
         a half-typed profile alive across tab switches (#162). getState() also
         reads the selection at delete time rather than closing over the value
         from the render that created the mutation. */
      const { selectedProfileId, setSelectedProfileId } = useKilnStore.getState();
      if (selectedProfileId === profileId) setSelectedProfileId(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
  });
}

export function useDuplicateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: FiringProfile) => api.duplicateProfile(profile),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
  });
}

export function useImportProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: FiringProfile) => api.importProfile(profile),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
  });
}

export function useGenerateConeFire() {
  return useMutation({
    mutationFn: (params: {
      coneId: number;
      speed: number;
      preheat: boolean;
      slowCool: boolean;
      save: boolean;
    }) => api.generateConeFire(params),
  });
}

export function useSaveSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: KilnSettings) => api.saveSettings(settings),
    onMutate: async (newSettings) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.settings });
      const previous = queryClient.getQueryData<KilnSettings>(queryKeys.settings);
      queryClient.setQueryData(queryKeys.settings, newSettings);
      return { previous };
    },
    onError: (_err, _new, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.settings, context.previous);
      }
    },
  });
}

export function useSaveWifi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ssid, password }: { ssid: string; password: string }) =>
      api.saveWifi(ssid, password),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.wifi });
    },
  });
}

export function useReboot() {
  return useMutation({
    mutationFn: () => api.reboot(),
  });
}

export function useClearWifi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.clearWifi(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.wifi });
    },
  });
}

export function useStartFiring() {
  return useMutation({
    mutationFn: ({ profileId, delayMinutes = 0 }: { profileId: string; delayMinutes?: number }) =>
      api.startFiring(profileId, delayMinutes),
  });
}

export function useStopFiring() {
  return useMutation({
    mutationFn: () => api.stopFiring(),
  });
}

export function usePauseFiring() {
  return useMutation({
    mutationFn: () => api.pauseFiring(),
  });
}

export function useSkipSegment() {
  return useMutation({
    mutationFn: () => api.skipSegment(),
  });
}

export function useStartAutotune() {
  return useMutation({
    mutationFn: (setpoint: number) => api.startAutotune(setpoint),
  });
}

export function useStopAutotune() {
  return useMutation({
    mutationFn: () => api.stopAutotune(),
  });
}

export function useTestRelay() {
  return useMutation({
    mutationFn: () => api.testRelay(2),
  });
}

export function useUploadOta() {
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress?: (pct: number) => void }) =>
      api.uploadOta(file, onProgress),
  });
}

export function useCheckOta() {
  return useMutation({
    mutationFn: () => api.checkOta(),
  });
}

export function useInstallOta() {
  return useMutation({
    mutationFn: () => api.installOta(),
  });
}
