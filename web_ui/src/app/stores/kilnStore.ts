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

  /* When the current failure began, or null if the kiln is not in error.
     The error *cause* lives on /api/v1/system rather than on this feed, so a
     consumer has to fetch it separately — and needs to know whether what it
     got back postdates the failure it is meant to explain. Recorded here
     because the transition is only visible while folding a frame. */
  errorSince: number | null;

  // Real-time firing data (from WebSocket)
  firingProgress: FiringProgress;
  currentTempData: TemperatureDataPoint[];
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
  dutyPercent: null,
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

/**
 * Does this observation announce a different firing than the one being plotted?
 *
 * A firing can start or stop from anywhere — the LCD, the iOS app, another
 * browser tab — so the discontinuity has to be read out of the data rather than
 * inferred from this client's own Start/Stop handlers. Either the WebSocket
 * stream or the REST snapshot can be the first to see it, so both ask.
 *
 * Rewound elapsed time is the third signal, but it is left to the callers: they
 * measure it against different baselines. See the call sites.
 */
function isDifferentFiring(
  next: { profileId?: string | null; isActive: boolean },
  prev: FiringProgress,
): boolean {
  return (
    (!!next.profileId && next.profileId !== prev.profileId) || (next.isActive && !prev.isActive)
  );
}

export const useKilnStore = create<KilnState>((set) => ({
  selectedProfileId: null,
  setSelectedProfileId: (id) => set({ selectedProfileId: id }),

  connectionState: "offline",
  lastUpdateAt: null,
  errorSince: null,

  firingProgress: initialProgress,
  currentTempData: [...initialTempData],
  resetTempData: () => set({ currentTempData: [...initialTempData] }),

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

         A series plotting a firing this snapshot says is over is not history
         worth keeping, and starts over. That is not hypothetical — if the
         device was offline when a new firing began, /status is the first
         observation of it, and merging would drop every point until the new
         firing's elapsed time passed the old series' tail. */
      const point = {
        time: Math.round(s.elapsedTime / 60),
        temp: Math.round(s.currentTemp),
        target: Math.round(s.targetTemp),
      };
      /* Rewind is measured against the plotted tail rather than against
         firingProgress.elapsedTime, because this compares two sources: a
         snapshot computed a few hundred milliseconds either side of the last
         frame can report a second less elapsed without anything having
         restarted. At the chart's one-minute resolution that skew lands on the
         same bin and collapses harmlessly; a point that lands a whole minute
         before the tail cannot belong to the firing being plotted. */
      const tail = state.currentTempData[state.currentTempData.length - 1];
      const restarted =
        isDifferentFiring(s, state.firingProgress) ||
        (tail !== undefined && point.time < tail.time);
      const currentTempData = restarted ? [point] : appendPoint(state.currentTempData, point);

      const status = coerceFiringStatus(s.status);
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
          dutyPercent: s.dutyPercent ?? null,
          status,
        },
        /* A reload landing mid-failure never sees the transition frame, so the
           snapshot has to stamp it or the error banner never gets a code it can
           trust. Preserved if already set — this is the same failure. */
        errorSince: status === "error" ? (state.errorSince ?? dispatchedAt) : null,
        currentTempData,
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

          /* Detect a new firing from the stream itself, or its low-time points
             get appended after the previous series' high-time tail and the
             chart's axis runs backward. */
          // Only from the second frame onward: on the very first frame every
          // field looks like a transition away from the initial state, which
          // would discard the point seeded by the mount-time getStatus().
          // Rewind is measured in raw seconds here: consecutive frames come
          // from one monotonic source, so any decrease is a restart.
          const seenAFrame = state.lastUpdateAt !== null;
          const isNewFiring =
            seenAFrame && (isDifferentFiring(d, prev) || d.elapsedTime < prev.elapsedTime);

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

          const status = coerceFiringStatus(d.status);
          /* Stamped on the edge into error and held for the duration, so a
             second failure cannot be explained by the first one's cause. */
          const errorSince =
            status === "error" ? (prev.status === "error" ? state.errorSince : receivedAt) : null;

          return {
            lastUpdateAt: receivedAt,
            errorSince,
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
              /* Not zeroed on endedFiring: unlike the elapsed/segment figures
                 above, this one still describes the kiln after the firing ends
                 — the element is genuinely off, and the firmware says so in the
                 same frame.

                 An omitted field resets to null rather than holding the last
                 reading. Whether the field exists is a property of the
                 firmware, not of the frame, so "absent" means "this kiln cannot
                 report power" — and the store outlives a reconnect, so after an
                 OTA rollback to pre-#180 firmware a retained value would sit
                 there as a stale percentage forever. */
              dutyPercent: d.dutyPercent ?? null,
              status,
            },
            currentTempData: newData,
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
