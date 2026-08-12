import { useState, useCallback, useRef, useEffect } from "react";
import { useForm, useWatch, type Path, type PathValue } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { formatUptime } from "../utils/time";
import { toErrorMessage } from "../utils/error";
import { commitApiTokenChange, API_TOKEN_MAX_LENGTH } from "../utils/apiToken";
import {
  applyAutotuneStatus,
  beginAutotuneSession,
  endAutotuneSession,
  isAutotunePolling,
  IDLE_AUTOTUNE_SESSION,
  type AutotuneSession,
} from "../utils/autotuneSession";
import { prepareSettingsPatch } from "../utils/settingsPatch";
import { preparePidGains, formatGain, type PidGainsDraft } from "../utils/pidGains";
import { prepareAutotuneRequest, AUTOTUNE_DEFAULT_HYSTERESIS_C } from "../utils/autotuneRequest";
import {
  prepareRelayDuration,
  RELAY_TEST_MIN_SECONDS,
  RELAY_TEST_MAX_SECONDS,
  RELAY_TEST_DEFAULT_SECONDS,
} from "../utils/relayTest";
import { describeFiringError, emergencyStopExplanation } from "../utils/firingError";
import { ASSUMED_DUTY_CYCLE, costPerHourAtFullPower, formatCost } from "../utils/cost";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Label } from "./ui/label";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";
import { Button } from "./ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { setApiToken } from "../services/api";
import { toast } from "sonner";
import {
  Upload,
  Zap,
  Thermometer,
  AlertTriangle,
  RefreshCw,
  Download,
  Power,
  HardDrive,
  Undo2,
  ShieldCheck,
} from "lucide-react";
import { settingsSchema, SettingsFormValues } from "../schemas/kiln";
import { TemperatureField } from "./TemperatureField";
import {
  formatTemp,
  toDisplayTemp,
  fromDisplayTemp,
  toDisplayRate,
  fromDisplayRate,
  unitLabel,
} from "../utils/temperature";
import {
  useSettings,
  useSaveSettings,
  useSystemInfo,
  useAutotuneStatus,
  useStartAutotune,
  useStopAutotune,
  usePidGains,
  useSavePidGains,
  useTestRelay,
  useReboot,
  useUploadOta,
  useCheckOta,
  useInstallOta,
  useOtaStatus,
  useResetOtaStatus,
  useConfirmOta,
  useRollbackOta,
} from "../hooks/queries";
import { api, DiagThermocouple, OtaCheckResponse } from "../services/api";
import { kilnWS } from "../services/websocket";
import { useKilnStore } from "../stores/kilnStore";
import { WifiCard } from "./WifiCard";
import { BrowserAlertsCard } from "./BrowserAlertsCard";
import { DemoFaultControl } from "./DemoFaultControl";

