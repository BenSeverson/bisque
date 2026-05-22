import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Wifi } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Label } from "./ui/label";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { wifiCredentialsSchema, WifiCredentialsFormValues } from "../schemas/kiln";
import { useWifi, useSaveWifi, useClearWifi } from "../hooks/queries";

export function WifiCard() {
  const { data: wifi } = useWifi();
  const saveWifi = useSaveWifi();
  const clearWifi = useClearWifi();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<WifiCredentialsFormValues>({
    resolver: zodResolver(wifiCredentialsSchema),
    defaultValues: { ssid: "", password: "" },
  });

  // Prefill the SSID with the saved network once status arrives, but never the
  // password (the firmware never returns it).
  useEffect(() => {
    if (wifi?.savedSsid) reset({ ssid: wifi.savedSsid, password: "" }, { keepDirtyValues: true });
  }, [wifi?.savedSsid, reset]);

  const onSubmit = async (data: WifiCredentialsFormValues) => {
    try {
      const resp = await saveWifi.mutateAsync(data);
      toast.success(resp.message ?? "Wi-Fi credentials saved");
    } catch {
      toast.error("Failed to save Wi-Fi credentials");
    }
  };

  const onForget = async () => {
    try {
      const resp = await clearWifi.mutateAsync();
      reset({ ssid: "", password: "" });
      toast.success(resp.message ?? "Wi-Fi credentials cleared");
    } catch {
      toast.error("Failed to clear Wi-Fi credentials");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Wifi className="h-5 w-5" />
          Wi-Fi Network
        </CardTitle>
        <CardDescription>
          Connect the controller to your network. Credentials are stored on the device and survive
          firmware updates.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Status</span>
          {wifi?.apMode ? (
            <Badge variant="secondary">Setup mode (AP)</Badge>
          ) : wifi?.connected ? (
            <Badge variant="default">Connected</Badge>
          ) : (
            <Badge variant="destructive">Disconnected</Badge>
          )}
        </div>

        {wifi?.ip && (
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">IP Address</span>
            <span className="text-sm text-muted-foreground">{wifi.ip}</span>
          </div>
        )}

        {wifi?.hasSavedCredentials && wifi.savedSsid && (
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Saved Network</span>
            <span className="text-sm text-muted-foreground">{wifi.savedSsid}</span>
          </div>
        )}

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="wifi-ssid">Network Name (SSID)</Label>
            <Input id="wifi-ssid" placeholder="Your Wi-Fi network" {...register("ssid")} />
            {errors.ssid && <p className="text-sm text-destructive">{errors.ssid.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="wifi-password">Password</Label>
            <Input
              id="wifi-password"
              type="password"
              placeholder="Leave blank for open networks"
              {...register("password")}
            />
            {errors.password && (
              <p className="text-sm text-destructive">{errors.password.message}</p>
            )}
          </div>

          <div className="flex gap-3 flex-wrap">
            <Button type="submit" disabled={saveWifi.isPending}>
              {saveWifi.isPending ? "Saving..." : "Save Network"}
            </Button>
            {wifi?.hasSavedCredentials && (
              <Button
                type="button"
                variant="destructive"
                onClick={onForget}
                disabled={clearWifi.isPending}
              >
                Forget Network
              </Button>
            )}
          </div>

          <p className="text-sm text-muted-foreground">
            Power-cycle the controller after saving for it to join the new network.
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
