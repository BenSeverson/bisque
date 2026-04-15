# GitHub README Redesign

## Problem

The Bisque GitHub repo page is basic — no logo, no badges, screenshots dumped sequentially, and dense content (wiring tables, BOM) creates a wall-of-text feel. The project deserves a first-class presentation that matches the quality of the firmware, web UI, and iOS app.

## Design

### 1. SVG Banner (`docs/logo-banner.svg`)

A centered hero banner containing:
- Flame/kiln SVG icon (stylized oval with inner flame shape, orange `#ff6b35` / `#ffaa44`)
- "bisque" wordmark (bold, white text)
- Tagline: "Open-source ESP32-S3 ceramic kiln controller"
- No tech stack subtitle
- Gradient background (`#1a1a2e` → `#16213e` → `#0f3460`)

The SVG should render well on both light and dark GitHub themes. Use a rounded rectangle background so it works on any page color.

### 2. Badges

Three badges below the banner (using shields.io or GitHub's native badge URLs):
- **Build status** — linked to GitHub Actions workflow (`.github/workflows/build.yml`)
- **ESP-IDF version** — static badge showing "ESP-IDF v6.0"
- **License** — MIT badge, linked to LICENSE file

### 3. Screenshot Layout

Restructure the existing screenshots into a hero + grid:
- **Hero:** `docs/screenshots/web-dashboard.png` at 600px width, centered
- **Grid:** 4 LCD screenshots (`lcd-home.png`, `lcd-chart.png`, `lcd-profiles.png`, `lcd-firing.png`) side by side, each ~160px width
- **iOS:** `docs/screenshots/ios-app.png` at 280px width, centered below

### 4. Content Reorganization

Keep all existing content. Changes to structure:

**Always visible:**
- Features (all 7 subsections with bullets — unchanged)
- Getting Started (prerequisites, firmware, web UI, iOS — unchanged)
- Architecture (directory tree — unchanged)

**Collapsible (`<details>` / `<summary>`):**
- Bill of Materials (table + safety warning blockquote)
- Wiring (all pin tables + diagram links)
- Simulator / Mock Server (web UI dev, iOS, LCD simulator sections)

### 5. New Files

- `docs/logo-banner.svg` — the hero banner
- `LICENSE` — MIT license, copyright holder "Ben" (or full name from git config), year 2026

### 6. Section Order

1. Banner (SVG image, centered)
2. Badges (centered row)
3. Screenshots (hero + grid + iOS)
4. Features
5. Bill of Materials (collapsible, includes safety warning)
6. Wiring (collapsible)
7. Getting Started
8. Simulator / Mock Server (collapsible)
9. Architecture
10. License footer line

## Files Modified

- `README.md` — full rewrite with new structure
- `docs/logo-banner.svg` — new file
- `LICENSE` — new file

## Verification

- Open README.md on GitHub (or use `grip` / VS Code markdown preview) and confirm:
  - Banner SVG renders correctly
  - Badges display and link properly
  - Screenshots display in hero + grid layout
  - Collapsible sections expand/collapse
  - All existing content is preserved (no information lost)
  - Page looks good on both light and dark GitHub themes
