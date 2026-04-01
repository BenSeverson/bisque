import { useState, useCallback, useRef, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { formatUptime } from "../utils/time";
import { toErrorMessage } from "../utils/error";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Label } from "./ui/label";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";
import { Button } from "./ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { setApiToken } from "../services/api";
import { toast } from "sonner";
import { Upload, Zap, Thermometer, AlertTriangle } from "lucide-react";
import { settingsSchema, SettingsFormValues } from "../schemas/kiln";
import {
  useSettings,
  useSaveSettings,
  useSystemInfo,
  useAutotuneStatus,
  useStartAutotune,
  useStopAutotune,
  useTestRelay,
  useUploadOta,
} from "../hooks/queries";
import { api, DiagThermocouple } from "../services/api";

export function Settings() {
  const { data: settings } = useSettings();
  const saveSettings = useSaveSettings();
  const { data: systemInfo } = useSystemInfo();

  const [autotuneRunning, setAutotuneRunning] = useState(false);
  const { data: autotuneStatus } = useAutotuneStatus(autotuneRunning);
  const [autotuneSetpoint, setAutotuneSetpoint] = useState(500);

  const startAutotune = useStartAutotune();
  const stopAutotune = useStopAutotune();
  const testRelay = useTestRelay();
  const uploadOta = useUploadOta();

  // TC diagnostics
  const [tcDiag, setTcDiag] = useState<DiagThermocouple | null>(null);

  // OTA state
  const [otaFile, setOtaFile] = useState<File | null>(null);
  const [otaProgress, setOtaProgress] = useState<number | null>(null);
  const otaInputRef = useRef<HTMLInputElement>(null);

  // API token local state
  const [newToken, setNewToken] = useState("");

  // Initialize autotuneRunning from query
  useEffect(() => {
    if (autotuneStatus?.state === "running") {
      setAutotuneRunning(true);
    } else if (autotuneStatus && autotuneStatus.state !== "running" && autotuneRunning) {
      setAutotuneRunning(false);
      toast.success("Auto-tune complete");
    }
  }, [autotuneStatus, autotuneRunning]);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
  } = useForm<SettingsFormValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: settings,
  });

  // Sync form when server data arrives
  useEffect(() => {
    if (settings) reset(settings);
  }, [settings, reset]);

  const watchedSettings = watch();

  const onSubmit = async (data: SettingsFormValues) => {
    try {
      await saveSettings.mutateAsync(data);
      toast.success("Settings saved");
    } catch {
      toast.error("Failed to save settings");
    }
  };

  // Optimistic update helper for switches/selects that save immediately
  const updateField = (field: keyof SettingsFormValues, value: SettingsFormValues[keyof SettingsFormValues]) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setValue(field, value as any);
    const updated = { ...watchedSettings, [field]: value };
    saveSettings.mutate(updated);
  };

  const handleSetToken = useCallback(async () => {
    if (!newToken.trim()) return;
    const updated = { ...watchedSettings, apiToken: newToken.trim() };
    saveSettings.mutate(updated);
    setApiToken(newToken.trim());
    setNewToken("");
    toast.success("API token set");
  }, [newToken, watchedSettings, saveSettings]);

  const handleClearToken = useCallback(async () => {
    const updated = { ...watchedSettings, apiToken: "", apiTokenSet: false };
    saveSettings.mutate(updated);
    setApiToken(null);
    toast.success("API token cleared");
  }, [watchedSettings, saveSettings]);

  const handleStartAutotune = useCallback(async () => {
    try {
      await startAutotune.mutateAsync(autotuneSetpoint);
      setAutotuneRunning(true);
      toast.success("Auto-tune started");
    } catch (e) {
      toast.error(`Failed: ${toErrorMessage(e)}`);
    }
  }, [autotuneSetpoint, startAutotune]);

  const handleStopAutotune = useCallback(async () => {
    try {
      await stopAutotune.mutateAsync();
      setAutotuneRunning(false);
      toast.success("Auto-tune stopped");
    } catch {
      toast.error("Failed to stop auto-tune");
    }
  }, [stopAutotune]);

  const handleReadTC = useCallback(async () => {
    try {
      const diag = await api.getThermocoupleDiag();
      setTcDiag(diag);
    } catch {
      toast.error("Failed to read thermocouple");
    }
  }, []);

  const handleTestRelay = useCallback(async () => {
    try {
      await testRelay.mutateAsync();
      toast.success("Relay activated for 2 seconds");
    } catch {
      toast.error("Failed to test relay");
    }
  }, [testRelay]);

  const handleOtaUpload = useCallback(async () => {
    if (!otaFile) return;
    setOtaProgress(0);
    try {
      await uploadOta.mutateAsync({ file: otaFile, onProgress: (pct) => setOtaProgress(pct) });
      toast.success("Firmware uploaded — controller is rebooting");
      setOtaFile(null);
      setOtaProgress(null);
    } catch (e) {
      toast.error(`OTA failed: ${toErrorMessage(e)}`);
      setOtaProgress(null);
    }
  }, [otaFile, uploadOta]);

  const formatBytes = (bytes: number) => `${Math.round(bytes / 1024)} KB`;
  const formatHours = (seconds: number) => `${(seconds / 3600).toFixed(1)} hrs`;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold mb-2">Kiln Settings</h2>
        <p className="text-muted-foreground">
          Configure your kiln controller preferences and safety settings.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Temperature Settings */}
        <Card>
          <CardHeader>
            <CardTitle>Temperature Settings</CardTitle>
            <CardDescription>Configure temperature units, limits, and calibration</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="temp-unit">Temperature Unit</Label>
              <Select
                value={watchedSettings.tempUnit}
                onValueChange={(value: "C" | "F") => updateField("tempUnit", value)}
              >
                <SelectTrigger id="temp-unit">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="C">Celsius (°C)</SelectItem>
                  <SelectItem value="F">Fahrenheit (°F)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="max-temp">Maximum Safe Temperature (°C)</Label>
              <Input
                id="max-temp"
                type="number"
                {...register("maxSafeTemp", { valueAsNumber: true })}
              />
              <p className="text-sm text-muted-foreground">
                The kiln will shut down if this temperature is exceeded. Hardware max: 1400°C.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="tc-offset">Thermocouple Offset (°C)</Label>
              <Input
                id="tc-offset"
                type="number"
                step="0.5"
                {...register("tcOffsetC", { valueAsNumber: true })}
              />
              <p className="text-sm text-muted-foreground">
                Calibration offset added to raw TC reading. Use a reference thermometer to determine
                this value.
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
                checked={watchedSettings.alarmEnabled}
                onCheckedChange={(checked) => updateField("alarmEnabled", checked)}
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
                checked={watchedSettings.autoShutdown}
                onCheckedChange={(checked) => updateField("autoShutdown", checked)}
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
                checked={watchedSettings.notificationsEnabled}
                onCheckedChange={(checked) => updateField("notificationsEnabled", checked)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Notifications */}
        <Card>
          <CardHeader>
            <CardTitle>Webhook Notifications</CardTitle>
            <CardDescription>
              POST a JSON payload to your URL when a firing completes or errors
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="webhook-url">Webhook URL</Label>
              <Input
                id="webhook-url"
                type="url"
                placeholder="https://your-server.example.com/kiln-webhook"
                {...register("webhookUrl")}
              />
              <p className="text-sm text-muted-foreground">
                Leave blank to disable. The controller posts: event, profile, peakTemp, durationS.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Cost Estimation */}
        <Card>
          <CardHeader>
            <CardTitle>Firing Cost Estimator</CardTitle>
            <CardDescription>
              Configure element power and electricity rate for cost estimates
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="element-watts">Element Power (W)</Label>
                <Input
                  id="element-watts"
                  type="number"
                  min="0"
                  step="100"
                  placeholder="e.g. 2400"
                  {...register("elementWatts", { valueAsNumber: true })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="elec-cost">Electricity Cost ($/kWh)</Label>
                <Input
                  id="elec-cost"
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="e.g. 0.15"
                  {...register("electricityCostKwh", { valueAsNumber: true })}
                />
              </div>
            </div>
            {(watchedSettings.elementWatts ?? 0) > 0 &&
              (watchedSettings.electricityCostKwh ?? 0) > 0 && (
                <p className="text-sm text-muted-foreground">
                  At 50% average duty cycle: {watchedSettings.elementWatts! / 2000} kW × $
                  {watchedSettings.electricityCostKwh!.toFixed(2)}/kWh
                </p>
              )}
          </CardContent>
        </Card>

        {/* Save button for the form */}
        <div className="flex justify-end">
          <Button type="submit">Save Settings</Button>
        </div>
      </form>

      {/* API Security */}
      <Card>
        <CardHeader>
          <CardTitle>API Security</CardTitle>
          <CardDescription>
            Optional Bearer token to restrict API access when exposed beyond your local network
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-sm">Token status:</span>
            {watchedSettings.apiTokenSet ? (
              <Badge variant="default">Set</Badge>
            ) : (
              <Badge variant="secondary">Not set</Badge>
            )}
          </div>
          <div className="flex gap-2">
            <Input
              type="password"
              placeholder="Enter new token..."
              value={newToken}
              onChange={(e) => setNewToken(e.target.value)}
              className="flex-1"
            />
            <Button onClick={handleSetToken} disabled={!newToken.trim()}>
              Set Token
            </Button>
            {watchedSettings.apiTokenSet && (
              <Button variant="outline" onClick={handleClearToken}>
                Clear
              </Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            Once set, all API requests must include{" "}
            <code className="text-xs bg-muted px-1 py-0.5 rounded">
              Authorization: Bearer &lt;token&gt;
            </code>
            . The token is never returned by the API.
          </p>
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
                Temp: {autotuneStatus?.currentTemp?.toFixed(1)}°C /{" "}
                {autotuneStatus?.targetTemp?.toFixed(0)}°C
              </span>
            </div>
          )}

          <div className="flex items-end gap-4">
            <div className="space-y-2 flex-1">
              <Label htmlFor="autotune-setpoint">Setpoint Temperature (°C)</Label>
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
              <Button onClick={handleStartAutotune}>Start Auto-Tune</Button>
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            The auto-tune process will heat to the setpoint and oscillate around it to measure the
            system response. This typically takes 15–30 minutes. The kiln must not be in use.
          </p>
        </CardContent>
      </Card>

      {/* Diagnostics */}
      <Card>
        <CardHeader>
          <CardTitle>Diagnostics</CardTitle>
          <CardDescription>Test hardware components and verify sensor readings</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3 flex-wrap">
            <Button variant="outline" className="gap-2" onClick={handleTestRelay}>
              <Zap className="h-4 w-4" />
              Test Relay (2 s)
            </Button>
            <Button variant="outline" className="gap-2" onClick={handleReadTC}>
              <Thermometer className="h-4 w-4" />
              Read Thermocouple
            </Button>
          </div>

          {tcDiag && (
            <div className="mt-3 p-4 bg-muted/50 rounded-lg space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">TC Temperature</span>
                <span className="font-mono">{tcDiag.temperatureC.toFixed(1)}°C</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Adjusted Temperature</span>
                <span className="font-mono">{tcDiag.temperatureAdjustedC.toFixed(1)}°C</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Cold Junction</span>
                <span className="font-mono">{tcDiag.internalTempC.toFixed(1)}°C</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">TC Offset</span>
                <span className="font-mono">{tcDiag.tcOffsetC.toFixed(1)}°C</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Reading Age</span>
                <span className="font-mono">{tcDiag.readingAgeMs} ms</span>
              </div>
              {tcDiag.fault && (
                <div className="flex items-center gap-2 text-destructive mt-1">
                  <AlertTriangle className="h-4 w-4" />
                  <span>
                    Fault detected:{" "}
                    {[
                      tcDiag.openCircuit && "Open Circuit",
                      tcDiag.shortGnd && "Short to GND",
                      tcDiag.shortVcc && "Short to VCC",
                    ]
                      .filter(Boolean)
                      .join(", ")}
                  </span>
                </div>
              )}
              {!tcDiag.fault && (
                <div className="flex items-center gap-2 text-green-600 mt-1">
                  <span>No faults detected</span>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* OTA Firmware Update */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Firmware Update (OTA)
          </CardTitle>
          <CardDescription>
            Upload a new firmware binary (.bin) to update the controller over Wi-Fi
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <input
            ref={otaInputRef}
            type="file"
            accept=".bin"
            className="hidden"
            onChange={(e) => setOtaFile(e.target.files?.[0] || null)}
          />
          <div className="flex gap-3 items-center flex-wrap">
            <Button variant="outline" onClick={() => otaInputRef.current?.click()}>
              Choose File
            </Button>
            {otaFile && (
              <span className="text-sm text-muted-foreground">
                {otaFile.name} ({Math.round(otaFile.size / 1024)} KB)
              </span>
            )}
          </div>

          {otaProgress !== null && (
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Uploading firmware...</span>
                <span>{Math.round(otaProgress)}%</span>
              </div>
              <Progress value={otaProgress} />
            </div>
          )}

          <Button
            onClick={handleOtaUpload}
            disabled={!otaFile || otaProgress !== null}
            variant="default"
            className="gap-2"
          >
            <Upload className="h-4 w-4" />
            Upload Firmware
          </Button>

          <p className="text-sm text-muted-foreground">
            The controller will restart automatically after a successful upload. Do not power off
            during the update.
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
              {systemInfo?.model || "Bisque ESP32-S3"}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Firmware Version</span>
            <span className="text-sm text-muted-foreground">{systemInfo?.firmware || "--"}</span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Uptime</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo ? formatUptime(systemInfo.uptimeSeconds) : "--"}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Free Heap</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo ? formatBytes(systemInfo.freeHeap) : "--"}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Element Hours</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo ? formatHours(systemInfo.elementHoursS) : "--"}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">SPIFFS Usage</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo
                ? `${formatBytes(systemInfo.spiffsUsed)} / ${formatBytes(systemInfo.spiffsTotal)}`
                : "--"}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Last Error Code</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo
                ? systemInfo.lastErrorCode === 0
                  ? "None"
                  : `E${systemInfo.lastErrorCode}`
                : "--"}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b">
            <span className="text-sm font-medium">Emergency Stop</span>
            <span className="text-sm">
              {systemInfo?.emergencyStop ? (
                <Badge variant="destructive">ACTIVE</Badge>
              ) : (
                <Badge variant="secondary">Clear</Badge>
              )}
            </span>
          </div>
          <div className="flex justify-between py-2">
            <span className="text-sm font-medium">Board Temperature</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo?.boardTempC != null ? `${systemInfo.boardTempC.toFixed(1)}°C` : "--"}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
