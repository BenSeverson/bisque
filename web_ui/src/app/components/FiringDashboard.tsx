import { useState, useEffect, useCallback, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Label } from "./ui/label";
import { Input } from "./ui/input";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  Play,
  Pause,
  Square,
  Flame,
  ThermometerSun,
  Clock,
  SkipForward,
  Timer,
} from "lucide-react";
import { TemperatureDataPoint, HOLD_UNTIL_SKIP, FiringStatus } from "../types/kiln";
import { api } from "../services/api";
import { toast } from "sonner";
import { formatCountdown, formatDuration } from "../utils/time";
import { toErrorMessage } from "../utils/error";
import { buildProfilePath, buildProfileTimeAxis } from "../utils/profilePath";
import { buildChartData, type ChartPoint } from "../utils/chartData";
import { computeFiringProgress } from "../utils/firingProgress";
import { useKilnStore } from "../stores/kilnStore";
import { ConnectionBanner } from "./ConnectionBanner";
import { deriveFiringPhase, showsFiringProgress } from "../utils/firingPhase";
import { describeFiringChart } from "../utils/chartAria";
import { describeFiringError, firingErrorGuidance } from "../utils/firingError";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import {
  useProfiles,
  useStartFiring,
  useStopFiring,
  usePauseFiring,
  useSkipSegment,
  useTempUnit,
  useSystemInfo,
  queryKeys,
} from "../hooks/queries";
import { useQueryClient } from "@tanstack/react-query";
import { formatTemp, formatRate, unitLabel } from "../utils/temperature";

