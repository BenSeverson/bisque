import { describe, it, expect } from "vitest";
import {
  readStoredPreference,
  writeStoredPreference,
  resolveTheme,
  applyTheme,
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
});
