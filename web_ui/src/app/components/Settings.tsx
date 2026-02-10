import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Label } from './ui/label';
import { Input } from './ui/input';
import { Switch } from './ui/switch';
import { Button } from './ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Badge } from './ui/badge';
import { KilnSettings } from '../types/kiln';
import { api, SystemInfo, AutotuneStatus } from '../services/api';
import { toast } from 'sonner';

interface SettingsProps {
  settings: KilnSettings;
  onUpdateSettings: (settings: KilnSettings) => void;
}

export function Settings({ settings, onUpdateSettings }: SettingsProps) {
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [autotuneStatus, setAutotuneStatus] = useState<AutotuneStatus | null>(null);
  const [autotuneSetpoint, setAutotuneSetpoint] = useState(500);
  const [autotuneRunning, setAutotuneRunning] = useState(false);

  useEffect(() => {
    api.getSystemInfo().then(setSystemInfo).catch(() => {});
    api.getAutotuneStatus().then((s) => {
      setAutotuneStatus(s);
      setAutotuneRunning(s.state === 'running');
    }).catch(() => {});
  }, []);

  // Poll autotune status while running
  useEffect(() => {
    if (!autotuneRunning) return;
    const interval = setInterval(() => {
      api.getAutotuneStatus().then((s) => {
        setAutotuneStatus(s);
        if (s.state !== 'running') {
          setAutotuneRunning(false);
          toast.success('Auto-tune complete');
        }
      }).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [autotuneRunning]);

  const handleSave = useCallback(async () => {
    onUpdateSettings(settings);
    toast.success('Settings saved');
  }, [settings, onUpdateSettings]);

  const handleStartAutotune = useCallback(async () => {
    try {
      await api.startAutotune(autotuneSetpoint);
      setAutotuneRunning(true);
      toast.success('Auto-tune started');
    } catch (e) {
      toast.error(`Failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [autotuneSetpoint]);

  const handleStopAutotune = useCallback(async () => {
    try {
      await api.stopAutotune();
      setAutotuneRunning(false);
      toast.success('Auto-tune stopped');
    } catch {
      toast.error('Failed to stop auto-tune');
    }
  }, []);

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h}h ${m}m ${s}s`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold mb-2">Kiln Settings</h2>
        <p className="text-muted-foreground">
          Configure your kiln controller preferences and safety settings.
        </p>
      </div>

      {/* Temperature Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Temperature Settings</CardTitle>
          <CardDescription>Configure temperature units and limits</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="temp-unit">Temperature Unit</Label>
            <Select
              value={settings.tempUnit}
              onValueChange={(value: 'C' | 'F') =>
                onUpdateSettings({ ...settings, tempUnit: value })
              }
            >
              <SelectTrigger id="temp-unit">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="C">Celsius (&deg;C)</SelectItem>
                <SelectItem value="F">Fahrenheit (&deg;F)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="max-temp">Maximum Safe Temperature (&deg;C)</Label>
            <Input
              id="max-temp"
              type="number"
              value={settings.maxSafeTemp}
              onChange={(e) =>
                onUpdateSettings({ ...settings, maxSafeTemp: parseFloat(e.target.value) })
              }
            />
            <p className="text-sm text-muted-foreground">
              The kiln will shut down if this temperature is exceeded. Hardware max: 1400&deg;C.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Safety Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Safety Settings</CardTitle>
          <CardDescription>Configure safety features and alerts</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="alarm-enabled">Temperature Alarm</Label>
              <p className="text-sm text-muted-foreground">
                Sound alarm if temperature exceeds safe limits
              </p>
            </div>
            <Switch
              id="alarm-enabled"
              checked={settings.alarmEnabled}
              onCheckedChange={(checked) =>
                onUpdateSettings({ ...settings, alarmEnabled: checked })
              }
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="auto-shutdown">Automatic Shutdown</Label>
              <p className="text-sm text-muted-foreground">
                Automatically shut down kiln when firing completes
              </p>
            </div>
            <Switch
              id="auto-shutdown"
              checked={settings.autoShutdown}
              onCheckedChange={(checked) =>
                onUpdateSettings({ ...settings, autoShutdown: checked })
              }
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="notifications">Notifications</Label>
              <p className="text-sm text-muted-foreground">
                Receive notifications for important events
              </p>
            </div>
            <Switch
              id="notifications"
              checked={settings.notificationsEnabled}
              onCheckedChange={(checked) =>
                onUpdateSettings({ ...settings, notificationsEnabled: checked })
              }
            />
          </div>
        </CardContent>
      </Card>

      {/* PID Auto-Tune */}
      <Card>
        <CardHeader>
          <CardTitle>Auto-Tune PID</CardTitle>
          <CardDescription>
            Automatically calibrate PID parameters using relay-based Ziegler-Nichols method
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {autotuneStatus && autotuneStatus.currentGains && (
            <div className="grid grid-cols-3 gap-4 p-3 bg-muted/50 rounded-lg">
              <div>
                <p className="text-xs text-muted-foreground">Kp</p>
                <p className="text-lg font-mono">{autotuneStatus.currentGains.kp.toFixed(4)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Ki</p>
                <p className="text-lg font-mono">{autotuneStatus.currentGains.ki.toFixed(4)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Kd</p>
                <p className="text-lg font-mono">{autotuneStatus.currentGains.kd.toFixed(4)}</p>
              </div>
            </div>
          )}

          {autotuneRunning && (
            <div className="flex items-center gap-2">
              <Badge variant="default">Running</Badge>
              <span className="text-sm text-muted-foreground">
                Temp: {autotuneStatus?.currentTemp?.toFixed(1)}&deg;C / {autotuneStatus?.targetTemp?.toFixed(0)}&deg;C
              </span>
            </div>
          )}

          <div className="flex items-end gap-4">
            <div className="space-y-2 flex-1">
              <Label htmlFor="autotune-setpoint">Setpoint Temperature (&deg;C)</Label>
              <Input
                id="autotune-setpoint"
                type="number"
                value={autotuneSetpoint}
                onChange={(e) => setAutotuneSetpoint(parseFloat(e.target.value))}
                disabled={autotuneRunning}
              />
            </div>
            {autotuneRunning ? (
              <Button variant="destructive" onClick={handleStopAutotune}>
                Stop Auto-Tune
              </Button>
            ) : (
              <Button onClick={handleStartAutotune}>
                Start Auto-Tune
              </Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            The auto-tune process will heat to the setpoint and oscillate around it to measure the
            system response. This typically takes 15-30 minutes. The kiln must not be in use.
          </p>
        </CardContent>
      </Card>

      {/* Controller Information */}
      <Card>
        <CardHeader>
          <CardTitle>Controller Information</CardTitle>
          <CardDescription>Hardware and software details</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Model</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo?.model || 'Bisque ESP32-S3'}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Firmware Version</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo?.firmware || '--'}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Uptime</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo ? formatUptime(systemInfo.uptimeSeconds) : '--'}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Free Heap</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo ? `${Math.round(systemInfo.freeHeap / 1024)} KB` : '--'}
            </span>
          </div>
          <div className="flex justify-between py-2">
            <span className="text-sm font-medium">Emergency Stop</span>
            <span className="text-sm">
              {systemInfo?.emergencyStop ? (
                <Badge variant="destructive">ACTIVE</Badge>
              ) : (
                <Badge variant="secondary">Clear</Badge>
              )}
            </span>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={handleSave}>Save Settings</Button>
      </div>
    </div>
  );
}
