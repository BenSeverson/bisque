/**
 * The pinned ESP-IDF toolchain version is written out by hand in 21 places —
 * a workflow input, three container image tags, a ccache key, a shell default,
 * a shields.io badge, and a dozen prose mentions. Renovate is the only thing
 * that bumps any of them, and it can only bump what one of its `matchStrings`
 * in renovate.json actually matches.
 *
 * Before #26 that was a single regex hitting a single file, so every release
 * needed a manual fan-out commit (b63ed0e) to carry the new version to the
 * other twenty sites, and anything missed went stale in silence — a devcontainer
 * or CI image drifting off the version the README tells contributors to install.
 *
 * These tests close that loop. They rediscover the pins independently of the
 * config (any `vX.Y.Z` on a line that mentions ESP-IDF), then assert the config
 * can see every one. A new pin site added tomorrow fails here until renovate.json
 * grows a pattern for it, rather than going quietly untracked.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const repoRoot = resolve(import.meta.dirname, "../..");
const read = (rel: string) => readFileSync(resolve(repoRoot, rel), "utf8");

/**
 * Every file that hard-codes the toolchain version. Deliberately enumerated
 * rather than globbed: docs/superpowers/ holds historical plans and specs that
 * quote whatever version was current when they were written, and those must
 * NOT be rewritten by a bump.
 */
const PINNED_FILES = [
  ".github/workflows/release.yml",
  ".github/workflows/build.yml",
  ".github/workflows/codeql.yml",
  ".devcontainer/Dockerfile",
  ".devcontainer/devcontainer.json",
  ".claude/hooks/install-esp-idf.sh",
  "scripts/idf-env.sh",
  "README.md",
  "RELEASING.md",
  "docs/devcontainer.md",
  "docs/cloud-dev.md",
];

interface CustomManager {
  customType: string;
  managerFilePatterns: string[];
  matchStrings: string[];
  depNameTemplate?: string;
}

const renovate = JSON.parse(read("renovate.json")) as { customManagers: CustomManager[] };

const idfManager = renovate.customManagers.find((m) => m.depNameTemplate === "espressif/esp-idf");
if (!idfManager) throw new Error("renovate.json has no custom manager for espressif/esp-idf");

/** Renovate file patterns are regexes wrapped in slashes; unwrap to a JS RegExp. */
function unwrapPattern(pattern: string): RegExp {
  const match = /^\/(.*)\/$/.exec(pattern);
  expect(match, `${pattern} should be a /regex/, not a glob`).not.toBeNull();
  return new RegExp(match![1]);
}

const filePatterns = idfManager.managerFilePatterns.map(unwrapPattern);
// `d` gives us match.indices, so a pin can be located by offset rather than by
// value — two pins on one line (README's badge and its alt text) stay distinct.
// tsconfig targets ES2020, whose lib predates the flag, so the group spans are
// typed here rather than by bumping the whole project's lib for one test.
type IndexedMatch = RegExpMatchArray & {
  indices?: { groups?: Record<string, [number, number] | undefined> };
};
const matchStrings = idfManager.matchStrings.map((s) => new RegExp(s, "gd"));

interface Pin {
  file: string;
  line: number;
  version: string;
  /** Byte offset of the version within the file, for comparing against matchStrings. */
  start: number;
  text: string;
}

/** Find version pins the way a human reading the file would, ignoring renovate.json. */
function findPins(file: string): Pin[] {
  const content = read(file);
  const pins: Pin[] = [];
  let offset = 0;
  content.split("\n").forEach((text, index) => {
    if (/idf|espressif/i.test(text)) {
      for (const m of text.matchAll(/v\d+\.\d+\.\d+/g)) {
        pins.push({
          file,
          line: index + 1,
          version: m[0],
          start: offset + m.index,
          text: text.trim(),
        });
      }
    }
    offset += text.length + 1; // +1 for the \n split consumed
  });
  return pins;
}

const allPins = PINNED_FILES.flatMap(findPins);

/** Offsets renovate.json's matchStrings would rewrite in a given file. */
function trackedOffsets(file: string): Set<number> {
  const content = read(file);
  const offsets = new Set<number>();
  for (const re of matchStrings) {
    re.lastIndex = 0;
    for (const m of content.matchAll(re) as Iterable<IndexedMatch>) {
      const span = m.indices?.groups?.currentValue;
      expect(span, `${re.source} must capture a currentValue group`).toBeDefined();
      offsets.add(span![0]);
    }
  }
  return offsets;
}

describe("ESP-IDF version pins", () => {
  it("finds every file it claims to cover", () => {
    // A renamed or deleted file would otherwise silently shrink the scan to zero
    // pins and pass everything below.
    expect(allPins.length).toBeGreaterThan(0);
    for (const file of PINNED_FILES) {
      expect(findPins(file).length, `${file} pins no ESP-IDF version any more`).toBeGreaterThan(0);
    }
  });

  it("agrees on one version everywhere", () => {
    const versions = [...new Set(allPins.map((p) => p.version))];
    const detail = allPins.map((p) => `${p.file}:${p.line} ${p.version}`).join("\n");
    expect(versions, `pins disagree:\n${detail}`).toHaveLength(1);
  });
});

describe("renovate.json coverage", () => {
  it.each(PINNED_FILES)("matches %s against a managerFilePattern", (file) => {
    expect(
      filePatterns.some((re) => re.test(file)),
      `${file} pins the toolchain but no managerFilePattern selects it`,
    ).toBe(true);
  });

  it("tracks every pin, so one bump lands as one PR", () => {
    const untracked: Pin[] = [];
    for (const file of PINNED_FILES) {
      const tracked = trackedOffsets(file);
      untracked.push(...findPins(file).filter((p) => !tracked.has(p.start)));
    }
    const detail = untracked.map((p) => `  ${p.file}:${p.line}  ${p.text}`).join("\n");
    expect(
      untracked,
      `renovate.json cannot see ${untracked.length} pin(s); add a matchString:\n${detail}`,
    ).toHaveLength(0);
  });
});
