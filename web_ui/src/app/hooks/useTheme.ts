import { useCallback, useEffect, useState } from "react";
import {
  applyTheme,
  readStoredPreference,
  resolveTheme,
  writeStoredPreference,
  type ResolvedTheme,
  type ThemePreference,
} from "../utils/theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function prefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.(DARK_QUERY).matches === true;
}

function storage(): Storage | undefined {
  return typeof window === "undefined" ? undefined : window.localStorage;
}

/**
 * Owns the app's colour scheme: reads the persisted preference, resolves it
 * against the OS, paints it onto `<html>`, and keeps following the OS while the
 * preference is "system".
 *
 * Returns the resolved theme as well as the preference so consumers that need
 * the *painted* scheme — the toaster, which takes "light"/"dark" and not
 * "system" — don't have to re-derive it (#191).
 */
export function useTheme(): {
  preference: ThemePreference;
  theme: ResolvedTheme;
  setPreference: (next: ThemePreference) => void;
} {
  const [preference, setPreferenceState] = useState<ThemePreference>(() =>
    readStoredPreference(storage()),
  );
  const [systemDark, setSystemDark] = useState<boolean>(prefersDark);

  // Only meaningful while the preference is "system", but the listener is
  // cheap and unconditional attachment keeps systemDark correct for the moment
  // the user switches back to "system".
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const theme = resolveTheme(preference, systemDark);

  useEffect(() => {
    applyTheme(document.documentElement, theme);
  }, [theme]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    writeStoredPreference(storage(), next);
  }, []);

  return { preference, theme, setPreference };
}
