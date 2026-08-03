import { useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Label } from "./ui/label";
import { Switch } from "./ui/switch";
import {
  notificationPermission,
  notificationsSupported,
  readNotifyPreference,
  requestNotificationPermission,
  writeNotifyPreference,
} from "../utils/browserNotifications";

/**
 * The opt-in for OS notifications when a firing ends (#185).
 *
 * Deliberately outside the settings `<form>`: this is stored in this browser,
 * not on the controller, and applies the moment it is flipped. Sitting it above
 * a "Save Settings" button it has nothing to do with would be a lie about where
 * the value goes.
 *
 * The card renders even where the API is missing, with the reason in place of
 * the switch. Silence there would read as a missing feature rather than as the
 * consequence of the controller serving plain HTTP.
 */
export function BrowserAlertsCard() {
  const supported = notificationsSupported(window);
  const [permission, setPermission] = useState(() => notificationPermission(window));
  const [enabled, setEnabled] = useState(() => readNotifyPreference(window.localStorage));

  const persist = (on: boolean) => {
    setEnabled(on);
    writeNotifyPreference(window.localStorage, on);
  };

  const onToggle = async (on: boolean) => {
    if (!on) {
      persist(false);
      return;
    }

    if (permission === "denied") {
      toast.error("Notifications are blocked for this site — allow them in your browser settings");
      return;
    }

    /* Prompting from this switch is what makes the permission request legal:
       Safari only honours requestPermission() inside a user gesture, and a
       prompt raised by a background status change would be hostile anyway. */
    const result =
      permission === "granted" ? "granted" : await requestNotificationPermission(window);
    setPermission(result);

    if (result !== "granted") {
      // Leave the switch off rather than claiming an opt-in the browser will
      // not honour — the announcement would then silently never arrive.
      persist(false);
      toast.error(
        result === "denied"
          ? "Notifications are blocked for this site — allow them in your browser settings"
          : "Permission was not granted, so notifications stay off",
      );
      return;
    }

    persist(true);
    toast.success("You'll be notified when a firing completes or errors");
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Browser Alerts</CardTitle>
        <CardDescription>
          Notify this browser when a firing completes or errors. Saved on this device only, and
          applies immediately.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {supported ? (
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="browser-notifications">Desktop notifications</Label>
              <p className="text-sm text-muted-foreground">
                {permission === "denied"
                  ? "Blocked for this site. Allow notifications in your browser settings first."
                  : "A firing runs for hours — this reaches you with the tab closed."}
              </p>
            </div>
            <Switch
              id="browser-notifications"
              checked={enabled}
              disabled={permission === "denied"}
              onCheckedChange={onToggle}
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Your browser only offers notifications over a secure (https) connection, and the
            controller serves this page over plain http. Firing results still appear as an on-screen
            message and in the browser tab title.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