export function Settings() {
  const { data: settings } = useSettings();
  const saveSettings = useSaveSettings();
  const { data: systemInfo } = useSystemInfo();

  const [autotuneSession, setAutotuneSession] = useState<AutotuneSession>(IDLE_AUTOTUNE_SESSION);
  const autotuneRunning = isAutotunePolling(autotuneSession);
  const {
    data: autotuneStatus,
    dataUpdatedAt,
    errorUpdatedAt,
  } = useAutotuneStatus(autotuneRunning);
  const [autotuneSetpoint, setAutotuneSetpoint] = useState(500);
  // The relay band the tune oscillates across, in Celsius like the API. Exposed
  // rather than pinned to the firmware default because it is the one knob that
  // trades tune duration against gain quality on a given kiln (#178).
  const [autotuneHysteresis, setAutotuneHysteresis] = useState(AUTOTUNE_DEFAULT_HYSTERESIS_C);

  const startAutotune = useStartAutotune();
  const stopAutotune = useStopAutotune();

  // PID gains, editable by hand (#182). `gainsDraft` is non-null exactly while
  // the editor is open, so it doubles as the open/closed flag — there is no
  // second boolean to keep in step with it.
  const { data: pidGains, refetch: refetchPidGains } = usePidGains();
  const savePidGains = useSavePidGains();
  const [gainsDraft, setGainsDraft] = useState<PidGainsDraft | null>(null);
  // The firmware answers POST /pid with 409 while the control loop is running,
  // because the integrator wound up under the old Ki. Mirror that here off the
  // live WebSocket state, so the editor is closed before the user types three
  // numbers rather than after.
  const firingActive = useKilnStore((s) => s.firingProgress.isActive);
  const kilnBusy = firingActive || autotuneRunning;
  // For the auto-tune band checks. `statusObserved` gates the reading because
  // the store seeds currentTemp to a synthetic 20 °C — validating against that
  // would reject a legitimate low-setpoint tune on a cold page load.
  const currentTemp = useKilnStore((s) => s.firingProgress.currentTemp);
  const statusObserved = useKilnStore((s) => s.statusObserved);
  const testRelay = useTestRelay();
  const [relayDurationS, setRelayDurationS] = useState(RELAY_TEST_DEFAULT_SECONDS);
  const reboot = useReboot();
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);
  const uploadOta = useUploadOta();
  const checkOta = useCheckOta();
  const installOta = useInstallOta();
  // Firmware partitions (#177). Not fetched in the demo: the card that reads it
  // is hardware-only, and the mock kiln has no partition table to describe.
  const {
    data: otaStatus,
    isError: otaStatusFailed,
    isFetching: otaStatusFetching,
    refetch: refetchOtaStatus,
  } = useOtaStatus(!__DEMO__);
  const resetOtaStatus = useResetOtaStatus();
  const confirmOta = useConfirmOta();
  const rollbackOta = useRollbackOta();
  const [rollbackConfirmOpen, setRollbackConfirmOpen] = useState(false);

  // TC diagnostics
  const [tcDiag, setTcDiag] = useState<DiagThermocouple | null>(null);

  // OTA state
  const [otaFile, setOtaFile] = useState<File | null>(null);
  const [otaProgress, setOtaProgress] = useState<number | null>(null);
  const otaInputRef = useRef<HTMLInputElement>(null);
  const [otaCheck, setOtaCheck] = useState<OtaCheckResponse | null>(null);
  const [otaInstalling, setOtaInstalling] = useState(false);
  const [otaInstallPct, setOtaInstallPct] = useState<number | null>(null);
  // Either OTA path in flight: a manifest install, or a manual binary upload.
  const otaBusy = otaInstalling || otaProgress !== null;

  // API token local state
  const [newToken, setNewToken] = useState("");

  // Fold each polled status frame into the auto-tune session, and toast once on
  // the transition out of a run. This is a genuine external-system sync (the
  // session gates the polling query), so it can't be derived during render —
  // deriving it would be circular with the query's refetch interval. Hence the
  // targeted set-state-in-effect exemption.
  //
  // The frame's fetch time — not "now" — is what applyAutotuneStatus judges,
  // so the cached pre-start frame can no longer end the run it never saw.
  const observedAt = Math.max(dataUpdatedAt, errorUpdatedAt);
  // A failed fetch also advances errorUpdatedAt, so tell applyAutotuneStatus
  // whether the newest settle was real data — otherwise an unreachable kiln
  // ages out a pending start and takes the Stop button with it.
  const statusArrived = dataUpdatedAt >= errorUpdatedAt;
  useEffect(() => {
    const { session, outcome } = applyAutotuneStatus(
      autotuneSession,
      autotuneStatus?.state,
      observedAt,
      { succeeded: statusArrived },
    );
    if (session !== autotuneSession) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- see comment above
      setAutotuneSession(session);
    }
    if (outcome === "completed") {
      toast.success("Auto-tune complete — new PID gains saved");
      // The tune wrote gains the device now holds; the card shows the cached
      // pre-tune ones until this lands.
      refetchPidGains();
    } else if (outcome === "failed") {
      toast.error("Auto-tune failed to measure usable gains — PID gains are unchanged");
    } else if (outcome === "stopped") {
      toast.warning("Auto-tune ended before it finished — PID gains are unchanged");
    } else if (outcome === "not-started") {
      toast.error("The controller did not start the auto-tune");
    }
  }, [autotuneSession, autotuneStatus?.state, observedAt, statusArrived, refetchPidGains]);

  const { register, handleSubmit, setValue, reset, control, getValues } =
    useForm<SettingsFormValues>({
      resolver: zodResolver(settingsSchema),
      defaultValues: settings,
    });

  // Sync form when server data arrives. keepDirtyValues prevents a refetch (e.g.
  // on window focus) from stomping unsaved edits the user is in the middle of.
  useEffect(() => {
    if (settings) reset(settings, { keepDirtyValues: true });
  }, [settings, reset]);

  // Reactive form snapshot for display. useWatch (not the form's watch())
  // keeps this React Compiler-friendly; imperative reads in handlers use
  // getValues() instead. Mutations that need the full settings shape build
  // their payload from getValues().
  const watchedSettings = useWatch({ control });
  const unit = watchedSettings.tempUnit ?? "F";

  // Priced off the live form values, not the saved settings, so the preview
  // tracks what is being typed rather than waiting for a save.
  const fullPowerCostPerHour = costPerHourAtFullPower({
    elementWatts: watchedSettings.elementWatts ?? 0,
    electricityCostKwh: watchedSettings.electricityCostKwh ?? 0,
  });

  const onSubmit = async (data: SettingsFormValues) => {
    try {
      await saveSettings.mutateAsync(data);
      toast.success("Settings saved");
    } catch {
      toast.error("Failed to save settings");
    }
  };

  // Optimistic update helper for switches/selects that save immediately.
  //
  // These bypass handleSubmit, so the payload is validated here instead: a
  // temperature field the user has cleared mid-edit holds NaN, which reached
  // the firmware as null and was stored as 0 — turning "Maximum Safe
  // Temperature" into a limit that rejects every firing. On a refused save the
  // control is left alone, so it springs back rather than displaying a state
  // the controller never took.
  function updateField<K extends Path<SettingsFormValues> & keyof SettingsFormValues>(
    field: K,
    value: SettingsFormValues[K],
  ) {
    const patch = prepareSettingsPatch(getValues(), field, value);
    if (!patch.ok) {
      toast.error(`Not saved: ${patch.message}`);
      return;
    }
    setValue(field, value as PathValue<SettingsFormValues, K>);
    saveSettings.mutate(patch.settings);
  }

  const handleSetToken = useCallback(async () => {
    const token = newToken.trim();
    if (!token) return;
    try {
      await commitApiTokenChange(
        { kind: "set", token },
        (apiToken) => saveSettings.mutateAsync({ ...getValues(), apiToken }),
        setApiToken,
      );
      setNewToken("");
      toast.success("API token set");
    } catch (e) {
      // Report the real outcome: the previous fire-and-forget mutate() toasted
      // success even when the save 401'd, hiding the lockout.
      toast.error(`Failed to set API token: ${toErrorMessage(e)}`);
    }
  }, [newToken, getValues, saveSettings]);

  const handleClearToken = useCallback(async () => {
    try {
      await commitApiTokenChange(
        { kind: "clear" },
        (apiToken) => saveSettings.mutateAsync({ ...getValues(), apiToken, apiTokenSet: false }),
        setApiToken,
      );
      toast.success("API token cleared");
    } catch (e) {
      toast.error(`Failed to clear API token: ${toErrorMessage(e)}`);
    }
  }, [getValues, saveSettings]);

  const handleStartAutotune = useCallback(async () => {
    const prepared = prepareAutotuneRequest(autotuneSetpoint, autotuneHysteresis, {
      currentTemp: statusObserved ? currentTemp : undefined,
      maxSafeTemp: settings?.maxSafeTemp,
      formatTemp: (c) => formatTemp(c, unit),
    });
    if (!prepared.ok) {
      toast.error(prepared.message);
      return;
    }
    try {
      await startAutotune.mutateAsync({
        setpoint: prepared.setpoint,
        hysteresis: prepared.hysteresis,
      });
      // Pending until a *fresh* status frame confirms it: the firmware only
      // queues the start command, so the next poll or two may still read idle.
      setAutotuneSession(beginAutotuneSession(Date.now()));
      toast.success("Auto-tune started");
    } catch (e) {
      toast.error(`Failed: ${toErrorMessage(e)}`);
    }
  }, [
    autotuneSetpoint,
    autotuneHysteresis,
    startAutotune,
    statusObserved,
    currentTemp,
    settings?.maxSafeTemp,
    unit,
  ]);

  const handleStopAutotune = useCallback(async () => {
    try {
      await stopAutotune.mutateAsync();
      setAutotuneSession(endAutotuneSession(Date.now()));
      toast.success("Auto-tune stopped");
    } catch {
      toast.error("Failed to stop auto-tune");
    }
  }, [stopAutotune]);

  const handleEditGains = useCallback(() => {
    if (!pidGains) return;
    setGainsDraft({
      kp: formatGain(pidGains.kp),
      ki: formatGain(pidGains.ki),
      kd: formatGain(pidGains.kd),
    });
  }, [pidGains]);

  const handleRestoreDefaultGains = useCallback(() => {
    if (!pidGains) return;
    // Fill the fields rather than saving outright — restoring defaults throws
    // away a tuning run, so it should still take a deliberate Save.
    setGainsDraft({
      kp: formatGain(pidGains.defaults.kp),
      ki: formatGain(pidGains.defaults.ki),
      kd: formatGain(pidGains.defaults.kd),
    });
  }, [pidGains]);

  const handleSaveGains = useCallback(async () => {
    if (!gainsDraft) return;
    const prepared = preparePidGains(gainsDraft, pidGains?.limits);
    if (!prepared.ok) {
      toast.error(`Not saved: ${prepared.message}`);
      return;
    }
    try {
      const stored = await savePidGains.mutateAsync(prepared.gains);
      setGainsDraft(null);
      toast.success(
        `PID gains saved — Kp ${formatGain(stored.kp)}, Ki ${formatGain(stored.ki)}, Kd ${formatGain(stored.kd)}`,
      );
    } catch (e) {
      // Leave the editor open with the entered values, so a 409 ("kiln is
      // busy") doesn't cost the user what they typed.
      toast.error(`Failed to save PID gains: ${toErrorMessage(e)}`);
    }
  }, [gainsDraft, pidGains?.limits, savePidGains]);

  const handleReadTC = useCallback(async () => {
    try {
      const diag = await api.getThermocoupleDiag();
      setTcDiag(diag);
    } catch {
      toast.error("Failed to read thermocouple");
    }
  }, []);

  const handleTestRelay = useCallback(async () => {
    const prepared = prepareRelayDuration(relayDurationS);
    if (!prepared.ok) {
      toast.error(prepared.message);
      return;
    }
    try {
      // Report the duration the controller echoes, not the one requested: the
      // firmware clamps silently, so its answer is the only honest number here.
      const resp = await testRelay.mutateAsync(prepared.seconds);
      toast.success(`Relay activated for ${resp.durationSeconds} seconds`);
    } catch (e) {
      // 409 while a firing, delay or another relay test holds the SSR.
      toast.error(`Failed to test relay: ${toErrorMessage(e)}`);
    }
  }, [relayDurationS, testRelay]);

  const handleRestart = useCallback(async () => {
    setRestartConfirmOpen(false);
    try {
      await reboot.mutateAsync();
      toast.success("Restarting — reload this page once the controller is back.");
    } catch (e) {
      // handle_reboot() refuses with 409 while a firing or relay test is
      // running, which is the likely failure rather than a dropped request.
      toast.error(`Restart refused: ${toErrorMessage(e)}`);
    }
  }, [reboot]);

  const handleOtaUpload = useCallback(async () => {
    if (!otaFile) return;
    setOtaProgress(0);
    try {
      await uploadOta.mutateAsync({ file: otaFile, onProgress: (pct) => setOtaProgress(pct) });
      toast.success("Firmware uploaded — controller is rebooting");
      // The slot, version and image state on screen belong to the firmware
      // just replaced, and the new image may be pending verification.
      resetOtaStatus();
      setOtaFile(null);
      setOtaProgress(null);
    } catch (e) {
      toast.error(`OTA failed: ${toErrorMessage(e)}`);
      setOtaProgress(null);
    }
  }, [otaFile, uploadOta, resetOtaStatus]);

  const handleCheckOta = useCallback(async () => {
    setOtaCheck(null);
    try {
      const result = await checkOta.mutateAsync();
      setOtaCheck(result);
      if (!result.updateAvailable) {
        toast.success(`You're on the latest version (${result.current})`);
      }
    } catch (e) {
      toast.error(`Update check failed: ${toErrorMessage(e)}`);
    }
  }, [checkOta]);

  const handleInstallOta = useCallback(async () => {
    setOtaInstalling(true);
    setOtaInstallPct(0);
    try {
      await installOta.mutateAsync();
    } catch (e) {
      toast.error(`Update failed: ${toErrorMessage(e)}`);
      setOtaInstalling(false);
      setOtaInstallPct(null);
    }
  }, [installOta]);

  const handleConfirmFirmware = useCallback(async () => {
    try {
      const resp = await confirmOta.mutateAsync();
      toast.success(resp.message);
    } catch (e) {
      toast.error(`Could not confirm the firmware: ${toErrorMessage(e)}`);
    }
  }, [confirmOta]);

  const handleRollback = useCallback(async () => {
    setRollbackConfirmOpen(false);
    try {
      const { acknowledged } = await rollbackOta.mutateAsync();
      if (acknowledged) {
        toast.success("Rolling back — reload this page once the controller is back.");
      } else {
        /* The request never got an answer. Usually that is the controller
           rebooting mid-reply, which is the rollback working — but a kiln that
           had already dropped off the network produces exactly the same
           TypeError, and claiming success there would be a guess presented as
           a fact. Say what is known and point at the check that settles it. */
        toast.warning(
          "Rollback sent, but the controller stopped answering before it replied. " +
            "That is expected while it reboots — retry the partition state in a moment " +
            "and check the running version.",
        );
      }
      /* Both outcomes leave the cached slot, version and rollbackAvailable
         describing an image the controller is in the middle of abandoning.
         Kept, they would re-enable Roll Back off a stale `true` the moment the
         mutation settled, and — because the card only offers Retry when it has
         no data — hide the very control the warning above tells the user to
         reach for. This is what the install and upload paths do; a rollback is
         the same reboot. Not on the error path below: a 400 or 409 means the
         firmware did not change, so the state on screen is still correct. */
      resetOtaStatus();
    } catch (e) {
      toast.error(`Rollback refused: ${toErrorMessage(e)}`);
    }
  }, [rollbackOta, resetOtaStatus]);

  // Stream OTA install progress from the WebSocket while an install runs.
  useEffect(() => {
    if (!otaInstalling) return;
    return kilnWS.subscribe((msg) => {
      if (msg.type === "ota_progress") {
        setOtaInstallPct(msg.data.percent);
      } else if (msg.type === "ota_complete") {
        setOtaInstallPct(100);
        toast.success("Update installed — controller is rebooting");
        resetOtaStatus();
      } else if (msg.type === "ota_error") {
        toast.error(`Update failed: ${msg.data.message}`);
        setOtaInstalling(false);
        setOtaInstallPct(null);
      }
    });
  }, [otaInstalling, resetOtaStatus]);

  const formatBytes = (bytes: number) => {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${bytes} B`;
  };
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
              <Label htmlFor="max-temp">Maximum Safe Temperature ({unitLabel(unit)})</Label>
              <TemperatureField id="max-temp" control={control} name="maxSafeTemp" unit={unit} />
              <p className="text-sm text-muted-foreground">
                The kiln will shut down if this temperature is exceeded. Hardware max:{" "}
                {formatTemp(1400, unit)}.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="tc-offset">Thermocouple Offset ({unitLabel(unit)})</Label>
              <TemperatureField
                id="tc-offset"
                control={control}
                name="tcOffsetC"
                unit={unit}
                kind="delta"
                digits={1}
                step="0.5"
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

            <div className="space-y-2">
              <Label htmlFor="lid-mode">Lid Switch</Label>
              <Select
                value={watchedSettings.lidMode ?? "pause"}
                onValueChange={(value: "warn" | "pause" | "interlock") =>
                  updateField("lidMode", value)
                }
              >
                <SelectTrigger id="lid-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="warn">Warn only</SelectItem>
                  <SelectItem value="pause">Pause firing</SelectItem>
                  <SelectItem value="interlock">Cut elements, keep running</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-sm text-muted-foreground">
                {watchedSettings.lidMode === "warn" &&
                  "Show the lid position, but never interrupt a firing."}
                {(watchedSettings.lidMode ?? "pause") === "pause" &&
                  "Cut the elements and hold the program while the lid is open, resuming automatically when it closes. Recommended for ceramics."}
                {watchedSettings.lidMode === "interlock" &&
                  "Cut the elements but keep the program running. Recommended for heat treating, where the door is opened at temperature by design."}
              </p>
              <p className="text-sm text-muted-foreground">
                Not a substitute for a mechanical interlock wired into the element circuit.
              </p>
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
            {/* Lives here, not under Safety Settings where it used to sit as
                "Notifications — receive notifications for important events".
                That copy promised alerts of every kind while the flag gates
                exactly one thing: the webhook POST two cards below it
                (api_handlers.c, handle_firing_event). Browser alerts are a
                separate, browser-local setting (#185). */}
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label htmlFor="notifications">Send webhooks</Label>
                <p className="text-sm text-muted-foreground">
                  Master switch. Off means nothing is posted, even with a URL saved below.
                </p>
              </div>
              <Switch
                id="notifications"
                checked={watchedSettings.notificationsEnabled}
                onCheckedChange={(checked) => updateField("notificationsEnabled", checked)}
              />
            </div>

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
                  placeholder="e.g. 5000"
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
            {fullPowerCostPerHour === null ? (
              <p className="text-sm text-muted-foreground">
                Set both to see estimated firing costs on profiles and history records.
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                {(watchedSettings.elementWatts! / 1000).toFixed(1)} kW × $
                {watchedSettings.electricityCostKwh!.toFixed(2)}/kWh ={" "}
                <span className="font-medium text-foreground">
                  {formatCost(fullPowerCostPerHour)}
                </span>{" "}
                per hour at full power. Profiles and history records show an estimated cost at{" "}
                {Math.round(ASSUMED_DUTY_CYCLE * 100)}% average duty.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Save button for the form */}
        <div className="flex justify-end">
          <Button type="submit">Save Settings</Button>
        </div>
      </form>

      {/* Browser-local, so it sits outside the form and its Save button. */}
      <BrowserAlertsCard />

      {/* Wi-Fi Network — hidden in the demo (provisioning needs hardware) */}
      {!__DEMO__ && <WifiCard />}

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
              /* Matches the firmware's api_token[64]; without this the device
                 would reject (previously: silently truncate) a longer token. */
              maxLength={API_TOKEN_MAX_LENGTH}
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
          {/* Current gains. Read from GET /pid, which is always available —
              these used to come from the auto-tune status query, which only
              polls during a run, so the gains were invisible unless you had
              just tuned (#182). */}
          <div className="space-y-3 p-3 bg-muted/50 rounded-lg">
            {gainsDraft ? (
              <div className="grid grid-cols-3 gap-4">
                {(["kp", "ki", "kd"] as const).map((key) => (
                  <div key={key} className="space-y-1">
                    <Label htmlFor={`pid-${key}`} className="text-xs text-muted-foreground">
                      {key === "kp" ? "Kp" : key === "ki" ? "Ki" : "Kd"}
                    </Label>
                    <Input
                      id={`pid-${key}`}
                      type="number"
                      inputMode="decimal"
                      step="any"
                      min={pidGains?.limits.min}
                      max={pidGains?.limits.max}
                      className="font-mono"
                      value={gainsDraft[key]}
                      onChange={(e) =>
                        setGainsDraft((draft) =>
                          draft ? { ...draft, [key]: e.target.value } : draft,
                        )
                      }
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">Kp</p>
                  <p className="text-lg font-mono">{pidGains ? formatGain(pidGains.kp) : "--"}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Ki</p>
                  <p className="text-lg font-mono">{pidGains ? formatGain(pidGains.ki) : "--"}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Kd</p>
                  <p className="text-lg font-mono">{pidGains ? formatGain(pidGains.kd) : "--"}</p>
                </div>
              </div>
            )}

            <div className="flex gap-2 flex-wrap">
              {gainsDraft ? (
                <>
                  <Button size="sm" onClick={handleSaveGains} disabled={savePidGains.isPending}>
                    {savePidGains.isPending ? "Saving..." : "Save Gains"}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setGainsDraft(null)}>
                    Cancel
                  </Button>
                  <Button size="sm" variant="ghost" onClick={handleRestoreDefaultGains}>
                    Restore Defaults
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleEditGains}
                  disabled={!pidGains || kilnBusy}
                >
                  Edit Manually
                </Button>
              )}
            </div>

            <p className="text-xs text-muted-foreground">
              {gainsDraft
                ? "Kp or Ki must be above zero. Saved values are rounded to four decimals, which is what the controller stores."
                : kilnBusy
                  ? "Gains can only be changed while the kiln is idle — changing them mid-firing would step the element duty cycle."
                  : "Enter gains directly if you already have known-good values for this kiln — no need to run a tune."}
            </p>
          </div>

          {autotuneRunning && (
            <div className="flex items-center gap-2">
              <Badge variant="default">Running</Badge>
              <span className="text-sm text-muted-foreground">
                Temp:{" "}
                {autotuneStatus?.currentTemp != null
                  ? formatTemp(autotuneStatus.currentTemp, unit, 1)
                  : "--"}{" "}
                /{" "}
                {autotuneStatus?.targetTemp != null
                  ? formatTemp(autotuneStatus.targetTemp, unit)
                  : "--"}
              </span>
            </div>
          )}

          <div className="flex items-end gap-4 flex-wrap">
            <div className="space-y-2 flex-1 min-w-40">
              <Label htmlFor="autotune-setpoint">Setpoint Temperature ({unitLabel(unit)})</Label>
              <Input
                id="autotune-setpoint"
                type="number"
                value={Number(toDisplayTemp(autotuneSetpoint, unit).toFixed(0))}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setAutotuneSetpoint(Number.isFinite(v) ? fromDisplayTemp(v, unit) : 0);
                }}
                disabled={autotuneRunning}
              />
            </div>
            {/* A delta, so it scales by 9/5 with no offset — hence toDisplayRate
                rather than toDisplayTemp. */}
            <div className="space-y-2 w-32">
              <Label htmlFor="autotune-hysteresis">Relay Band (±{unitLabel(unit)})</Label>
              <Input
                id="autotune-hysteresis"
                type="number"
                min={0}
                step="any"
                value={Number(toDisplayRate(autotuneHysteresis, unit).toFixed(1))}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setAutotuneHysteresis(Number.isFinite(v) ? fromDisplayRate(v, unit) : 0);
                }}
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
          <p className="text-sm text-muted-foreground">
            The relay band is how far above and below the setpoint the element switches. The default
            of ±{toDisplayRate(AUTOTUNE_DEFAULT_HYSTERESIS_C, unit).toFixed(0)}
            {unitLabel(unit)} suits most kilns; widen it if thermocouple noise makes the relay
            chatter, narrow it for a tighter-tuned but slower run.
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
          <div className="flex gap-3 flex-wrap items-end">
            {/* Relay test needs hardware — hidden in the demo. Its duration was
                an API parameter with no control behind it (#178); the bounds are
                the firmware's own silent clamp. */}
            {!__DEMO__ && (
              <>
                <div className="space-y-2 w-28">
                  <Label htmlFor="relay-test-duration">Pulse (s)</Label>
                  <Input
                    id="relay-test-duration"
                    type="number"
                    min={RELAY_TEST_MIN_SECONDS}
                    max={RELAY_TEST_MAX_SECONDS}
                    step={1}
                    value={relayDurationS}
                    // parseFloat, not parseInt: truncating here would hide a
                    // typed "1.9" from prepareRelayDuration's whole-second rule
                    // and fire a 1-second pulse under a success toast.
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      setRelayDurationS(Number.isFinite(v) ? v : 0);
                    }}
                  />
                </div>
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={handleTestRelay}
                  disabled={testRelay.isPending}
                >
                  <Zap className="h-4 w-4" />
                  Test Relay
                </Button>
              </>
            )}
            <Button variant="outline" className="gap-2" onClick={handleReadTC}>
              <Thermometer className="h-4 w-4" />
              Read Thermocouple
            </Button>
            {/* The mirror image of Test Relay: hardware-only there, simulator-only
                here. A demo kiln never fails on its own, so without this the
                error UI below is unreachable by clicking (#239). */}
            {__DEMO__ && <DemoFaultControl />}
          </div>

          {tcDiag && (
            <div className="mt-3 p-4 bg-muted/50 rounded-lg space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">TC Temperature</span>
                <span className="font-mono">{formatTemp(tcDiag.temperatureC, unit, 1)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Adjusted Temperature</span>
                <span className="font-mono">
                  {formatTemp(tcDiag.temperatureAdjustedC, unit, 1)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Cold Junction</span>
                <span className="font-mono">{formatTemp(tcDiag.internalTempC, unit, 1)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">TC Offset</span>
                <span className="font-mono">
                  {toDisplayRate(tcDiag.tcOffsetC, unit).toFixed(1)}
                  {unitLabel(unit)}
                </span>
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

          {/* Restart. POST /reboot has always existed — the Wi-Fi save flow
              reboots through it — but nothing offered it on its own, so clearing
              a wedged controller meant pulling the plug (#178). Hardware-only:
              there is nothing to restart in the demo. */}
          {!__DEMO__ && (
            <div className="border-t pt-4 flex items-end justify-between gap-4 flex-wrap">
              <div className="space-y-1">
                <p className="text-sm font-medium">Restart Controller</p>
                <p className="text-sm text-muted-foreground">
                  Reboots the controller. Settings, profiles and firing history are kept. Refused
                  while a firing or relay test is running.
                </p>
              </div>
              {/* Also blocked during an update. handle_reboot() only guards
                  against a firing or relay test — not ota_is_busy() — so
                  restarting from this very page would otherwise discard a
                  download in progress a few cards further down. */}
              <Button
                variant="outline"
                className="gap-2"
                onClick={() => setRestartConfirmOpen(true)}
                disabled={reboot.isPending || kilnBusy || otaBusy}
              >
                <Power className="h-4 w-4" />
                {reboot.isPending ? "Restarting..." : "Restart"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Firmware update & manual OTA — hidden in the demo (require hardware) */}
      {!__DEMO__ && (
        <>
          {/* Firmware Update — check GitHub for a new release */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <RefreshCw className="h-5 w-5" />
                Check for Updates
              </CardTitle>
              <CardDescription>
                Check GitHub for a newer firmware release and install it over Wi-Fi
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-between py-2 border-b">
                <span className="text-sm font-medium">Current Version</span>
                <span className="text-sm text-muted-foreground">
                  {systemInfo?.firmware || "--"}
                </span>
              </div>

              {otaCheck?.updateAvailable && (
                <div className="flex justify-between py-2 border-b">
                  <span className="text-sm font-medium">Available Version</span>
                  <Badge>{otaCheck.latest}</Badge>
                </div>
              )}

              {otaCheck && !otaCheck.updateAvailable && (
                <p className="text-sm text-muted-foreground">You're running the latest version.</p>
              )}

              {otaInstallPct !== null && (
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span>Installing update...</span>
                    <span>{Math.round(otaInstallPct)}%</span>
                  </div>
                  <Progress value={otaInstallPct} />
                </div>
              )}

              <div className="flex gap-3 flex-wrap">
                <Button
                  variant="outline"
                  onClick={handleCheckOta}
                  disabled={checkOta.isPending || otaInstalling}
                  className="gap-2"
                >
                  <RefreshCw className="h-4 w-4" />
                  {checkOta.isPending ? "Checking..." : "Check for Updates"}
                </Button>

                {otaCheck?.updateAvailable && (
                  <Button
                    onClick={handleInstallOta}
                    disabled={otaInstalling}
                    variant="default"
                    className="gap-2"
                  >
                    <Download className="h-4 w-4" />
                    Install {otaCheck.latest}
                  </Button>
                )}
              </div>

              <p className="text-sm text-muted-foreground">
                The controller restarts automatically after installing. Do not power off during the
                update. Updates are blocked while a firing is active.
              </p>
            </CardContent>
          </Card>

          {/* OTA Firmware Update — manual binary upload */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Upload className="h-5 w-5" />
                Manual Firmware Update
              </CardTitle>
              <CardDescription>
                Upload a firmware binary (.bin) directly to update the controller over Wi-Fi
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
                The controller will restart automatically after a successful upload. Do not power
                off during the update.
              </p>
            </CardContent>
          </Card>

          {/* Firmware partitions — the other half of the OTA story (#177).
              Every update writes to the inactive slot, so the image it replaced
              is still on the device; without this card the only way back from a
              bad update was a USB cable. */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <HardDrive className="h-5 w-5" />
                Firmware Partitions
              </CardTitle>
              <CardDescription>
                Which image the controller booted, and how to return to the previous one
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Three states, and the difference matters: everything below —
                  above all "no previous firmware to roll back to" — is a claim
                  about the device that is only true once a fetch has actually
                  landed. Rendered off `otaStatus?.` alone, a still-loading or
                  failed request asserted the same sentence as a successful
                  `rollbackAvailable: false`, and printed it directly beneath
                  "Could not read the partition state". */}
              {!otaStatus && otaStatusFailed && (
                <div className="flex items-end justify-between gap-4 flex-wrap">
                  <p className="text-sm text-muted-foreground">
                    Could not read the partition state from the controller. It may be restarting
                    after an update, or running firmware older than this page.
                  </p>
                  <Button
                    variant="outline"
                    className="gap-2"
                    onClick={() => refetchOtaStatus()}
                    disabled={otaStatusFetching}
                  >
                    <RefreshCw className="h-4 w-4" />
                    {otaStatusFetching ? "Checking..." : "Retry"}
                  </Button>
                </div>
              )}

              {!otaStatus && !otaStatusFailed && (
                <p className="text-sm text-muted-foreground">Reading the partition state...</p>
              )}

              {otaStatus && (
                <div className="space-y-0">
                  <div className="flex justify-between py-2 border-b">
                    <span className="text-sm font-medium">Running Slot</span>
                    <span className="text-sm text-muted-foreground font-mono">
                      {otaStatus.running?.label ?? "--"}
                    </span>
                  </div>
                  <div className="flex justify-between py-2 border-b">
                    <span className="text-sm font-medium">Running Version</span>
                    <span className="text-sm text-muted-foreground">
                      {otaStatus.running?.version || "--"}
                    </span>
                  </div>
                  {/* The boot slot is what the *next* reboot will run. It only
                      differs from the running slot between a rollback request
                      and the reboot that carries it out, which is exactly when
                      a user needs to see it. */}
                  <div className="flex justify-between py-2 border-b">
                    <span className="text-sm font-medium">Boots Next From</span>
                    <span className="text-sm text-muted-foreground font-mono">
                      {otaStatus.bootPartition ?? "--"}
                    </span>
                  </div>
                  <div className="flex justify-between py-2 items-center">
                    <span className="text-sm font-medium">Image State</span>
                    <span className="text-sm">
                      {otaStatus.pendingVerify ? (
                        <Badge variant="destructive">Pending verification</Badge>
                      ) : (
                        <Badge variant="secondary">{otaStatus.running?.state ?? "unknown"}</Badge>
                      )}
                    </span>
                  </div>
                </div>
              )}

              {/* ota_confirm.c normally confirms an image on its own after a
                  healthy-uptime window, so this only shows up inside that
                  window — or when the automatic pass did not run. Offering it
                  manually means a user watching a fresh update land does not
                  have to wait out the timer to make it permanent. */}
              {otaStatus?.pendingVerify && (
                <div className="border-t pt-4 flex items-end justify-between gap-4 flex-wrap">
                  <div className="space-y-1">
                    <p className="text-sm font-medium">Confirm This Firmware</p>
                    <p className="text-sm text-muted-foreground">
                      This image has not been marked valid yet. Until it is, the controller reverts
                      to the previous firmware if it reboots.
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    className="gap-2"
                    onClick={handleConfirmFirmware}
                    disabled={confirmOta.isPending}
                  >
                    <ShieldCheck className="h-4 w-4" />
                    {confirmOta.isPending ? "Confirming..." : "Confirm"}
                  </Button>
                </div>
              )}

              {otaStatus && (
                <div className="border-t pt-4 flex items-end justify-between gap-4 flex-wrap">
                  <div className="space-y-1">
                    <p className="text-sm font-medium">Roll Back Firmware</p>
                    <p className="text-sm text-muted-foreground">
                      {otaStatus.rollbackAvailable
                        ? "Reboots into the firmware that was running before the last update. Settings, profiles and firing history are kept."
                        : "No previous firmware to roll back to — the other slot is empty or was never booted successfully."}
                    </p>
                  </div>
                  {/* handle_ota_rollback() refuses with 409 while a firing runs,
                      and rebooting mid-firing would abandon the load anyway. */}
                  <Button
                    variant="destructive"
                    className="gap-2"
                    onClick={() => setRollbackConfirmOpen(true)}
                    disabled={
                      !otaStatus.rollbackAvailable || rollbackOta.isPending || kilnBusy || otaBusy
                    }
                  >
                    <Undo2 className="h-4 w-4" />
                    {rollbackOta.isPending ? "Rolling back..." : "Roll Back"}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

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
            <span className="text-sm font-medium">Free Internal RAM</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo ? formatBytes(systemInfo.freeInternalHeap) : "--"}
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
          <div className="flex justify-between py-2 border-b gap-4">
            <span className="text-sm font-medium shrink-0">Last Error</span>
            <span className="text-sm text-muted-foreground text-right">
              {!systemInfo
                ? "--"
                : systemInfo.lastErrorCode === 0
                  ? "None"
                  : `${describeFiringError(systemInfo.lastErrorCode)} (E${systemInfo.lastErrorCode})`}
            </span>
          </div>
          <div className="py-2 border-b">
            <div className="flex justify-between">
              <span className="text-sm font-medium">Emergency Stop</span>
              <span className="text-sm">
                {systemInfo?.emergencyStop ? (
                  <Badge variant="destructive">ACTIVE</Badge>
                ) : (
                  <Badge variant="secondary">Clear</Badge>
                )}
              </span>
            </div>
            {/* "ACTIVE" on its own is a dead end — nothing else in the UI hints
                at how to get out of it (#164). The copy is keyed off the recorded
                cause, not the flag: every safety trip raises the same flag, so a
                fixed message would advise starting a new firing to clear an
                over-temperature trip. */}
            {systemInfo?.emergencyStop &&
              (() => {
                const { cause, guidance } = emergencyStopExplanation(systemInfo.lastErrorCode);
                return (
                  <p className="text-xs text-muted-foreground mt-1">
                    {cause}
                    {guidance ? ` — ${guidance}` : ""}
                  </p>
                );
              })()}
          </div>
          <div className="flex justify-between py-2">
            <span className="text-sm font-medium">Board Temperature</span>
            <span className="text-sm text-muted-foreground">
              {systemInfo?.boardTempC != null ? formatTemp(systemInfo.boardTempC, unit, 1) : "--"}
            </span>
          </div>
        </CardContent>
      </Card>

      <Dialog open={restartConfirmOpen} onOpenChange={setRestartConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Restart the controller?</DialogTitle>
            <DialogDescription>
              The kiln will go offline for a few seconds and this page will lose its connection.
              Nothing is erased — settings, profiles and history all survive a restart.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRestartConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleRestart}>
              Restart
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rollbackConfirmOpen} onOpenChange={setRollbackConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Roll back to the previous firmware?</DialogTitle>
            <DialogDescription>
              {`The controller reboots immediately into the firmware it ran before ${
                otaStatus?.running?.version ?? "the last update"
              }. Settings, profiles and history are kept. To come back to this version afterwards, install it again from the update card above.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRollbackConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleRollback}>
              Roll Back
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
