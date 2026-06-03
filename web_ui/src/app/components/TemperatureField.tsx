import { Controller, type Control, type FieldPath, type FieldValues } from "react-hook-form";
import { Input } from "./ui/input";
import {
  type TempUnit,
  toDisplayTemp,
  fromDisplayTemp,
  toDisplayRate,
  fromDisplayRate,
} from "../utils/temperature";

/**
 * A numeric <Input> bound to a react-hook-form field whose canonical value is
 * Celsius, but which displays and accepts values in the active unit. Keeps the
 * form/store in Celsius so validation, the API, and stored profiles never deal
 * with the display unit.
 *
 * kind="absolute" applies the full conversion (×9/5 + 32) — use for temperatures.
 * kind="delta" scales only — use for ramp rates and offsets.
 */
interface TemperatureFieldProps<T extends FieldValues> {
  control: Control<T>;
  name: FieldPath<T>;
  unit: TempUnit;
  kind?: "absolute" | "delta";
  /** Decimal places shown in the display unit (default 0). */
  digits?: number;
  id?: string;
  step?: string;
  min?: string;
}

export function TemperatureField<T extends FieldValues>({
  control,
  name,
  unit,
  kind = "absolute",
  digits = 0,
  id,
  step,
  min,
}: TemperatureFieldProps<T>) {
  const toDisplay = kind === "delta" ? toDisplayRate : toDisplayTemp;
  const fromDisplay = kind === "delta" ? fromDisplayRate : fromDisplayTemp;

  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => {
        const celsius = field.value as number;
        const shown = Number.isFinite(celsius)
          ? Number(toDisplay(celsius, unit).toFixed(digits))
          : "";
        return (
          <Input
            id={id}
            type="number"
            step={step}
            min={min}
            value={shown}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === "") {
                // Mirror valueAsNumber: empty -> NaN so the schema flags it.
                field.onChange(NaN);
                return;
              }
              const parsed = parseFloat(raw);
              field.onChange(Number.isFinite(parsed) ? fromDisplay(parsed, unit) : NaN);
            }}
            onBlur={field.onBlur}
          />
        );
      }}
    />
  );
}
