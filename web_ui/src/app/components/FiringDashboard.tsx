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
import { TemperatureDataPoint, HOLD_UNTIL_SKIP } from "../types/kiln";
import { api } from "../services/api";
import { toast } from "sonner";
import { formatDuration } from "../utils/time";
import { toErrorMessage } from "../utils/error";
import { computeSegmentDurationMinutes } from "../utils/profile";
import { useKilnStore } from "../stores/kilnStore";
import {
  useProfiles,
  useStartFiring,
  useStopFiring,
  usePauseFiring,
  useSkipSegment,
} from "../hooks/queries";

export function FiringDashboard() {
  const {
    selectedProfileId,
    setSelectedProfileId,
    firingProgress,
    currentTempData,
    resetTempData,
  } = useKilnStore();
  const { data: profiles = [] } = useProfiles();
  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === selectedProfileId) ?? null,
    [profiles, selectedProfileId],
  );

  const startFiring = useStartFiring();
  const stopFiring = useStopFiring();
  const pauseFiring = usePauseFiring();
  const skipSegment = useSkipSegment();

  const [delayMinutes, setDelayMinutes] = useState<number>(0);
  const [profilePath, setProfilePath] = useState<TemperatureDataPoint[]>([]);

  // Fetch initial status from REST API
  useEffect(() => {
    api
      .getStatus()
      .then((s) => {
        useKilnStore.setState({
          firingProgress: {
            isActive: s.isActive,
            profileId: s.profileId,
            startTime: null,
            currentTemp: s.currentTemp,
            targetTemp: s.targetTemp,
            currentSegment: s.currentSegment,
            totalSegments: s.totalSegments,
            elapsedTime: s.elapsedTime,
            estimatedTimeRemaining: s.estimatedTimeRemaining,
            status: s.status,
          },
        });
      })
      .catch(() => {});
  }, []);

  // Calculate the complete profile path when profile is selected
  useEffect(() => {
    if (!selectedProfile) {
      setProfilePath([]);
      return;
    }

    const path: TemperatureDataPoint[] = [];
    let currentTime = 0;
    let currentTemp = 20;

    path.push({ time: 0, temp: 20, target: 20 });

    selectedProfile.segments.forEach((segment) => {
      const tempDifference = segment.targetTemp - currentTemp;
      const { rampMinutes: rampTimeMinutes } = computeSegmentDurationMinutes(
        {
          targetTemp: segment.targetTemp,
          rampRate: segment.rampRate,
          holdMinutes: segment.holdTime,
        },
        currentTemp,
      );

      const steps = Math.max(10, Math.floor(rampTimeMinutes / 5));
      for (let i = 1; i <= steps; i++) {
        const progress = i / steps;
        const stepTime = currentTime + rampTimeMinutes * progress;
        const stepTemp = currentTemp + tempDifference * progress;
        path.push({
          time: Math.round(stepTime),
          temp: Math.round(stepTemp),
          target: Math.round(stepTemp),
        });
      }

      currentTime += rampTimeMinutes;
      currentTemp = segment.targetTemp;

      if (segment.holdTime > 0 && segment.holdTime !== HOLD_UNTIL_SKIP) {
        path.push({
          time: Math.round(currentTime + segment.holdTime),
          temp: segment.targetTemp,
          target: segment.targetTemp,
        });
        currentTime += segment.holdTime;
      }
    });

    setProfilePath(path);
  }, [selectedProfile]);

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
    try {
      await stopFiring.mutateAsync();
      resetTempData();
      toast.success("Firing stopped");
    } catch (e) {
      toast.error(`Failed to stop: ${toErrorMessage(e)}`);
    }
  }, [stopFiring, resetTempData]);

  const getProgress = () => {
    if (!selectedProfile || firingProgress.elapsedTime === 0) return 0;
    const totalSeconds = selectedProfile.estimatedDuration * 60;
    return Math.min(100, (firingProgress.elapsedTime / totalSeconds) * 100);
  };

  const getStatusBadge = () => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      heating: "default",
      holding: "default",
      cooling: "default",
      complete: "secondary",
      error: "destructive",
      paused: "outline",
      autotune: "default",
      idle: "secondary",
    };
    return (
      <Badge variant={variants[firingProgress.status] || "secondary"}>
        {firingProgress.status.charAt(0).toUpperCase() + firingProgress.status.slice(1)}
      </Badge>
    );
  };

  interface ChartPoint {
    time: number;
    profile?: number;
    current?: number;
    target?: number;
  }

  const getChartData = (): ChartPoint[] => {
    if (!selectedProfile || profilePath.length === 0) {
      return currentTempData.map((p) => ({ time: p.time, current: p.temp, target: p.target }));
    }

    const map = new Map<number, ChartPoint>();

    profilePath.forEach((point) => {
      map.set(point.time, { time: point.time, profile: point.temp });
    });

    currentTempData.forEach((point) => {
      const existing = map.get(point.time);
      if (existing) {
        existing.current = point.temp;
        existing.target = point.target;
      } else {
        map.set(point.time, { time: point.time, current: point.temp, target: point.target });
      }
    });

    return Array.from(map.values()).sort((a, b) => a.time - b.time);
  };

  return (
    <div className="space-y-6">
      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Current Temperature</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <ThermometerSun className="h-6 w-6" />
              {Math.round(firingProgress.currentTemp)}&deg;C
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Target Temperature</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <Flame className="h-6 w-6" />
              {Math.round(firingProgress.targetTemp)}&deg;C
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Elapsed Time</CardDescription>
            <CardTitle className="flex items-center gap-2 text-3xl">
              <Clock className="h-6 w-6" />
              {formatDuration(firingProgress.elapsedTime)}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Status</CardDescription>
            <CardTitle className="flex items-center gap-2">{getStatusBadge()}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Progress and Controls */}
      <Card>
        <CardHeader>
          <CardTitle>Firing Controls</CardTitle>
          <CardDescription>
            {selectedProfile &&
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
            {firingProgress.isActive && (
              <p className="text-xs text-muted-foreground">
                Stop the current firing to change profile
              </p>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span>Overall Progress</span>
              <span>{Math.round(getProgress())}%</span>
            </div>
            <Progress value={getProgress()} />
            {selectedProfile && (
              <p className="text-sm text-muted-foreground">
                Estimated time remaining: {formatDuration(firingProgress.estimatedTimeRemaining)}
              </p>
            )}
          </div>

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
            ) : (
              <Button onClick={handlePause} variant="outline" className="gap-2">
                <Pause className="h-4 w-4" />
                Pause
              </Button>
            )}

            <Button
              onClick={handleStop}
              variant="destructive"
              disabled={!firingProgress.isActive && firingProgress.status !== "paused"}
              className="gap-2"
            >
              <Square className="h-4 w-4" />
              Stop
            </Button>

            {firingProgress.isActive && firingProgress.status !== "paused" && (
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
                    {segment.rampRate}&deg;C/hr &rarr; {segment.targetTemp}&deg;C
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
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={getChartData()}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                type="number"
                domain={
                  profilePath.length > 0
                    ? [0, Math.ceil(profilePath[profilePath.length - 1].time / 60) * 60]
                    : ["auto", "auto"]
                }
                ticks={
                  profilePath.length > 0
                    ? Array.from(
                        { length: Math.ceil(profilePath[profilePath.length - 1].time / 60) + 1 },
                        (_, i) => i * 60,
                      )
                    : undefined
                }
                tickFormatter={(min: number) => `${Math.round(min / 60)}`}
                label={{ value: "Time (hours)", position: "insideBottom", offset: -5 }}
              />
              <YAxis
                label={{ value: "Temperature (\u00B0C)", angle: -90, position: "insideLeft" }}
              />
              <Tooltip
                labelFormatter={(label) => {
                  const min = Number(label);
                  const h = Math.floor(min / 60);
                  const m = min % 60;
                  return h > 0 ? `${h}h ${m}m` : `${m}m`;
                }}
                formatter={(value, name) => [`${value}°C`, name as string]}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="current"
                stroke="#ef4444"
                strokeWidth={2}
                name="Current Temp"
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="target"
                stroke="#3b82f6"
                strokeWidth={2}
                strokeDasharray="5 5"
                name="Target Temp"
                dot={false}
              />
              {profilePath.length > 0 && (
                <Line
                  type="monotone"
                  dataKey="profile"
                  stroke="#6b7280"
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  name="Profile Path"
                  dot={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