export function FiringDashboard() {
  const {
    selectedProfileId,
    setSelectedProfileId,
    firingProgress,
    currentTempData,
    resetTempData,
    lastUpdateAt,
    seedFromStatus,
  } = useKilnStore();
  const { data: profiles = [], isError: profilesFailed } = useProfiles();
  const unit = useTempUnit();
  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === selectedProfileId) ?? null,
    [profiles, selectedProfileId],
  );

  const startFiring = useStartFiring();
  const stopFiring = useStopFiring();
  const pauseFiring = usePauseFiring();
  const skipSegment = useSkipSegment();

  const [delayMinutes, setDelayMinutes] = useState<number>(0);
  // Stopping mid-firing ruins the load, so it is confirmed here the way the
  // on-device LCD confirms it (modal_action_menu.c). An accidental tap is far
  // more likely on the web surface than on the physical 5-way switch.
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);

  // Fetch initial status from REST API. Seeds firingProgress AND the chart so a
  // mid-firing reload doesn't show 20°C until the first WS message arrives, and
  // restores the active profile selection.
  //
  // This runs on every visit to the tab, not just the first: the Dashboard tab
  // is not forceMount'ed, so it remounts each time. The store and the app-wide
  // WebSocket both outlive that remount, which is why seedFromStatus folds the
  // snapshot into the existing series instead of replacing it, and ignores a
  // snapshot older than the frames already applied (#124).
  useEffect(() => {
    let cancelled = false;
    const dispatchedAt = Date.now();
    api
      .getStatus()
      .then((s) => {
        if (cancelled) return;
        seedFromStatus(s, dispatchedAt);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [seedFromStatus]);

  // The complete planned path for the selected profile. Point count is bounded
  // inside buildProfilePath — see MAX_PROFILE_PATH_POINTS.
  const profilePath = useMemo<TemperatureDataPoint[]>(() => {
    if (!selectedProfile) return [];
    return buildProfilePath(selectedProfile.segments);
  }, [selectedProfile]);

  // Hour ticks for the planned span, bounded the same way the path is.
  const timeAxis = useMemo(() => buildProfileTimeAxis(profilePath), [profilePath]);

  const handleStart = useCallback(async () => {
    if (!selectedProfile) return;
    try {
      await startFiring.mutateAsync({ profileId: selectedProfile.id, delayMinutes });
      resetTempData();
      toast.success(
        delayMinutes > 0 ? `Firing scheduled in ${delayMinutes} min` : "Firing started",
      );
    } catch (e) {
      toast.error(`Failed to start: ${toErrorMessage(e)}`);
    }
  }, [selectedProfile, delayMinutes, startFiring, resetTempData]);

  const handleSkipSegment = useCallback(async () => {
    try {
      await skipSegment.mutateAsync();
      toast.success("Skipped to next segment");
    } catch (e) {
      toast.error(`Failed to skip: ${toErrorMessage(e)}`);
    }
  }, [skipSegment]);

  const handlePause = useCallback(async () => {
    try {
      const result = await pauseFiring.mutateAsync();
      toast.success(result.action === "paused" ? "Firing paused" : "Firing resumed");
    } catch (e) {
      toast.error(`Failed: ${toErrorMessage(e)}`);
    }
  }, [pauseFiring]);

  const handleStop = useCallback(async () => {
    setStopConfirmOpen(false);
    try {
      await stopFiring.mutateAsync();
      resetTempData();
      toast.success("Firing stopped");
    } catch (e) {
      toast.error(`Failed to stop: ${toErrorMessage(e)}`);
    }
  }, [stopFiring, resetTempData]);

  const phase = deriveFiringPhase(firingProgress);
  const progressVisible = showsFiringProgress(phase);

  // Wall-clock start time for an armed delay. The countdown says how long; this
  // says *when*, which is the thing an operator actually checks before leaving a
  // kiln to run overnight (#204).
  //
  // Anchored to when the frame arrived rather than to render time: the countdown
  // was measured on the device at that instant, so this stays put across
  // unrelated re-renders instead of drifting a second at a time.
  const delayRemaining = firingProgress.delayRemaining;
  const startsAtLabel = useMemo(() => {
    if (phase !== "scheduled" || delayRemaining <= 0 || lastUpdateAt === null) return null;
    return new Date(lastUpdateAt + delayRemaining * 1000).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
  }, [phase, delayRemaining, lastUpdateAt]);

  const progressResult = useMemo(
    () =>
      computeFiringProgress({
        profile: selectedProfile,
        elapsedSeconds: firingProgress.elapsedTime,
        currentSegment: firingProgress.currentSegment,
      }),
    [selectedProfile, firingProgress.elapsedTime, firingProgress.currentSegment],
  );
  const progress = progressResult.percent;

  const getStatusBadge = () => {
    const variants: Record<FiringStatus, "default" | "secondary" | "destructive" | "outline"> = {
      heating: "default",
      holding: "default",
      cooling: "default",
      complete: "secondary",
      error: "destructive",
      paused: "outline",
      autotune: "default",
      idle: "secondary",
    };
    // The firmware reports is_active=true with status=IDLE during an armed
    // delay; showing a bare "Idle" made a scheduled overnight firing look as
    // though nothing had been set at all.
    if (phase === "scheduled") {
      return (
        <Badge variant="outline">
          {firingProgress.delayRemaining > 0
            ? `Scheduled — ${formatCountdown(firingProgress.delayRemaining)}`
            : "Scheduled"}
        </Badge>
      );
    }
    return (
      <Badge variant={variants[firingProgress.status]}>
        {firingProgress.status.charAt(0).toUpperCase() + firingProgress.status.slice(1)}
      </Badge>
    );
  };

  // The live status payload carries no error code — only /api/v1/system does,
  // via firing_engine_get_error_code(). useSystemInfo() never refetches on its
  // own, so without this the banner below would show whatever code was cached
  // when Settings last loaded, which is usually "none". Refetch on the edge
  // into error, not on every render while in it.
  const queryClient = useQueryClient();
  const inError = firingProgress.status === "error";
  useEffect(() => {
    if (inError) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.systemInfo });
    }
  }, [inError, queryClient]);
  const { data: systemInfo } = useSystemInfo();
  const errorCode = inError ? systemInfo?.lastErrorCode : undefined;

  const chartAriaLabel = useMemo(
    () =>
      describeFiringChart({
        points: currentTempData,
        hasPlanned: profilePath.length > 0,
        unit,
      }),
    [currentTempData, profilePath, unit],
  );

  const chartData = useMemo<ChartPoint[]>(
    () =>
      buildChartData({
        currentTempData,
        // An unselected profile simply contributes no planned path; the live
        // series is converted either way.
        profilePath: selectedProfile ? profilePath : [],
        unit,
      }),
    [selectedProfile, profilePath, currentTempData, unit],
  );

  // Recharts draws a line between points, so a series holding exactly one
  // measurement renders as nothing at all under `dot={false}`. Now that the
  // series starts empty rather than with a fabricated 20 °C point (#192), that
  // is the normal state on every fresh load until telemetry reaches a second
  // rounded minute — and it is permanent if only the REST seed lands and the
  // WebSocket never connects. Show the marker in exactly that case: honest
  // about having one reading, rather than silently showing none.
  const showMeasuredDots = currentTempData.length === 1;

  return (
    <div className="space-y-6">
      <ConnectionBanner />

      {/* A "Error" badge was the entire report of a failed firing (#164). The
          code is only on /api/v1/system, so it can lag a beat behind the
          status flip — render the generic line rather than nothing until it
          arrives, so the banner never appears empty. */}
      {inError && (
        <div
          className="p-4 rounded-lg border border-destructive/50 bg-destructive/10"
          role="alert"
          aria-live="assertive"
        >
          <p className="font-medium text-destructive">
            Firing stopped: {describeFiringError(errorCode)}
          </p>
          {firingErrorGuidance(errorCode) && (
            <p className="text-sm text-muted-foreground mt-1">{firingErrorGuidance(errorCode)}</p>
          )}
        </div>
      )}

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Current Temperature</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <ThermometerSun className="h-6 w-6" />
              {formatTemp(firingProgress.currentTemp, unit)}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Target Temperature</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <Flame className="h-6 w-6" />
              {formatTemp(firingProgress.targetTemp, unit)}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Elapsed Time</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <Clock className="h-6 w-6" />
              {progressVisible ? formatDuration(firingProgress.elapsedTime) : "—"}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Status</CardDescription>
            {/* Status changes on its own as the firing advances, with no user
                action to anchor them — polite live region so a screen-reader
                user hears the transition instead of having to re-read the
                page to discover it (#170). */}
            <CardTitle className="flex items-center gap-2" aria-live="polite">
              {getStatusBadge()}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Progress and Controls */}
      <Card>
        <CardHeader>
          <CardTitle>Firing Controls</CardTitle>
          <CardDescription>
            {phase === "scheduled" && (
              <>
                {firingProgress.delayRemaining > 0 ? (
                  <>
                    Starts in {formatCountdown(firingProgress.delayRemaining)}
                    {startsAtLabel && <> — at {startsAtLabel}</>}
                  </>
                ) : (
                  <>Scheduled — the kiln will start automatically</>
                )}
              </>
            )}
            {progressVisible &&
              selectedProfile &&
              firingProgress.currentSegment < (selectedProfile?.segments.length || 0) && (
                <>
                  Current Segment: {selectedProfile.segments[firingProgress.currentSegment]?.name}
                </>
              )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!firingProgress.isActive && firingProgress.status !== "paused" && (
            <div className="flex items-end gap-3">
              <div className="space-y-2 w-36">
                <Label htmlFor="delay-start" className="flex items-center gap-1">
                  <Timer className="h-3 w-3" />
                  Delay Start (min)
                </Label>
                <Input
                  id="delay-start"
                  type="number"
                  min="0"
                  max="1440"
                  value={delayMinutes}
                  onChange={(e) => setDelayMinutes(Math.max(0, parseInt(e.target.value) || 0))}
                />
              </div>
              {delayMinutes > 0 && (
                <p className="text-xs text-muted-foreground pb-2">
                  Kiln will start in {delayMinutes} min
                </p>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="profile-select">Select Firing Profile</Label>
            <Select
              value={selectedProfile?.id || ""}
              onValueChange={setSelectedProfileId}
              disabled={firingProgress.isActive}
            >
              <SelectTrigger id="profile-select">
                <SelectValue placeholder="Choose a firing profile..." />
              </SelectTrigger>
              <SelectContent>
                {profiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {/* Without this the picker is simply empty and Start is disabled,
                which reads as "this kiln has no profiles" when the real story
                is that the fetch failed — the same misreading #135 fixed on the
                Profiles tab. */}
            {profilesFailed && (
              <p className="text-xs text-destructive">
                Could not load profiles — check the connection. Your saved profiles are still on the
                kiln.
              </p>
            )}
            {firingProgress.isActive && (
              <p className="text-xs text-muted-foreground">
                Stop the current firing to change profile
              </p>
            )}
          </div>

          {progressVisible && (
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>
                  Overall Progress
                  {!progressResult.timeBased && (
                    <span className="text-muted-foreground"> (by segment)</span>
                  )}
                </span>
                <span>{Math.round(progress)}%</span>
              </div>
              <Progress value={progress} />
              {selectedProfile && (
                <p className="text-sm text-muted-foreground">
                  Estimated time remaining: {formatDuration(firingProgress.estimatedTimeRemaining)}
                </p>
              )}
            </div>
          )}

          <div className="flex gap-2">
            {!firingProgress.isActive && firingProgress.status !== "paused" ? (
              <Button onClick={handleStart} disabled={!selectedProfile} className="gap-2">
                <Play className="h-4 w-4" />
                Start Firing
              </Button>
            ) : firingProgress.status === "paused" ? (
              <Button onClick={handlePause} className="gap-2">
                <Play className="h-4 w-4" />
                Resume
              </Button>
            ) : phase === "scheduled" ? null : ( // nothing to pause until it starts
              <Button onClick={handlePause} variant="outline" className="gap-2">
                <Pause className="h-4 w-4" />
                Pause
              </Button>
            )}

            <Button
              onClick={() => setStopConfirmOpen(true)}
              variant="destructive"
              disabled={!firingProgress.isActive && firingProgress.status !== "paused"}
              className="gap-2"
            >
              <Square className="h-4 w-4" />
              {phase === "scheduled" ? "Cancel" : "Stop"}
            </Button>

            {progressVisible && firingProgress.status !== "paused" && (
              <Button onClick={handleSkipSegment} variant="outline" className="gap-2 ml-auto">
                <SkipForward className="h-4 w-4" />
                Skip Segment
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Firing Segments */}
      {selectedProfile && (
        <Card>
          <CardHeader>
            <CardTitle>Firing Segments</CardTitle>
            <CardDescription>
              Profile: {selectedProfile.name} - {selectedProfile.description}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {selectedProfile.segments.map((segment, index) => (
                <div
                  key={segment.id}
                  className={`p-3 rounded-lg border ${
                    index === firingProgress.currentSegment && firingProgress.isActive
                      ? "bg-primary/10 border-primary"
                      : "bg-muted/50"
                  }`}
                >
                  <div className="flex justify-between items-center">
                    <span className="font-medium">{segment.name}</span>
                    {index === firingProgress.currentSegment && firingProgress.isActive && (
                      <Badge variant="default">Active</Badge>
                    )}
                  </div>
                  <div className="text-sm text-muted-foreground mt-1">
                    {segment.rampRate > 0 ? "+" : ""}
                    {formatRate(segment.rampRate, unit)} &rarr;{" "}
                    {formatTemp(segment.targetTemp, unit)}
                    {segment.holdTime === HOLD_UNTIL_SKIP && " (hold until skip)"}
                    {segment.holdTime > 0 &&
                      segment.holdTime !== HOLD_UNTIL_SKIP &&
                      `, hold ${segment.holdTime} min`}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Temperature Graph */}
      <Card>
        <CardHeader>
          <CardTitle>Temperature Profile</CardTitle>
          <CardDescription>
            {selectedProfile ? `Running: ${selectedProfile.name}` : "No profile selected"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Recharts emits an unlabelled <svg>, so the whole chart is silent
              to a screen reader (#170). Presenting it as one image with a
              summary alt text is the standard remedy — role="img" also makes
              the descendants presentational, so the axis ticks stop leaking
              out as a stream of loose numbers. */}
          <div role="img" aria-label={chartAriaLabel}>
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="time"
                  type="number"
                  domain={timeAxis.ticks.length > 0 ? [0, timeAxis.domainMax] : ["auto", "auto"]}
                  ticks={timeAxis.ticks.length > 0 ? timeAxis.ticks : undefined}
                  tickFormatter={(min: number) => `${Math.round(min / 60)}`}
                  label={{ value: "Time (hours)", position: "insideBottom", offset: -5 }}
                />
                <YAxis
                  label={{
                    value: `Temperature (${unitLabel(unit)})`,
                    angle: -90,
                    position: "insideLeft",
                  }}
                />
                <Tooltip
                  labelFormatter={(label) => {
                    const min = Number(label);
                    const h = Math.floor(min / 60);
                    const m = min % 60;
                    return h > 0 ? `${h}h ${m}m` : `${m}m`;
                  }}
                  formatter={(value, name) => [`${value}${unitLabel(unit)}`, name as string]}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="current"
                  stroke="var(--chart-1)"
                  strokeWidth={2}
                  name="Current Temp"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="target"
                  stroke="var(--chart-3)"
                  strokeWidth={2}
                  strokeDasharray="5 5"
                  name="Target Temp"
                  dot={false}
                />
                {profilePath.length > 0 && (
                  <Line
                    type="monotone"
                    dataKey="profile"
                    stroke="var(--muted-foreground)"
                    strokeWidth={1}
                    strokeDasharray="3 3"
                    name="Profile Path"
                    dot={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Dialog open={stopConfirmOpen} onOpenChange={setStopConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Stop the firing?</DialogTitle>
            <DialogDescription>
              The kiln will stop heating immediately and the firing cannot be resumed. This will
              likely ruin the load.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStopConfirmOpen(false)}>
              Keep firing
            </Button>
            <Button variant="destructive" onClick={handleStop}>
              Stop firing
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
