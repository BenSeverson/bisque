import { useRef } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { FiringProfile } from '../types/kiln';
import { Flame, Clock, TrendingUp, Copy, Download, Upload } from 'lucide-react';
import { api } from '../services/api';
import { toast } from 'sonner';

interface FiringProfilesProps {
  profiles: FiringProfile[];
  selectedProfile: FiringProfile | null;
  onSelectProfile: (profileId: string) => void;
  onEditProfile?: (profileId: string) => void;
  onRefreshProfiles?: () => void;
}

export function FiringProfiles({
  profiles,
  selectedProfile,
  onSelectProfile,
  onEditProfile,
  onRefreshProfiles,
}: FiringProfilesProps) {
  const importInputRef = useRef<HTMLInputElement>(null);

  const formatTime = (minutes: number) => {
    const hours = Math.floor(minutes / 60);
    const mins = Math.floor(minutes % 60);
    return `${hours}h ${mins}m`;
  };

  const handleDuplicate = async (e: React.MouseEvent, profile: FiringProfile) => {
    e.stopPropagation();
    try {
      await api.duplicateProfile(profile);
      toast.success(`Duplicated "${profile.name}"`);
      onRefreshProfiles?.();
    } catch {
      toast.error('Failed to duplicate profile');
    }
  };

  const handleExport = (e: React.MouseEvent, profile: FiringProfile) => {
    e.stopPropagation();
    const url = api.exportProfile(profile.id);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${profile.id}.json`;
    a.click();
    toast.success('Downloading profile JSON');
  };

  const handleImportClick = () => {
    importInputRef.current?.click();
  };

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const profile = JSON.parse(text) as FiringProfile;
      await api.importProfile(profile);
      toast.success(`Imported "${profile.name}"`);
      onRefreshProfiles?.();
    } catch {
      toast.error('Failed to import profile — invalid JSON or format');
    } finally {
      // Reset so the same file can be re-imported
      e.target.value = '';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold mb-2">Firing Profiles</h2>
          <p className="text-muted-foreground">
            Select a firing profile to use for your kiln. Each profile contains multiple segments
            that control the temperature ramp rate and hold times.
          </p>
        </div>
        <div>
          <input
            ref={importInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImportFile}
          />
          <Button variant="outline" size="sm" className="gap-2" onClick={handleImportClick}>
            <Upload className="h-4 w-4" />
            Import Profile
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {profiles.map((profile) => (
          <Card
            key={profile.id}
            className={`cursor-pointer transition-all ${
              selectedProfile?.id === profile.id
                ? 'ring-2 ring-primary'
                : 'hover:shadow-lg'
            }`}
            onClick={() => onSelectProfile(profile.id)}
          >
            <CardHeader>
              <div className="flex justify-between items-start">
                <CardTitle className="text-lg">{profile.name}</CardTitle>
                {selectedProfile?.id === profile.id && (
                  <Badge variant="default">Selected</Badge>
                )}
              </div>
              <CardDescription>{profile.description}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2 text-sm">
                <Flame className="h-4 w-4 text-orange-500" />
                <span>Max Temperature: {profile.maxTemp}°C</span>
              </div>

              <div className="flex items-center gap-2 text-sm">
                <Clock className="h-4 w-4 text-blue-500" />
                <span>Duration: {formatTime(profile.estimatedDuration)}</span>
              </div>

              <div className="flex items-center gap-2 text-sm">
                <TrendingUp className="h-4 w-4 text-green-500" />
                <span>{profile.segments.length} segments</span>
              </div>

              <div className="pt-3 border-t">
                <p className="text-xs font-semibold text-muted-foreground mb-2">SEGMENTS</p>
                <div className="space-y-1">
                  {profile.segments.map((segment) => (
                    <div key={segment.id} className="text-xs bg-muted/50 p-2 rounded">
                      <div className="font-medium">{segment.name}</div>
                      <div className="text-muted-foreground">
                        {segment.rampRate > 0 ? '+' : ''}{segment.rampRate}°C/hr → {segment.targetTemp}°C
                        {segment.holdTime > 0 && `, hold ${segment.holdTime} min`}
                        {segment.holdTime === 0 && ` (hold until skip)`}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex gap-2 pt-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 gap-1"
                  onClick={(e) => handleDuplicate(e, profile)}
                >
                  <Copy className="h-3 w-3" />
                  Duplicate
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 gap-1"
                  onClick={(e) => handleExport(e, profile)}
                >
                  <Download className="h-3 w-3" />
                  Export
                </Button>
                {onEditProfile && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={(e) => {
                      e.stopPropagation();
                      onEditProfile(profile.id);
                    }}
                  >
                    Edit
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {profiles.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No firing profiles available.</p>
            <p className="text-sm text-muted-foreground mt-2">
              Create a new profile in the Profile Builder tab or import one.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
