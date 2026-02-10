import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { FiringProfile } from '../types/kiln';
import { Flame, Clock, TrendingUp } from 'lucide-react';

interface FiringProfilesProps {
  profiles: FiringProfile[];
  selectedProfile: FiringProfile | null;
  onSelectProfile: (profileId: string) => void;
  onEditProfile?: (profileId: string) => void;
}

export function FiringProfiles({ 
  profiles, 
  selectedProfile, 
  onSelectProfile,
  onEditProfile 
}: FiringProfilesProps) {
  const formatTime = (minutes: number) => {
    const hours = Math.floor(minutes / 60);
    const mins = Math.floor(minutes % 60);
    return `${hours}h ${mins}m`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold mb-2">Firing Profiles</h2>
        <p className="text-muted-foreground">
          Select a firing profile to use for your kiln. Each profile contains multiple segments
          that control the temperature ramp rate and hold times.
        </p>
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
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {onEditProfile && (
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="w-full mt-3"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEditProfile(profile.id);
                  }}
                >
                  Edit Profile
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {profiles.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No firing profiles available.</p>
            <p className="text-sm text-muted-foreground mt-2">
              Create a new profile in the Profile Builder tab.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
