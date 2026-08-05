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
 * These tests close that loop. Rather than trusting a list of files, they take
 * the version from the canonical pin and hunt every copy of it across the whole
 * repo, then assert renovate.json can see each one. A pin added tomorrow in a
 * file nobody thought to enumerate — a new setup doc, a new helper script —
 * fails here until renovate.json grows a pattern for it.
 */
import { describe, it, expect } from "vitest";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const repoRoot = resolve(import.meta.dirname, "../..");
const read = (rel: string) => readFileSync(resolve(repoRoot, rel), "utf8");

/**
 * release.yml's action input is the canonical pin: it is what actually builds a
 * release, and it is the site renovate.json has always matched. Every other copy
 * of the version in the repo is downstream of it.
 */
const CANONICAL_FILE = ".github/workflows/release.yml";
const CANONICAL_PATTERN = /esp_idf_version:\s*(v\d+\.\d+\.\d+)/;

/**
 * Historical plans and specs quote whatever version was current when they were
 * written. They are a record of a past decision, so a bump must NOT rewrite
 * them — and this scan must not demand that Renovate track them.
 */
const EXCLUDED = [/^docs\/superpowers\//];

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

const canonicalVersion = CANONICAL_PATTERN.exec(read(CANONICAL_FILE))?.[1];
if (!canonicalVersion) {
  throw new Error(`no esp_idf_version pin in ${CANONICAL_FILE} — has the release build moved?`);
}
const versionLiteral = new RegExp(canonicalVersion.replace(/\./g, "\\."), "g");

/**
 * Every text file under version control, minus the historical record. Uses the
 * index rather than a directory walk so build output, node_modules and a
 * developer's untracked scratch files can't inject phantom pins.
 */
function scannableFiles(): string[] {
  const tracked = execFileSync("git", ["ls-files", "-z"], { cwd: repoRoot, encoding: "utf8" })
    .split("\0")
    .filter(Boolean);
  return tracked.filter((f) => !EXCLUDED.some((re) => re.test(f)));
}

interface Pin {
  file: string;
  line: number;
  /** Byte offset of the version within the file, for comparing against matchStrings. */
  start: number;
  text: string;
}

/** Where the canonical version literally appears, decided without consulting renovate.json. */
function findPins(file: string): Pin[] {
  let content: string;
  try {
    content = read(file);
  } catch {
    return []; // symlink into an unchecked-out submodule, or similar
  }
  if (content.includes("\0")) return []; // binary
  versionLiteral.lastIndex = 0;
  return [...content.matchAll(versionLiteral)].map((m) => {
    const before = content.slice(0, m.index);
    const lineStart = before.lastIndexOf("\n") + 1;
    return {
      file,
      line: before.split("\n").length,
      start: m.index,
      text: content.slice(lineStart, content.indexOf("\n", m.index)).trim(),
    };
  });
}

/** Offsets renovate.json's matchStrings would rewrite in a given file, and what they'd read. */
function trackedSpans(file: string): Map<number, string> {
  const content = read(file);
  const spans = new Map<number, string>();
  for (const re of matchStrings) {
    re.lastIndex = 0;
    for (const m of content.matchAll(re) as Iterable<IndexedMatch>) {
      const span = m.indices?.groups?.currentValue;
      expect(span, `${re.source} must capture a currentValue group`).toBeDefined();
      spans.set(span![0], content.slice(span![0], span![1]));
    }
  }
  return spans;
}

const files = scannableFiles();
const allPins = files.flatMap(findPins);

describe("ESP-IDF version pins", () => {
  it("finds the version in more than one place", () => {
    // A scan that has gone blind — bad cwd, `git ls-files` returning nothing,
    // a renamed canonical file — would otherwise pass everything below
    // vacuously. The whole point is that this version is copied around.
    expect(files.length).toBeGreaterThan(100);
    expect(new Set(allPins.map((p) => p.file)).size).toBeGreaterThan(1);
  });

  it("is tracked by renovate.json everywhere it appears, so one bump lands as one PR", () => {
    const untracked = allPins.filter((p) => !trackedSpans(p.file).has(p.start));
    const detail = untracked.map((p) => `  ${p.file}:${p.line}  ${p.text}`).join("\n");
    expect(
      untracked,
      `renovate.json cannot see ${untracked.length} pin(s) of ${canonicalVersion}; ` +
        `add a matchString (and a managerFilePattern if the file is new):\n${detail}`,
    ).toHaveLength(0);
  });

  it("sits in a file some managerFilePattern selects", () => {
    // Distinct from the check above: a matchString can match text in a file
    // Renovate never opens, which reads as "covered" but rewrites nothing.
    const unselected = [...new Set(allPins.map((p) => p.file))].filter(
      (f) => !filePatterns.some((re) => re.test(f)),
    );
    expect(unselected, `no managerFilePattern selects: ${unselected.join(", ")}`).toHaveLength(0);
  });

  it("agrees on one version across every site renovate.json rewrites", () => {
    // Catches the inverse drift: a tracked site left behind at an older version
    // still gets rewritten, but disagrees with the canonical pin until it does.
    const disagreements: string[] = [];
    for (const file of files.filter((f) => filePatterns.some((re) => re.test(f)))) {
      for (const [offset, value] of trackedSpans(file)) {
        if (value !== canonicalVersion) disagreements.push(`${file}@${offset} has ${value}`);
      }
    }
    expect(
      disagreements,
      `${CANONICAL_FILE} pins ${canonicalVersion}, but:\n  ${disagreements.join("\n  ")}`,
    ).toHaveLength(0);
  });
});
