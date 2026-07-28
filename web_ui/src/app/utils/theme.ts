/**
 * Colour-scheme preference.
 *
 * The `.dark` palette in `styles/theme.css` was complete but unreachable —
 * nothing ever set the class, and the toaster independently followed the OS via
 * `theme="system"`, so a dark-mode user got dark toasts floating over a light
 * app (#191). This module owns the one source of truth both now read.
 *
 * Three preferences, not two: "system" tracks the OS and is the default, while
 * "light"/"dark" pin the choice. Checking a kiln at night in a dark studio is a
 * real use of this UI, and so is wanting it to stay light in a bright workshop.
 */

export type ThemePreference = "light" | "dark" | "system";

/** The scheme actually painted, once a preference is resolved against the OS. */
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "bisque.theme";

const PREFERENCES: readonly ThemePreference[] = ["light", "dark", "system"];

function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && (PREFERENCES as readonly string[]).includes(value);
}

/**
 * Read the stored preference, falling back to "system".
 *
 * Tolerates a missing, unparseable, or hand-edited value, and a storage that
 * throws outright — Safari's private mode raises on `localStorage` access, and
 * a theme preference is never worth breaking the app over.
 */
export function readStoredPreference(
  storage: Pick<Storage, "getItem"> | undefined,
): ThemePreference {
  if (!storage) return "system";
  try {
    const raw = storage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

/** Persist a preference. Silently no-ops if storage is unavailable. */
export function writeStoredPreference(
  storage: Pick<Storage, "setItem"> | undefined,
  preference: ThemePreference,
): void {
  if (!storage) return;
  try {
    storage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    /* preference is not worth throwing over */
  }
}

/** Resolve a preference against the OS setting. */
export function resolveTheme(preference: ThemePreference, prefersDark: boolean): ResolvedTheme {
  if (preference === "system") return prefersDark ? "dark" : "light";
  return preference;
}

/**
 * Apply a resolved theme to the document root.
 *
 * `.dark` drives the CSS custom-variant; `color-scheme` makes the browser's own
 * chrome (scrollbars, form controls, the canvas behind the app) match, which is
 * what stops a dark app from flashing a white gutter.
 */
export function applyTheme(root: HTMLElement, theme: ResolvedTheme): void {
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}
