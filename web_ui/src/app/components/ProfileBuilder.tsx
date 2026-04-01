import { useState, useMemo } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Switch } from "./ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { FiringProfile } from "../types/kiln";
import { Plus, Trash2, Save, MoveUp, MoveDown, Flame } from "lucide-react";
import { toast } from "sonner";
import { toErrorMessage } from "../utils/error";
import { computeSegmentDurationMinutes } from "../utils/profile";
import { profileFormSchema, ProfileFormValues } from "../schemas/kiln";
import {
  useProfiles,
  useSaveProfile,
  useDeleteProfile,
  useConeTable,
  useGenerateConeFire,
} from "../hooks/queries";

// Generate UUID - works in non-secure contexts (HTTP) unlike crypto.randomUUID()
function generateId(): string {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function ProfileBuilder() {
  const { data: profiles = [] } = useProfiles();
  const saveProfile = useSaveProfile();
  const deleteProfile = useDeleteProfile();
  const { data: coneEntries = [] } = useConeTable();
  const generateConeFire = useGenerateConeFire();

  const [mode, setMode] = useState<"manual" | "cone">("manual");
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);

  // Cone fire state
  const [selectedConeId, setSelectedConeId] = useState<number | null>(null);
  const [coneSpeed, setConeSpeed] = useState<0 | 1 | 2>(1);
  const [preheat, setPreheat] = useState(true);
  const [slowCool, setSlowCool] = useState(false);

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: {
      name: "",
      description: "",
      segments: [],
    },
  });

  const { fields, append, remove, move } = useFieldArray({
    control,
    name: "segments",
  });

  const segments = watch("segments");
  const profileName = watch("name");

  const isEditing = fields.length > 0 || profileName;

  const estimatedDuration = useMemo(() => {
    let totalMinutes = 0;
    let currentTemp = 20;
    segments.forEach((segment) => {
      const { rampMinutes, holdMinutes } = computeSegmentDurationMinutes(
        {
          targetTemp: segment.targetTemp,
          rampRate: segment.rampRate,
          holdMinutes: segment.holdTime,
        },
        currentTemp,
      );
      totalMinutes += rampMinutes + holdMinutes;
      currentTemp = segment.targetTemp;
    });
    return Math.round(totalMinutes);
  }, [segments]);

  const calculateMaxTemp = (): number => {
    if (segments.length === 0) return 0;
    return Math.max(...segments.map((s) => s.targetTemp));
  };

  const createNewProfile = () => {
    setMode("manual");
    setEditingProfileId(null);
    reset({
      name: "",
      description: "",
      segments: [
        {
          id: generateId(),
          name: "Segment 1",
          rampRate: 100,
          targetTemp: 600,
          holdTime: 0,
        },
      ],
    });
  };

  const loadProfile = (profileId: string) => {
    const profile = profiles.find((p) => p.id === profileId);
    if (profile) {
      setMode("manual");
      setEditingProfileId(profile.id);
      reset({
        name: profile.name,
        description: profile.description,
        segments: profile.segments.map((s) => ({ ...s })),
      });
    }
  };

  const handleGenerateConeFire = async () => {
    if (selectedConeId === null) {
      toast.error("Please select a cone");
      return;
    }
    try {
      const profile = await generateConeFire.mutateAsync({
        coneId: selectedConeId,
        speed: coneSpeed,
        preheat,
        slowCool,
        save: false,
      });
      setMode("manual");
      setEditingProfileId(null);
      reset({
        name: profile.name,
        description: profile.description,
        segments: profile.segments.map((s) => ({ ...s })),
      });
      toast.success("Cone fire profile generated — review and save below");
    } catch (e) {
      toast.error(`Failed to generate: ${toErrorMessage(e)}`);
    }
  };

  const addSegment = () => {
    append({
      id: generateId(),
      name: `Segment ${fields.length + 1}`,
      rampRate: 100,
      targetTemp: 1000,
      holdTime: 0,
    });
  };

  const onSubmit = async (data: ProfileFormValues) => {
    const profile: FiringProfile = {
      id: editingProfileId || generateId(),
      name: data.name,
      description: data.description,
      segments: data.segments,
      maxTemp: calculateMaxTemp(),
      estimatedDuration,
    };
    try {
      await saveProfile.mutateAsync(profile);
      toast.success(`Profile "${data.name}" saved successfully`);
      setEditingProfileId(null);
      reset({ name: "", description: "", segments: [] });
    } catch {
      // The mutation's onError fallback handles local cache update
      toast.success(`Profile "${data.name}" saved locally`);
      setEditingProfileId(null);
      reset({ name: "", description: "", segments: [] });
    }
  };

  const handleDelete = async () => {
    if (!editingProfileId) return;
    if (!window.confirm(`Delete profile "${profileName}"?`)) return;
    try {
      await deleteProfile.mutateAsync(editingProfileId);
      toast.success("Profile deleted");
      setEditingProfileId(null);
      reset({ name: "", description: "", segments: [] });
    } catch {
      toast.error("Failed to delete profile");
    }
  };

  const speedLabel = (s: 0 | 1 | 2) => {
    if (s === 0) return "Slow";
    if (s === 1) return "Medium";
    return "Fast";
  };

  const selectedCone = coneEntries.find((c) => c.id === selectedConeId);
  const coneTargetTemp = selectedCone
    ? [selectedCone.slowTempC, selectedCone.mediumTempC, selectedCone.fastTempC][coneSpeed]
    : null;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-2xl font-semibold mb-2">Profile Builder</h2>
          <p className="text-muted-foreground">
            Create firing profiles manually or use the Cone Fire Wizard.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={mode === "cone" ? "default" : "outline"}
            onClick={() => setMode("cone")}
            className="gap-2"
          >
            <Flame className="h-4 w-4" />
            Cone Fire Wizard
          </Button>
          <Button
            variant={mode === "manual" ? "default" : "outline"}
            onClick={createNewProfile}
            className="gap-2"
          >
            <Plus className="h-4 w-4" />
            New Profile
          </Button>
        </div>
      </div>

      {/* Cone Fire Wizard */}
      {mode === "cone" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Flame className="h-5 w-5 text-orange-500" />
              Cone Fire Wizard
            </CardTitle>
            <CardDescription>
              Generate an Orton-standard firing schedule for a target cone and speed.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Target Cone</Label>
                <Select
                  value={selectedConeId !== null ? String(selectedConeId) : ""}
                  onValueChange={(v) => setSelectedConeId(Number(v))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select cone..." />
                  </SelectTrigger>
                  <SelectContent>
                    {coneEntries.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        Cone {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Firing Speed</Label>
                <Select
                  value={String(coneSpeed)}
                  onValueChange={(v) => setConeSpeed(Number(v) as 0 | 1 | 2)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">Slow</SelectItem>
                    <SelectItem value="1">Medium</SelectItem>
                    <SelectItem value="2">Fast</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {coneTargetTemp !== null && (
              <div className="p-3 bg-muted/50 rounded-lg text-sm">
                Cone {selectedCone?.name} @ {speedLabel(coneSpeed)}: target{" "}
                <span className="font-semibold">{coneTargetTemp}°C</span>
              </div>
            )}

            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Preheat Segment</Label>
                  <p className="text-xs text-muted-foreground">
                    80°C/hr to 120°C with 30-min moisture hold
                  </p>
                </div>
                <Switch checked={preheat} onCheckedChange={setPreheat} />
              </div>
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Slow Cool</Label>
                  <p className="text-xs text-muted-foreground">
                    −150°C/hr through quartz inversion (573°C)
                  </p>
                </div>
                <Switch checked={slowCool} onCheckedChange={setSlowCool} />
              </div>
            </div>

            <Button
              onClick={handleGenerateConeFire}
              disabled={selectedConeId === null || generateConeFire.isPending}
              className="w-full gap-2"
            >
              <Flame className="h-4 w-4" />
              {generateConeFire.isPending ? "Generating..." : "Generate Profile"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Load existing profile */}
      {mode === "manual" && profiles.length > 0 && (
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
                  variant={editingProfileId === profile.id ? "default" : "outline"}
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
      {isEditing && (
        <form onSubmit={handleSubmit(onSubmit)}>
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Profile Details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="profile-name">Profile Name</Label>
                  <Input
                    id="profile-name"
                    {...register("name")}
                    placeholder="e.g., Custom Bisque Firing"
                  />
                  {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="profile-description">Description</Label>
                  <Textarea
                    id="profile-description"
                    {...register("description")}
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
                      {Math.floor(estimatedDuration / 60)}h {estimatedDuration % 60}m
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
                    <CardDescription>
                      Define temperature ramps and holds. Set hold time to 0 for infinite hold.
                    </CardDescription>
                  </div>
                  <Button
                    onClick={addSegment}
                    type="button"
                    variant="outline"
                    size="sm"
                    className="gap-2"
                  >
                    <Plus className="h-4 w-4" />
                    Add Segment
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {errors.segments?.root && (
                  <p className="text-sm text-destructive">{errors.segments.root.message}</p>
                )}
                {fields.map((field, index) => (
                  <div key={field.id} className="p-4 border rounded-lg space-y-4">
                    <div className="flex justify-between items-start">
                      <div className="flex-1 space-y-2">
                        <Label>Segment Name</Label>
                        <Input
                          {...register(`segments.${index}.name`)}
                          placeholder="e.g., Warm-up, Water smoke"
                        />
                        {errors.segments?.[index]?.name && (
                          <p className="text-sm text-destructive">
                            {errors.segments[index].name.message}
                          </p>
                        )}
                      </div>
                      <div className="flex gap-1 ml-4">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => move(index, index - 1)}
                          disabled={index === 0}
                        >
                          <MoveUp className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => move(index, index + 1)}
                          disabled={index === fields.length - 1}
                        >
                          <MoveDown className="h-4 w-4" />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => remove(index)}
                          disabled={fields.length === 1}
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
                          {...register(`segments.${index}.rampRate`, { valueAsNumber: true })}
                        />
                        <p className="text-xs text-muted-foreground">
                          Positive to heat, negative to cool
                        </p>
                      </div>

                      <div className="space-y-2">
                        <Label>Target Temp (°C)</Label>
                        <Input
                          type="number"
                          {...register(`segments.${index}.targetTemp`, { valueAsNumber: true })}
                        />
                      </div>

                      <div className="space-y-2">
                        <Label>Hold Time (min)</Label>
                        <Input
                          type="number"
                          {...register(`segments.${index}.holdTime`, { valueAsNumber: true })}
                          min="0"
                        />
                        <p className="text-xs text-muted-foreground">0 = hold until skip</p>
                      </div>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            {/* Save/Delete Actions */}
            <div className="flex gap-2 justify-end">
              {editingProfileId && (
                <Button type="button" variant="destructive" onClick={handleDelete}>
                  Delete Profile
                </Button>
              )}
              <Button type="submit" className="gap-2">
                <Save className="h-4 w-4" />
                Save Profile
              </Button>
            </div>
          </div>
        </form>
      )}

      {!isEditing && mode === "manual" && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">
              Click "New Profile" to start building, or use the Cone Fire Wizard to generate a
              schedule.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
