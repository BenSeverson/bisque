import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";
import { FiringProfile, KilnSettings } from "../types/kiln";
import { useKilnStore } from "../stores/kilnStore";
import { mockProfiles } from "../data/mockProfiles";

// Query keys
export const queryKeys = {
  profiles: ["profiles"] as const,
  settings: ["settings"] as const,
  status: ["status"] as const,
  systemInfo: ["systemInfo"] as const,
  autotuneStatus: ["autotuneStatus"] as const,
  history: ["history"] as const,
  coneTable: ["coneTable"] as const,
  thermocoupleDiag: ["thermocoupleDiag"] as const,
};

// --- Queries ---

export function useProfiles() {
  return useQuery({
    queryKey: queryKeys.profiles,
    queryFn: async () => {
      try {
        return await api.getProfiles();
      } catch {
        // Fallback to mock data when ESP32 is not reachable
        return mockProfiles;
      }
    },
  });
}

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => api.getSettings(),
    placeholderData: {
      tempUnit: "C" as const,
      maxSafeTemp: 1400,
      alarmEnabled: true,
      autoShutdown: true,
      notificationsEnabled: true,
      tcOffsetC: 0,
      webhookUrl: "",
      elementWatts: 0,
      electricityCostKwh: 0,
    },
  });
}

export function useStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: () => api.getStatus(),
    retry: false,
  });
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

// --- Mutations ---

export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: FiringProfile) => api.saveProfile(profile),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
    onError: (_err, profile) => {
      // Local-only fallback: update cache directly
      queryClient.setQueryData<FiringProfile[]>(queryKeys.profiles, (old) => {
        if (!old) return [profile];
        const existing = old.find((p) => p.id === profile.id);
        if (existing) return old.map((p) => (p.id === profile.id ? profile : p));
        return [...old, profile];
      });
    },
  });
}

export function useDeleteProfile() {
  const queryClient = useQueryClient();
  const { selectedProfileId, setSelectedProfileId } = useKilnStore();
  return useMutation({
    mutationFn: (profileId: string) => api.deleteProfile(profileId),
    onSuccess: (_data, profileId) => {
      if (selectedProfileId === profileId) setSelectedProfileId(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.profiles });
    },
    onError: (_err, profileId) => {
      if (selectedProfileId === profileId) setSelectedProfileId(null);
      queryClient.setQueryData<FiringProfile[]>(queryKeys.profiles, (old) =>
        old?.filter((p) => p.id !== profileId),
      );
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
