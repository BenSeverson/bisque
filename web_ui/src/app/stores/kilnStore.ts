import { create } from "zustand";
import { FiringProgress, TemperatureDataPoint, coerceFiringStatus } from "../types/kiln";
import { kilnWS, WSMessage, WSConnectionState } from "../services/websocket";
import type { StatusResponse } from "../services/api";

interface KilnState {
  // UI state
  selectedProfileId: string | null;
  setSelectedProfileId: (id: string | null) => void;

  // Connection health. Without this the dashboard cannot distinguish a live
  // reading from the last one received before the device dropped off.
  connectionState: WSConnectionState;
  lastUpdateAt: number | null;

  // Real-time firing data (from WebSocket)
  firingProgress: FiringProgress;
  currentTempData: TemperatureDataPoint[];
  /** False while currentTempData is still the synthetic placeholder point. */
  tempDataSeeded: boolean;
  resetTempData: () => void;

  /**
   * Fold a REST /status snapshot into the store.
   *
   * `dispatchedAt` is the timestamp taken *before* the request went out, not
   * when it resolved: the snapshot describes the kiln as of roughly that
   * moment, so any WebSocket frame stamped at or after it is strictly newer.
   */
  seedFromStatus: (status: StatusResponse, dispatchedAt: number) => void;

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
  delayRemaining: 0,
  status: "idle",
};

// Deliberately empty. Seeding a synthetic {time: 0, temp: 20} point drew a
// cold-start ramp that was never measured: load the page six hours into a
// firing with the kiln at 900°C and the chart claimed it started at 20°C.
// The first real WS frame (or the REST seed) provides the first point.
const initialTempData: TemperatureDataPoint[] = [];

const MAX_TEMP_POINTS = 600;

/**
 * Add one reading to the live series, deduped by minute.
 *
 * Without the dedupe, sub-minute updates would flood the buffer (e.g. 1Hz → 60
 * points/min) and the cap would only retain ~10 minutes of history. A point
 * that lands *before* the tail is dropped rather than appended: the chart's X
 * axis is the point order, so an out-of-order insert draws the curve running
 * backwards.
 */
function appendPoint(
  series: TemperatureDataPoint[],
  point: TemperatureDataPoint,
): TemperatureDataPoint[] {
  const last = series[series.length - 1];
  if (last && last.time === point.time) return [...series.slice(0, -1), point];
  if (last && last.time > point.time) return series;
  const next = [...series, point];
  if (next.length > MAX_TEMP_POINTS) next.shift();
  return next;
}

