import { afterEach, describe, it, expect } from "vitest";
import {
  readStoredPreference,
  writeStoredPreference,
  resolveTheme,
  applyTheme,
  THEME_COLORS,
  THEME_STORAGE_KEY,
} from "./theme";

function memoryStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
  };
}

const throwingStorage = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("SecurityError");
  },
};

describe("readStoredPreference", () => {
  it("defaults to 'system' when nothing is stored", () => {
    expect(readStoredPreference(memoryStorage())).toBe("system");
  });

  it("returns each valid stored preference", () => {
    for (const p of ["light", "dark", "system"] as const) {
      expect(readStoredPreference(memoryStorage({ [THEME_STORAGE_KEY]: p }))).toBe(p);
    }
  });

  it("falls back to 'system' for a hand-edited junk value", () => {
    expect(readStoredPreference(memoryStorage({ [THEME_STORAGE_KEY]: "chartreuse" }))).toBe(
      "system",
    );
  });

  it("survives storage that throws (Safari private mode)", () => {
    expect(readStoredPreference(throwingStorage)).toBe("system");
  });

  it("survives storage being absent entirely (SSR/no-DOM)", () => {
    expect(readStoredPreference(undefined)).toBe("system");
  });
});

describe("writeStoredPreference", () => {
  it("persists under the shared key", () => {
    const s = memoryStorage();
    writeStoredPreference(s, "dark");
    expect(s.map.get(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("does not throw when storage does", () => {
    expect(() => writeStoredPreference(throwingStorage, "dark")).not.toThrow();
  });

  it("does not throw when storage is absent", () => {
    expect(() => writeStoredPreference(undefined, "dark")).not.toThrow();
  });
});

describe("resolveTheme", () => {
  it("pins explicit preferences regardless of the OS setting", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("follows the OS when set to 'system'", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

describe("applyTheme", () => {
  it("adds .dark and sets color-scheme for dark", () => {
    const root = document.createElement("html");
    applyTheme(root, "dark");
    expect(root.classList.contains("dark")).toBe(true);
    expect(root.style.colorScheme).toBe("dark");
  });

  it("removes .dark again when switching back to light", () => {
    const root = document.createElement("html");
    applyTheme(root, "dark");
    applyTheme(root, "light");
    expect(root.classList.contains("dark")).toBe(false);
    expect(root.style.colorScheme).toBe("light");
  });

  it("does not throw when the document has no theme-color tags", () => {
    const root = document.createElement("html");
    expect(() => applyTheme(root, "dark")).not.toThrow();
  });
});

describe("applyTheme / theme-color", () => {
  /** Stand in for the two media-scoped tags index.html ships. */
  function seedMetaTags(): HTMLMetaElement[] {
    return ["(prefers-color-scheme: light)", "(prefers-color-scheme: dark)"].map((media) => {
      const meta = document.createElement("meta");
      meta.setAttribute("name", "theme-color");
      meta.setAttribute("media", media);
      meta.setAttribute("content", "#123456");
      document.head.appendChild(meta);
      return meta;
    });
  }

  afterEach(() => {
    document.head.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.remove());
  });

  it("writes the resolved colour into every theme-color tag", () => {
    const [light, dark] = seedMetaTags();
    applyTheme(document.createElement("html"), "dark");
    // Both, not just the matching one: the tags stay media-scoped for the no-JS
    // case, so the only way an explicit preference wins is to agree on a colour.
    expect(light.getAttribute("content")).toBe(THEME_COLORS.dark);
    expect(dark.getAttribute("content")).toBe(THEME_COLORS.dark);
  });

  it("follows a switch back to light", () => {
    const [light, dark] = seedMetaTags();
    const root = document.createElement("html");
    applyTheme(root, "dark");
    applyTheme(root, "light");
    expect(light.getAttribute("content")).toBe(THEME_COLORS.light);
    expect(dark.getAttribute("content")).toBe(THEME_COLORS.light);
  });

  it("leaves the media attributes alone", () => {
    const [light, dark] = seedMetaTags();
    applyTheme(document.createElement("html"), "dark");
    expect(light.getAttribute("media")).toBe("(prefers-color-scheme: light)");
    expect(dark.getAttribute("media")).toBe("(prefers-color-scheme: dark)");
  });
});
