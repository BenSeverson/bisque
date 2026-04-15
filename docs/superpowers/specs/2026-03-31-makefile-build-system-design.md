# Makefile Build System Design

## Context

The monorepo currently uses `build.sh` to orchestrate builds across 3 components (web UI, ESP-IDF firmware, iOS app). This is fragile, doesn't support partial rebuilds, and duplicates commands already defined in CI. Replace it with a standard Makefile.

## Approach

Single flat root Makefile with `.PHONY` targets delegating to underlying tools (npm, idf.py, xcodebuild). No file-level dependency tracking at the Make level — each tool handles its own incrementality.

## Makefile Targets

### Build Targets

| Target | Depends On | Command |
|--------|-----------|---------|
| `all` (default) | `firmware` | — |
| `web` | — | `cd web_ui && npm ci && npm run build` |
| `gzip` | `web` | `find` + `gzip -9 -f` on JS/CSS/HTML/SVG in `spiffs_data/www/` |
| `firmware` | `gzip` | `idf.py build` |
| `flash` | `firmware` | `idf.py flash monitor` |
| `ios` | — | `cd ios/Bisque && xcodegen generate && xcodebuild ...` |

### Lint & Format Targets

| Target | Depends On | Command |
|--------|-----------|---------|
| `lint` | `lint-web lint-c` | — |
| `lint-web` | — | `cd web_ui && npm run typecheck && npm run lint && npm run format:check` |
| `lint-c` | — | `clang-format --dry-run --Werror` on `main/` and `components/` |
| `format` | `format-web format-c` | — |
| `format-web` | — | `cd web_ui && npm run format` |
| `format-c` | — | `clang-format -i` on `main/` and `components/` |
| `typecheck` | — | `cd web_ui && npm run typecheck` |

### Check Targets

| Target | Depends On | Command |
|--------|-----------|---------|
| `check` | `check-spiffs check-firmware` | — |
| `check-spiffs` | `gzip` | `./scripts/check-spiffs-size.sh` |
| `check-firmware` | `firmware` | `./scripts/check-firmware-size.sh` |

### Clean Targets

| Target | What it removes |
|--------|----------------|
| `clean` | All build outputs |
| `clean-web` | `spiffs_data/www/*`, `web_ui/node_modules/` |
| `clean-firmware` | `idf.py fullclean` |
| `clean-ios` | `ios/Bisque/build/`, generated `.xcodeproj` |

## Dependency Chain

```
firmware → gzip → web    (sequential, mandatory)
ios                       (independent)
lint-web, lint-c          (independent, parallelizable)
```

## CI Changes

Update `.github/workflows/build.yml` to use Make targets where possible:

- `lint-web` job: `make lint-web` (still needs Node setup first)
- `lint-c` job: `make lint-c`
- `build` job: `make firmware && make check`
- `build-ios` job: `make ios` (still needs xcodegen install)

**Note:** The ESP-IDF CI action runs inside a Docker container, so `make firmware` needs `make` available in that container (it is — it's Ubuntu-based). The lint and web build steps run directly on the runner.

## What Gets Deleted

- `build.sh` — fully replaced by `make` / `make firmware`

## Design Decisions

- **All .PHONY:** The underlying tools (npm, idf.py, xcodebuild) all have their own incremental build caching. Adding file-level Make dependencies would add complexity for marginal (seconds) savings.
- **No recursive Make:** Single file is easier to maintain and understand for a small project.
- **npm ci vs npm install:** Keep `npm ci` for clean, reproducible installs (matches CI behavior).
- **gzip as separate target:** Keeps the web build and compression steps independently runnable, matching the existing `build.sh` structure.
