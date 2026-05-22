import { useState } from "react";
import { Wifi, X } from "lucide-react";
import { Button } from "./ui/button";
import { useWifi } from "../hooks/queries";

/** Dismissible banner shown while the device is in AP setup mode, pointing the
 *  user to the Wi-Fi card in Settings. */
export function WifiSetupBanner({ onGoToSettings }: { onGoToSettings: () => void }) {
  const { data: wifi } = useWifi();
  const [dismissed, setDismissed] = useState(false);

  if (!wifi?.apMode || dismissed) return null;

  return (
    <div className="border-b border-amber-300 bg-amber-50 text-amber-900">
      <div className="container mx-auto flex items-center gap-3 px-4 py-3">
        <Wifi className="h-5 w-5 shrink-0" />
        <p className="flex-1 text-sm">
          The controller is in Wi-Fi setup mode and isn&apos;t connected to your network. Add your
          network details to get it online.
        </p>
        <Button size="sm" onClick={onGoToSettings}>
          Set up Wi-Fi
        </Button>
        <button
          type="button"
          aria-label="Dismiss"
          className="rounded p-1 hover:bg-amber-100"
          onClick={() => setDismissed(true)}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
