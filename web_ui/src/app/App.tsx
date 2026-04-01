import { useEffect } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
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

  useEffect(() => {
    return initWebSocket();
  }, [initWebSocket]);

  return (
    <div className="min-h-screen bg-background">
      <Toaster />

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
        <Tabs defaultValue="dashboard" className="space-y-6">
          <TabsList className="grid w-full grid-cols-5 lg:w-auto lg:inline-grid">
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

          <TabsContent value="builder" className="space-y-4">
            <ProfileBuilder />
          </TabsContent>

          <TabsContent value="settings" className="space-y-4">
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
          <div className="flex flex-col md:flex-row justify-between items-center gap-4 text-sm text-muted-foreground">
            <p>Bisque ESP32-S3</p>
            <div className="flex gap-6">
              <a href="#" className="hover:text-foreground transition-colors">
                Documentation
              </a>
              <a href="#" className="hover:text-foreground transition-colors">
                Support
              </a>
              <a href="#" className="hover:text-foreground transition-colors">
                Safety Guidelines
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
