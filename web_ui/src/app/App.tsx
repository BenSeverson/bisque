import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { WifiSetupBanner } from "./components/WifiSetupBanner";
import { FiringDashboard } from "./components/FiringDashboard";
import { FiringProfiles } from "./components/FiringProfiles";
import { ProfileBuilder } from "./components/ProfileBuilder";
import { Settings } from "./components/Settings";
import { FiringHistory } from "./components/FiringHistory";
import { Flame, FileText, Wrench, Settings as SettingsIcon, History } from "lucide-react";
import { Toaster } from "./components/ui/sonner";
import { useKilnStore } from "./stores/kilnStore";

export default function App() {
  const initWebSocket = useKilnStore((s) => s.initWebSocket);
  const [activeTab, setActiveTab] = useState("dashboard");

  useEffect(() => {
    return initWebSocket();
  }, [initWebSocket]);

  return (
    <div className="min-h-screen bg-background">
      <Toaster />

      {__DEMO__ && (
        <div className="border-b border-orange-300 bg-orange-50 text-orange-900">
          <div className="container mx-auto flex items-center gap-2 px-4 py-2 text-sm">
            <Flame className="h-4 w-4 shrink-0" />
            <p>
              <span className="font-medium">Live demo</span> — simulated kiln, no hardware
              connected. Changes reset on reload.
            </p>
          </div>
        </div>
      )}

      <WifiSetupBanner onGoToSettings={() => setActiveTab("settings")} />

      {/* Header */}
      <header className="border-b bg-card">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-lg flex items-center justify-center">
              <Flame className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold">Bisque</h1>
              <p className="text-sm text-muted-foreground">Professional Firing Control System</p>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          {/* The tab strip wraps onto as many rows as the viewport needs instead of
              squeezing five tabs onto one line. `grid-cols-5` used to shrink every
              trigger below its label width at phone widths, so the icons and text
              overlapped into unreadable mush (#159). Wrapping keeps all five labels
              visible and legible at once — no horizontal scrolling that hides tabs
              off-screen, and no icon-only mode that would make "Profile Builder"
              (wrench) and "Settings" (gear) guesswork. `[&>*]:basis-auto` undoes the
              trigger's own `flex-1` (basis 0) so each one lays out at its natural
              width and the row breaks rather than the text colliding. */}
          <TabsList
            aria-label="Sections"
            className="h-auto w-full flex-wrap gap-1 [&>*]:basis-auto [&>*]:py-1.5 lg:w-fit lg:flex-nowrap"
          >
            <TabsTrigger value="dashboard" className="gap-2">
              <Flame className="h-4 w-4" />
              Dashboard
            </TabsTrigger>
            <TabsTrigger value="profiles" className="gap-2">
              <FileText className="h-4 w-4" />
              Profiles
            </TabsTrigger>
            <TabsTrigger value="builder" className="gap-2">
              <Wrench className="h-4 w-4" />
              Profile Builder
            </TabsTrigger>
            <TabsTrigger value="settings" className="gap-2">
              <SettingsIcon className="h-4 w-4" />
              Settings
            </TabsTrigger>
            <TabsTrigger value="history" className="gap-2">
              <History className="h-4 w-4" />
              History
            </TabsTrigger>
          </TabsList>

          <TabsContent value="dashboard" className="space-y-4">
            <FiringDashboard />
          </TabsContent>

          <TabsContent value="profiles" className="space-y-4">
            <FiringProfiles />
          </TabsContent>

          {/* forceMount keeps form state alive when the user switches tabs;
              react-hook-form state is per-mount and would otherwise be lost. */}
          <TabsContent value="builder" className="space-y-4" forceMount>
            <ProfileBuilder />
          </TabsContent>

          <TabsContent value="settings" className="space-y-4" forceMount>
            <Settings />
          </TabsContent>

          <TabsContent value="history" className="space-y-4">
            <FiringHistory />
          </TabsContent>
        </Tabs>
      </main>

      {/* Footer */}
      <footer className="border-t mt-12">
        <div className="container mx-auto px-4 py-6">
          <div className="text-sm text-muted-foreground">
            <p>
              Bisque ESP32-S3 · {__APP_VERSION__}
              {__DEMO__ ? " · demo" : ""}
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