export const useKilnStore = create<KilnState>((set) => ({
  selectedProfileId: null,
  setSelectedProfileId: (id) => set({ selectedProfileId: id }),

  connectionState: "offline",
  lastUpdateAt: null,

  firingProgress: initialProgress,
  currentTempData: [...initialTempData],
  tempDataSeeded: false,
  resetTempData: () => set({ currentTempData: [...initialTempData], tempDataSeeded: false }),

  seedFromStatus: (s, dispatchedAt) =>
    set((state) => {
      /* A WebSocket frame that landed while this request was in flight already
         describes a later moment than the snapshot in hand. Applying the
         snapshot would rewind the dashboard by a tick — and, before #124 was
         fixed, delete every chart point those frames had accumulated. */
      if (state.lastUpdateAt !== null && state.lastUpdateAt >= dispatchedAt) return {};

      /* Merge, never replace. The store outlives the Dashboard component (the
         tab is not forceMount'ed, so it remounts and re-seeds on every visit)
         while the WebSocket runs app-wide and keeps filling the series in the
         background. Replacing here collapsed hours of firing history into a
         single "now" point each time the user came back to the tab (#124).
         The one case that legitimately replaces is a series still holding the
         synthetic placeholder point, which is not history worth keeping. */
      const series = state.tempDataSeeded ? state.currentTempData : [];
      const currentTempData = appendPoint(series, {
        time: Math.round(s.elapsedTime / 60),
        temp: Math.round(s.currentTemp),
        target: Math.round(s.targetTemp),
      });

      return {
        firingProgress: {
          isActive: s.isActive,
          profileId: s.profileId || null,
          startTime: state.firingProgress.startTime,
          currentTemp: s.currentTemp,
          targetTemp: s.targetTemp,
          currentSegment: s.currentSegment,
          totalSegments: s.totalSegments,
          elapsedTime: s.elapsedTime,
          estimatedTimeRemaining: s.estimatedTimeRemaining,
          delayRemaining: s.delayRemaining ?? 0,
          status: coerceFiringStatus(s.status),
        },
        currentTempData,
        tempDataSeeded: true,
        selectedProfileId: s.isActive && s.profileId ? s.profileId : state.selectedProfileId,
      };
    }),

  initWebSocket: () => {
    kilnWS.connect();

    const unsubscribeStatus = kilnWS.subscribeStatus((state: WSConnectionState) => {
      set({ connectionState: state });
    });

    const unsubscribe = kilnWS.subscribe((msg: WSMessage) => {
      if (msg.type === "temp_update") {
        const d = msg.data;
        const receivedAt = Date.now();
        set((state) => {
          const prev = state.firingProgress;

          /* A firing can start or stop from anywhere — the LCD, the iOS app,
             another browser tab — and this client only ever reset its chart
             from its own Start/Stop handlers. Detect the discontinuity from the
             stream itself, or a new firing's low-time points get appended after
             the previous series' high-time tail and the chart's axis runs
             backward. */
          // Only from the second frame onward: on the very first frame every
          // field looks like a transition away from the initial state, which
          // would discard the point seeded by the mount-time getStatus().
          const seenAFrame = state.lastUpdateAt !== null;
          const isNewFiring =
            seenAFrame &&
            ((!!d.profileId && d.profileId !== prev.profileId) ||
              d.elapsedTime < prev.elapsedTime ||
              (d.isActive && !prev.isActive));

          /* Once a firing ends, its elapsed/segment/ETA figures describe
             nothing. Leaving them meant the dashboard showed a dead firing's
             numbers beside status "Idle". */
          const endedFiring = !d.isActive && prev.isActive;
          const timeMin = Math.round(d.elapsedTime / 60);
          const newPoint = {
            time: timeMin,
            temp: Math.round(d.currentTemp),
            target: Math.round(d.targetTemp),
          };
          const newData = isNewFiring ? [newPoint] : appendPoint(state.currentTempData, newPoint);

          /* Follow the running firing's profile. The dashboard resolves segment
             names and the profile overlay through selectedProfileId, so adopting
             only firingProgress.profileId would still leave a firing started
             from the LCD or the iOS app without segment names.

             Compared against selectedProfileId, not prev.profileId: the firmware
             leaves profileId populated while idle, so prev.profileId can equal
             the next firing's id (re-firing a profile the user has since browsed
             away from), and comparing against it would refuse to follow. The
             profile selector is disabled while active, so this can only correct
             a stale selection, never fight a browsing user. */
          const followProfile =
            d.isActive && !!d.profileId && d.profileId !== state.selectedProfileId;

          return {
            lastUpdateAt: receivedAt,
            ...(followProfile ? { selectedProfileId: d.profileId } : {}),
            firingProgress: {
              isActive: d.isActive,
              profileId: d.profileId ?? prev.profileId,
              startTime: prev.startTime,
              currentTemp: d.currentTemp,
              targetTemp: d.targetTemp,
              currentSegment: endedFiring ? 0 : d.currentSegment,
              totalSegments: endedFiring ? 0 : d.totalSegments,
              elapsedTime: endedFiring ? 0 : d.elapsedTime,
              estimatedTimeRemaining: endedFiring ? 0 : d.estimatedTimeRemaining,
              delayRemaining: endedFiring ? 0 : (d.delayRemaining ?? 0),
              status: coerceFiringStatus(d.status),
            },
            currentTempData: newData,
            tempDataSeeded: true,
          };
        });
      }
    });

    return () => {
      unsubscribeStatus();
      unsubscribe();
      kilnWS.disconnect();
    };
  },
}));
