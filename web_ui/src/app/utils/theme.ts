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
 * The painted `--background` for each scheme, mirrored from `styles/theme.css`
 * (`#ffffff`, and `oklch(0.145 0 0)` which resolves to `#0a0a0a`).
 *
 * `<meta name="theme-color">` only accepts a literal colour, so this pair has
 * to be duplicated here and in the two media-scoped tags in `index.html`. Retune
 * all three together if the background ever moves.
 */
export const THEME_COLORS: Record<ResolvedTheme, string> = {
  light: "#ffffff",
  dark: "#0a0a0a",
};

/**
 * Point every `<meta name="theme-color">` at the scheme actually painted.
 *
 * `index.html` ships two of these tags, scoped to `prefers-color-scheme`, so the
 * browser chrome is right before any JS runs. That is as far as markup gets:
 * a media query cannot know the user pinned "light" in a dark OS, and on a phone
 * home screen — where this UI is pinned for a 12-hour firing — the mismatch is a
 * bright status bar over a dark app. Writing the same resolved colour into
 * *both* tags makes whichever one matches produce the right answer, without
 * having to strip the `media` attributes and give up the no-JS behaviour.
 */
function applyThemeColor(doc: Document, theme: ResolvedTheme): void {
  const tags = doc.head?.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  tags?.forEach((tag) => tag.setAttribute("content", THEME_COLORS[theme]));
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
  if (root.ownerDocument) applyThemeColor(root.ownerDocument, theme);
}
