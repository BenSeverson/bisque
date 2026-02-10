import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Progress } from './ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Label } from './ui/label';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { Play, Pause, Square, Flame, ThermometerSun, Clock } from 'lucide-react';
import { FiringProfile, FiringProgress, TemperatureDataPoint } from '../types/kiln';
import { api } from '../services/api';
import { kilnWS, WSMessage } from '../services/websocket';
import { toast } from 'sonner';

interface FiringDashboardProps {
  profiles: FiringProfile[];
  selectedProfile: FiringProfile | null;
  onSelectProfile: (profileId: string) => void;
}

export function FiringDashboard({ profiles, selectedProfile, onSelectProfile }: FiringDashboardProps) {
  const [firingProgress, setFiringProgress] = useState<FiringProgress>({
    isActive: false,
    profileId: null,
    startTime: null,
    currentTemp: 20,
    targetTemp: 20,
    currentSegment: 0,
    elapsedTime: 0,
    estimatedTimeRemaining: 0,
  });

  const [status, setStatus] = useState<string>('idle');

  const [currentTempData, setCurrentTempData] = useState<TemperatureDataPoint[]>([
    { time: 0, temp: 20, target: 20 },
  ]);

  const [profilePath, setProfilePath] = useState<TemperatureDataPoint[]>([]);

  // Fetch initial status from REST API
  useEffect(() => {
    api.getStatus().then((s) => {
      setFiringProgress({
        isActive: s.isActive,
        profileId: s.profileId,
        startTime: null,
        currentTemp: s.currentTemp,
        targetTemp: s.targetTemp,
        currentSegment: s.currentSegment,
        elapsedTime: s.elapsedTime,
        estimatedTimeRemaining: s.estimatedTimeRemaining,
      });
      setStatus(s.status);
    }).catch(() => {
      // Not connected to ESP32
    });
  }, []);

  // Subscribe to WebSocket for real-time temperature updates
  useEffect(() => {
    const unsubscribe = kilnWS.subscribe((msg: WSMessage) => {
      if (msg.type === 'temp_update') {
        const d = msg.data;
        setFiringProgress((prev) => ({
          ...prev,
          isActive: d.isActive,
          currentTemp: d.currentTemp,
          targetTemp: d.targetTemp,
          currentSegment: d.currentSegment,
          elapsedTime: d.elapsedTime,
          estimatedTimeRemaining: d.estimatedTimeRemaining,
        }));
        setStatus(d.status);

        // Append to chart data (elapsedTime is in seconds from ESP32)
        const timeMin = Math.round(d.elapsedTime / 60);
        setCurrentTempData((prev) => {
          const newData = [...prev];
          if (newData.length > 200) newData.shift();
          newData.push({
            time: timeMin,
            temp: Math.round(d.currentTemp),
            target: Math.round(d.targetTemp),
          });
          return newData;
        });
      }
    });
    return unsubscribe;
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
      const rampTimeHours = Math.abs(tempDifference) / Math.abs(segment.rampRate);
      const rampTimeMinutes = rampTimeHours * 60;

      const steps = Math.max(10, Math.floor(rampTimeMinutes / 5));
      for (let i = 1; i <= steps; i++) {
        const progress = i / steps;
        const stepTime = currentTime + (rampTimeMinutes * progress);
        const stepTemp = currentTemp + (tempDifference * progress);
        path.push({ time: Math.round(stepTime), temp: Math.round(stepTemp), target: Math.round(stepTemp) });
      }

      currentTime += rampTimeMinutes;
      currentTemp = segment.targetTemp;

      if (segment.holdTime > 0) {
        path.push({ time: Math.round(currentTime + segment.holdTime), temp: segment.targetTemp, target: segment.targetTemp });
        currentTime += segment.holdTime;
      }
    });

    setProfilePath(path);
  }, [selectedProfile]);

  const handleStart = useCallback(async () => {
    if (!selectedProfile) return;
    try {
      await api.startFiring(selectedProfile.id);
      setCurrentTempData([{ time: 0, temp: 20, target: selectedProfile.segments[0].targetTemp }]);
      toast.success('Firing started');
    } catch (e) {
      toast.error(`Failed to start: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [selectedProfile]);

  const handlePause = useCallback(async () => {
    try {
      const result = await api.pauseFiring();
      toast.success(result.action === 'paused' ? 'Firing paused' : 'Firing resumed');
    } catch (e) {
      toast.error(`Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, []);

  const handleStop = useCallback(async () => {
    try {
      await api.stopFiring();
      setCurrentTempData([{ time: 0, temp: 20, target: 20 }]);
      toast.success('Firing stopped');
    } catch (e) {
      toast.error(`Failed to stop: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, []);

  const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${mins}m`;
  };

  const getProgress = () => {
    if (!selectedProfile || firingProgress.elapsedTime === 0) return 0;
    const totalSeconds = selectedProfile.estimatedDuration * 60;
    return Math.min(100, (firingProgress.elapsedTime / totalSeconds) * 100);
  };

  const getStatusBadge = () => {
    const variants: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
      heating: 'default',
      holding: 'default',
      cooling: 'default',
      complete: 'secondary',
      error: 'destructive',
      paused: 'outline',
      autotune: 'default',
      idle: 'secondary',
    };
    return (
      <Badge variant={variants[status] || 'secondary'}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </Badge>
    );
  };

  const getChartData = () => {
    if (!selectedProfile || profilePath.length === 0) {
      return currentTempData;
    }

    const map = new Map<number, { time: number; profile?: number; current?: number; target?: number }>();

    profilePath.forEach(point => {
      map.set(point.time, { time: point.time, profile: point.temp });
    });

    currentTempData.forEach(point => {
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
              {formatTime(firingProgress.elapsedTime)}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardDescription>Status</CardDescription>
            <CardTitle className="flex items-center gap-2">
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
            {selectedProfile && firingProgress.currentSegment < (selectedProfile?.segments.length || 0) && (
              <>Current Segment: {selectedProfile.segments[firingProgress.currentSegment]?.name}</>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="profile-select">Select Firing Profile</Label>
            <Select
              value={selectedProfile?.id || ''}
              onValueChange={onSelectProfile}
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
                Estimated time remaining: {formatTime(firingProgress.estimatedTimeRemaining)}
              </p>
            )}
          </div>

          <div className="flex gap-2">
            {!firingProgress.isActive && status !== 'paused' ? (
              <Button onClick={handleStart} disabled={!selectedProfile} className="gap-2">
                <Play className="h-4 w-4" />
                Start Firing
              </Button>
            ) : status === 'paused' ? (
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
              disabled={!firingProgress.isActive && status !== 'paused'}
              className="gap-2"
            >
              <Square className="h-4 w-4" />
              Stop
            </Button>
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
                      ? 'bg-primary/10 border-primary'
                      : 'bg-muted/50'
                  }`}
                >
                  <div className="flex justify-between items-center">
                    <span className="font-medium">{segment.name}</span>
                    {index === firingProgress.currentSegment && firingProgress.isActive && (
                      <Badge variant="default">Active</Badge>
                    )}
                  </div>
                  <div className="text-sm text-muted-foreground mt-1">
                    {segment.rampRate > 0 ? '+' : ''}{segment.rampRate}&deg;C/hr &rarr; {segment.targetTemp}&deg;C
                    {segment.holdTime > 0 && `, hold ${segment.holdTime} min`}
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
            {selectedProfile ? `Running: ${selectedProfile.name}` : 'No profile selected'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={getChartData()}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="time"
                label={{ value: 'Time (minutes)', position: 'insideBottom', offset: -5 }}
              />
              <YAxis
                label={{ value: 'Temperature (\u00B0C)', angle: -90, position: 'insideLeft' }}
              />
              <Tooltip />
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
