import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Textarea } from './ui/textarea';
import { FiringProfile, FiringSegment } from '../types/kiln';
import { Plus, Trash2, Save, MoveUp, MoveDown } from 'lucide-react';
import { toast } from 'sonner';

// Generate UUID - works in non-secure contexts (HTTP) unlike generateId()
function generateId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

interface ProfileBuilderProps {
  profiles: FiringProfile[];
  onSaveProfile: (profile: FiringProfile) => void;
  onDeleteProfile?: (profileId: string) => void;
}

export function ProfileBuilder({ profiles, onSaveProfile, onDeleteProfile }: ProfileBuilderProps) {
  const [editingProfile, setEditingProfile] = useState<FiringProfile | null>(null);
  const [profileName, setProfileName] = useState('');
  const [profileDescription, setProfileDescription] = useState('');
  const [segments, setSegments] = useState<FiringSegment[]>([]);

  const createNewProfile = () => {
    setEditingProfile(null);
    setProfileName('');
    setProfileDescription('');
    setSegments([
      {
        id: generateId(),
        name: 'Segment 1',
        rampRate: 100,
        targetTemp: 600,
        holdTime: 0,
      },
    ]);
  };

  const loadProfile = (profileId: string) => {
    const profile = profiles.find((p) => p.id === profileId);
    if (profile) {
      setEditingProfile(profile);
      setProfileName(profile.name);
      setProfileDescription(profile.description);
      setSegments([...profile.segments]);
    }
  };

  const addSegment = () => {
    const newSegment: FiringSegment = {
      id: generateId(),
      name: `Segment ${segments.length + 1}`,
      rampRate: 100,
      targetTemp: 1000,
      holdTime: 0,
    };
    setSegments([...segments, newSegment]);
  };

  const removeSegment = (segmentId: string) => {
    setSegments(segments.filter((s) => s.id !== segmentId));
  };

  const updateSegment = (segmentId: string, field: keyof FiringSegment, value: string | number) => {
    setSegments(
      segments.map((s) =>
        s.id === segmentId ? { ...s, [field]: value } : s
      )
    );
  };

  const moveSegment = (index: number, direction: 'up' | 'down') => {
    const newSegments = [...segments];
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    
    if (targetIndex < 0 || targetIndex >= segments.length) return;
    
    [newSegments[index], newSegments[targetIndex]] = [newSegments[targetIndex], newSegments[index]];
    setSegments(newSegments);
  };

  const calculateEstimatedDuration = (): number => {
    let totalMinutes = 0;
    let currentTemp = 20; // Starting room temperature

    segments.forEach((segment) => {
      const tempDifference = Math.abs(segment.targetTemp - currentTemp);
      const rampTimeHours = tempDifference / Math.abs(segment.rampRate);
      const rampTimeMinutes = rampTimeHours * 60;
      totalMinutes += rampTimeMinutes + segment.holdTime;
      currentTemp = segment.targetTemp;
    });

    return Math.round(totalMinutes);
  };

  const calculateMaxTemp = (): number => {
    if (segments.length === 0) return 0;
    return Math.max(...segments.map((s) => s.targetTemp));
  };

  const saveProfile = () => {
    if (!profileName.trim()) {
      toast.error('Please enter a profile name');
      return;
    }

    if (segments.length === 0) {
      toast.error('Please add at least one segment');
      return;
    }

    const profile: FiringProfile = {
      id: editingProfile?.id || generateId(),
      name: profileName,
      description: profileDescription,
      segments,
      maxTemp: calculateMaxTemp(),
      estimatedDuration: calculateEstimatedDuration(),
    };

    onSaveProfile(profile);
    toast.success(`Profile "${profileName}" saved successfully`);
    
    // Reset form
    setEditingProfile(null);
    setProfileName('');
    setProfileDescription('');
    setSegments([]);
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-2xl font-semibold mb-2">Profile Builder</h2>
          <p className="text-muted-foreground">
            Create and edit firing profiles with custom temperature segments.
          </p>
        </div>
        <Button onClick={createNewProfile} className="gap-2">
          <Plus className="h-4 w-4" />
          New Profile
        </Button>
      </div>

      {/* Load existing profile */}
      {profiles.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Load Existing Profile</CardTitle>
            <CardDescription>Select a profile to edit</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {profiles.map((profile) => (
                <Button
                  key={profile.id}
                  variant={editingProfile?.id === profile.id ? 'default' : 'outline'}
                  onClick={() => loadProfile(profile.id)}
                >
                  {profile.name}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Profile Editor */}
      {(segments.length > 0 || profileName) && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Profile Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="profile-name">Profile Name</Label>
                <Input
                  id="profile-name"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  placeholder="e.g., Custom Bisque Firing"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="profile-description">Description</Label>
                <Textarea
                  id="profile-description"
                  value={profileDescription}
                  onChange={(e) => setProfileDescription(e.target.value)}
                  placeholder="Describe the purpose of this firing profile..."
                  rows={3}
                />
              </div>

              <div className="grid grid-cols-2 gap-4 pt-2 border-t">
                <div>
                  <p className="text-sm text-muted-foreground">Max Temperature</p>
                  <p className="text-2xl font-semibold">{calculateMaxTemp()}°C</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Estimated Duration</p>
                  <p className="text-2xl font-semibold">
                    {Math.floor(calculateEstimatedDuration() / 60)}h {calculateEstimatedDuration() % 60}m
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Segments */}
          <Card>
            <CardHeader>
              <div className="flex justify-between items-center">
                <div>
                  <CardTitle>Firing Segments</CardTitle>
                  <CardDescription>Define temperature ramps and holds</CardDescription>
                </div>
                <Button onClick={addSegment} variant="outline" size="sm" className="gap-2">
                  <Plus className="h-4 w-4" />
                  Add Segment
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {segments.map((segment, index) => (
                <div key={segment.id} className="p-4 border rounded-lg space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="flex-1 space-y-2">
                      <Label>Segment Name</Label>
                      <Input
                        value={segment.name}
                        onChange={(e) => updateSegment(segment.id, 'name', e.target.value)}
                        placeholder="e.g., Warm-up, Water smoke"
                      />
                    </div>
                    <div className="flex gap-1 ml-4">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => moveSegment(index, 'up')}
                        disabled={index === 0}
                      >
                        <MoveUp className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => moveSegment(index, 'down')}
                        disabled={index === segments.length - 1}
                      >
                        <MoveDown className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeSegment(segment.id)}
                        disabled={segments.length === 1}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>Ramp Rate (°C/hr)</Label>
                      <Input
                        type="number"
                        value={segment.rampRate}
                        onChange={(e) => updateSegment(segment.id, 'rampRate', parseFloat(e.target.value))}
                      />
                      <p className="text-xs text-muted-foreground">
                        Positive to heat, negative to cool
                      </p>
                    </div>

                    <div className="space-y-2">
                      <Label>Target Temp (°C)</Label>
                      <Input
                        type="number"
                        value={segment.targetTemp}
                        onChange={(e) => updateSegment(segment.id, 'targetTemp', parseFloat(e.target.value))}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label>Hold Time (min)</Label>
                      <Input
                        type="number"
                        value={segment.holdTime}
                        onChange={(e) => updateSegment(segment.id, 'holdTime', parseFloat(e.target.value))}
                        min="0"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Save/Delete Actions */}
          <div className="flex gap-2 justify-end">
            {editingProfile && onDeleteProfile && (
              <Button
                variant="destructive"
                onClick={() => {
                  if (window.confirm(`Delete profile "${profileName}"?`)) {
                    onDeleteProfile(editingProfile.id);
                    toast.success('Profile deleted');
                    setEditingProfile(null);
                    setProfileName('');
                    setProfileDescription('');
                    setSegments([]);
                  }
                }}
              >
                Delete Profile
              </Button>
            )}
            <Button onClick={saveProfile} className="gap-2">
              <Save className="h-4 w-4" />
              Save Profile
            </Button>
          </div>
        </>
      )}

      {segments.length === 0 && !profileName && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">Click "New Profile" to start creating a firing profile.</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
