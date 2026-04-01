import { create } from "zustand";
import { FiringProgress, TemperatureDataPoint } from "../types/kiln";
import { kilnWS, WSMessage } from "../services/websocket";

interface KilnState {
  // UI state
  selectedProfileId: string | null;
  setSelectedProfileId: (id: string | null) => void;

  // Real-time firing data (from WebSocket)
  firingProgress: FiringProgress;
  currentTempData: TemperatureDataPoint[];
  resetTempData: () => void;

  // WebSocket lifecycle
  initWebSocket: () => () => void;
}

const initialProgress: FiringProgress = {
  isActive: false,
  profileId: null,
  startTime: null,
  currentTemp: 20,
  targetTemp: 20,
  currentSegment: 0,
  totalSegments: 0,
  elapsedTime: 0,
  estimatedTimeRemaining: 0,
  status: "idle",
};

const initialTempData: TemperatureDataPoint[] = [{ time: 0, temp: 20, target: 20 }];

export const useKilnStore = create<KilnState>((set) => ({
  selectedProfileId: null,
  setSelectedProfileId: (id) => set({ selectedProfileId: id }),

  firingProgress: initialProgress,
  currentTempData: [...initialTempData],
  resetTempData: () => set({ currentTempData: [...initialTempData] }),

  initWebSocket: () => {
    kilnWS.connect();

    const unsubscribe = kilnWS.subscribe((msg: WSMessage) => {
      if (msg.type === "temp_update") {
        const d = msg.data;
        set((state) => {
          const timeMin = Math.round(d.elapsedTime / 60);
          const newData = [...state.currentTempData];
          if (newData.length > 200) newData.shift();
          newData.push({
            time: timeMin,
            temp: Math.round(d.currentTemp),
            target: Math.round(d.targetTemp),
          });

          return {
            firingProgress: {
              isActive: d.isActive,
              profileId: state.firingProgress.profileId,
              startTime: state.firingProgress.startTime,
              currentTemp: d.currentTemp,
              targetTemp: d.targetTemp,
              currentSegment: d.currentSegment,
              totalSegments: d.totalSegments,
              elapsedTime: d.elapsedTime,
              estimatedTimeRemaining: d.estimatedTimeRemaining,
              status: d.status,
            },
            currentTempData: newData,
          };
        });
      }
    });

    return () => {
      unsubscribe();
      kilnWS.disconnect();
    };
  },
}));
