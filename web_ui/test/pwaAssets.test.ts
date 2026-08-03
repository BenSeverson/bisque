/**
 * The PWA shell — favicon, apple-touch-icon, manifest, theme-color — is all
 * static markup and static files. Nothing imports it, so a renamed or dropped
 * asset produces no build error, no runtime error, and no visible symptom
 * beyond the browser quietly falling back to its default icon and chrome.
 *
 * These tests are the only thing that notices. They keep three things honest:
 * every href in index.html resolves to a file in public/, every icon the
 * manifest lists exists, and the theme colours agree across index.html, the
 * manifest, and THEME_COLORS in utils/theme.ts (see #190).
 */
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { THEME_COLORS } from "../src/app/utils/theme";

// Resolved off this file, not cwd: `import.meta.url` + `fileURLToPath` is the
// usual spelling, but under the jsdom environment the global `URL` is jsdom's
// and Node's `fileURLToPath` rejects it.
const webUiRoot = resolve(import.meta.dirname, "..");
const publicPath = (name: string) => resolve(webUiRoot, "public", name);
const read = (rel: string) => readFileSync(resolve(webUiRoot, rel), "utf8");

const doc = new DOMParser().parseFromString(read("index.html"), "text/html");

/** Strip the leading "/" that makes an href root-absolute at serve time. */
function publicFileFor(href: string): string {
  expect(href.startsWith("/"), `${href} should be a root-absolute path`).toBe(true);
  return href.slice(1);
}

describe("index.html icons", () => {
  const links = [...doc.querySelectorAll<HTMLLinkElement>("link[rel]")].filter((l) =>
    ["icon", "apple-touch-icon", "manifest"].includes(l.getAttribute("rel") ?? ""),
  );

  it("declares an SVG favicon, a PNG fallback, an apple-touch-icon and a manifest", () => {
    expect(links.map((l) => l.getAttribute("rel"))).toEqual([
      "icon",
      "icon",
      "apple-touch-icon",
      "manifest",
    ]);
  });

  it.each(["favicon.svg", "favicon-32.png", "apple-touch-icon.png", "manifest.webmanifest"])(
    "ships public/%s",
    (name) => {
      expect(existsSync(publicPath(name))).toBe(true);
    },
  );

  it("points every link at a file that exists", () => {
    for (const link of links) {
      const file = publicFileFor(link.getAttribute("href") ?? "");
      expect(existsSync(publicPath(file)), `public/${file} is missing`).toBe(true);
    }
  });
});

describe("index.html theme-color", () => {
  const tags = [...doc.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')];

  it("scopes one tag per colour scheme", () => {
    expect(tags.map((t) => t.getAttribute("media"))).toEqual([
      "(prefers-color-scheme: light)",
      "(prefers-color-scheme: dark)",
    ]);
  });

  it("uses the same colours applyTheme will write back", () => {
    expect(tags.map((t) => t.getAttribute("content"))).toEqual([
      THEME_COLORS.light,
      THEME_COLORS.dark,
    ]);
  });
});

describe("index.html home-screen meta", () => {
  it.each(["mobile-web-app-capable", "apple-mobile-web-app-capable"])(
    "declares %s (iOS reads only the apple- spelling)",
    (name) => {
      expect(doc.querySelector(`meta[name="${name}"]`)?.getAttribute("content")).toBe("yes");
    },
  );
});

interface ManifestIcon {
  src: string;
  sizes: string;
  type: string;
  purpose: string;
}

interface Manifest {
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: ManifestIcon[];
}

describe("manifest.webmanifest", () => {
  const manifest = JSON.parse(read("public/manifest.webmanifest")) as Manifest;

  it("is installable: name, short_name, standalone display, icons", () => {
    expect(manifest.name).toBeTruthy();
    expect(manifest.short_name).toBeTruthy();
    expect(manifest.display).toBe("standalone");
    expect(manifest.icons.length).toBeGreaterThan(0);
  });

  it("offers both a 192 and a 512 'any' icon, plus a maskable one", () => {
    const any = manifest.icons.filter((i) => i.purpose === "any");
    expect(any.map((i) => i.sizes).sort()).toEqual(["192x192", "512x512"]);
    expect(manifest.icons.some((i) => i.purpose === "maskable")).toBe(true);
  });

  it("points every icon at a file that exists", () => {
    for (const icon of manifest.icons) {
      expect(existsSync(publicPath(icon.src)), `public/${icon.src} is missing`).toBe(true);
    }
  });

  it("keeps every URL relative so the /bisque/ demo build still resolves", () => {
    // GitHub Pages serves the demo under a base path, and nothing rewrites the
    // inside of a file copied verbatim out of public/. Root-absolute paths here
    // would 404 there while working fine on the device.
    const urls = [manifest.start_url, manifest.scope, ...manifest.icons.map((i) => i.src)];
    for (const url of urls) {
      expect(url.startsWith("/"), `${url} must be relative`).toBe(false);
    }
  });

  it("agrees with the light theme-color", () => {
    expect(manifest.theme_color).toBe(THEME_COLORS.light);
    expect(manifest.background_color).toBe(THEME_COLORS.light);
  });
});
