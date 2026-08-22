# Bisque — Kiln Controller Firmware

## Project Overview

ESP32-S3 ceramic kiln controller. Firmware built with **ESP-IDF** (C), using **LVGL v9.5.0** for the embedded display UI. The display is a **4.0" ST7796S TFT LCD** (480x320 landscape, SPI, RGB565).

## Build & Flash

```bash
./build.sh          # Build web UI (npm ci + vite), gzip into spiffs_data/www/, then idf.py build
idf.py build        # Firmware-only rebuild (skips web UI)
idf.py flash monitor  # Flash and monitor
```

**A bare `idf.py` only works in a shell that has already sourced ESP-IDF's `export.sh`** — which non-interactive shells (agent tool calls, git hooks, `make` recipes, CI) never do, since they read no rc files and get a fresh shell per command. Sourcing it in one command and running `idf.py` in the next does *not* work; the activation is lost with the shell.

So prefer `make firmware` / `make build` / `./build.sh` over a raw `idf.py` — they source `scripts/idf-env.sh` first, which finds a local install (honoring `IDF_PATH`, else the usual `~/esp-idf`, `~/esp/`, `~/.espressif/v*/`, `/opt/` layouts) and no-ops when the shell is already activated. Note that "activated" means `IDF_PATH`/`IDF_PYTHON_ENV_PATH`/`ESP_IDF_VERSION` are exported, not merely that `idf.py` is on PATH — a shell can inherit ESP-IDF's PATH entries without the rest of the environment, and IDF 6's `idf.py` then dies on a NULL `ESP_IDF_VERSION`. For a one-off `idf.py` invocation with no `make` target, activate in the *same* command:

```bash
. ./scripts/idf-env.sh && idf.py flash monitor
```

**Never conclude ESP-IDF is unavailable from an ad-hoc shell probe, and never ship firmware changes unbuilt because you think it is.** `scripts/idf-env.sh` is the only thing that gets to answer that question — run it, or just run `make firmware` and read the error. A hand-written `ls ~/esp* /opt/esp* ~/.espressif` is not a substitute and has already produced a false negative: the shell here is **zsh**, where an unmatched glob aborts the *entire* command line with `no matches found` before any other argument is listed, so one non-existent path makes every real one invisible. (`find ~ -maxdepth 4` fails differently — the install is deeper than that.) The cost of getting this wrong is high and silent: `tests/host/` links a handful of components, so a change to `api_handlers.c`, `ws_handler.c`, `main/`, or anything else outside that set is **completely uncompiled** by `make test`. "CI will catch it" is not a verification step.

Build profile: `./build.sh` builds release (`-O2`) by default. `BISQUE_PROFILE=debug ./build.sh` overlays `sdkconfig.defaults.debug` (`-Og`, full assertions, and the LVGL on-screen FPS/heap overlays) for on-device profiling.

Web UI demo: `cd web_ui && npm run build:demo` produces a static, serverless build (`BISQUE_DEMO=true` → the `__DEMO__` flag) that bundles the in-browser kiln simulator (`web_ui/mock-server/`, shared with the dev server via the browser-safe `router.ts`/`installDemo.ts`) and is published to GitHub Pages (`https://benseverson.github.io/bisque/`) by `.github/workflows/pages.yml` on every push to `main`. The simulator is loaded via a `__DEMO__`-gated dynamic import, so it is tree-shaken out of the firmware build and flash size is unaffected. Hardware-only controls (OTA, Wi-Fi setup, relay test) are hidden in the demo. Because that import is tree-shaken out of every non-demo bundle, the ordinary `npm run build` cannot catch a break in it — CI's `lint-web` job runs `make web-demo` so a broken demo fails the PR rather than the post-merge Pages deploy.

Build system: **CMake** via ESP-IDF's `idf.py`. Each `components/` subdirectory is an ESP-IDF component with its own `CMakeLists.txt`.

The top-level `Makefile` is a thin dispatcher over the existing scripts and `idf.py` — `make help` lists every developer entry point (`build`, `web`, `firmware`, `sim`, `test`, `lint`, `format`, `size`, `clang-tidy`, `cppcheck`, `ci`, `clean`). CI calls the same targets, so `make ci` is the closest local approximation of the PR check.

## Code Style

After editing any firmware C/H files under `main/` or `components/`, run `clang-format -i` on the changed files (or `./scripts/format.sh` to format all firmware + web sources). The CI format check uses the repo's `.clang-format`; unformatted code will fail the `clang-format` job.

`./scripts/lint.sh` (also installed as the pre-push hook via `./scripts/install-hooks.sh`) is a **subset** of CI: it runs `clang-format --dry-run` plus the web UI typecheck/lint/format checks. It does **not** run `clang-tidy` or `cppcheck`, so a push that passes `lint.sh` can still fail the `build` job's static-analysis steps. Both are available locally — `make clang-tidy` (after a firmware build) and `make cppcheck` — and are worth running on any firmware change.

Reading `make clang-tidy` output takes a filter. It reports findings from every header a TU pulls in, and `.clang-tidy`'s `HeaderFilterRegex` (`(main|components)/.*\.h$`) matches ESP-IDF's *own* `components/` too, so hundreds of lines come from `~/.espressif/` and `managed_components/` and are not yours. Apply CI's gate, then narrow to the repo:

```bash
grep -E ':[0-9]+:[0-9]+: (warning|error): ' warnings.txt | grep -v clang-diagnostic- | grep "$PWD/\(components\|main\)/"
```

`readability-redundant-declaration` is an error here, and it is the one that bites on refactors: declaring a function in both `web_server.h` and `api_json.h` is silent until some translation unit includes both. Declare each function in exactly one header.

## Testing

```bash
make test        # Everything portable: test-host + test-web
make test-host   # Unity C unit tests via ctest (tests/host/, no hardware needed)
make test-web    # Vitest — depends on `fixtures`, which must run first
make fixtures    # Regenerate JSON API fixtures from the C code
make test-ios    # XCTest on a simulator — macOS + Xcode only, NOT part of `test`
```

The web tests are **contract tests against the firmware**: `make fixtures` builds the `api_fixtures` target from `tests/host/` to emit real JSON from the C serializers, and Vitest asserts the web UI parses it. `test-web` depends on `fixtures`, so run it via `make` rather than `npm run test:run` directly. Host tests cover PID, cone table, firing helpers, firing scenarios (via `plant.c`, a simulated kiln thermal model), and API JSON.

Missing or stale fixtures **fail** the contract suite rather than skipping it (#173), so `npm run test:run` / `vitest --watch` can't quietly go green having validated nothing. Alongside the JSON, `make fixtures` writes `_manifest.json` with a SHA256 of every source that can change the emitted bytes — the list lives in `tests/host/fixture_sources.txt` (add a file there when a new source starts feeding a `build_*_json()`), and the test re-hashes it. Editing a serializer without regenerating is therefore a failure with a "run `make fixtures`" message. `BISQUE_SKIP_CONTRACTS=1` is the explicit opt-out for environments where the C build can't run.

The zod schemas those tests validate against live in **`web_ui/src/app/schemas/`** — `api.ts` for REST response shapes, `ws.ts` for the WebSocket frames, `kiln.ts` for the form/import schemas — and they are the single source of truth for the frontend's types too: `StatusResponse`, `SystemInfo`, `WifiInfo`, `OtaStatus`, `TempUpdateData`, `FiringProfile`, `KilnSettings` and friends are `z.infer`red from them and re-exported by `services/api.ts` / `services/websocket.ts` / `types/kiln.ts` (#176, #174). Change a response shape in the schema only; the interfaces follow, and every call site that no longer matches fails `npm run typecheck`. The schemas are imported for their types alone, so they stay tree-shaken out of the bundle — verified byte-identical output.

Every payload the device emits — including the WebSocket frames and `/system`, `/wifi`, `/ota/check`, `/ota/status` — goes through a `build_*_json()` in `api_json.c`, never inline `cJSON_Add*` at the handler. That is what makes it fixture-dumpable from the host; JSON assembled in `api_handlers.c` or `ws_handler.c` cannot be, and is invisible to the contract test by construction (#174). Handlers gather ESP-specific inputs into a plain struct and delegate. The contract test also rebuilds each schema `.strict()` before checking the fixtures, so a *new* firmware field is a failure until the schema models it — the app-facing schemas stay non-strict so a newer kiln still parses in an older tab.

**Device log / diagnostics bundle (#189).** `components/device_log` chains an `esp_log_set_vprintf()` hook that tees every `ESP_LOGx` line into a fixed RAM ring (`CONFIG_KILN_LOG_BUFFER_BYTES`, default 6 KiB) while still writing to the UART; `GET /api/v1/log` serves it. The line-assembly and eviction rules live in `log_sink.c` — no ESP-IDF, caller-supplied storage, caller-held lock — precisely so `tests/host/test_log_sink.c` can drive them; `device_log.c` is only the hook, the mutex and the allocation. RAM, not SPIFFS: a firing logs continuously and rotation would spend the flash's erase budget, so the buffer does not survive a reboot. Settings → Diagnostics → **Download Diagnostics** bundles `/log` + `/system` + `/settings` into one JSON file via `utils/diagnostics.ts`, which is built from `Promise.allSettled` on purpose — a kiln on firmware older than `/log` 404s it, and the bundle records the failed section in `errors` rather than downloading as if it were complete. Nothing secret goes in: it takes the `/settings` *response*, where the firmware has already replaced the API token with `apiTokenSet`.

Error bodies are part of the contract too: the firmware answers a failed request with the bare message (`httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing ssid")`), no JSON envelope, and the mock-server's `apiError()` matches it verbatim. `services/api.ts` reads `res.text()` on any non-2xx, so a wrapped body would show up in the toast braces and all.

**Component and hook tests** run in the same `app` (jsdom) project via `@testing-library/react` (#172). Four pieces of wiring make them work, and all four are easy to trip over:

- `src/app/test/setup.ts` is the project's `setupFiles`. Because `globals: false`, jest-dom's matchers and Testing Library's `cleanup` do not self-register — it attaches both, plus the browser APIs jsdom lacks and Radix calls unconditionally (`ResizeObserver`, `matchMedia`, pointer capture, `scrollIntoView`). A component that fails on layout measurement before rendering anything is almost always a missing entry here.
- `vitest.config.ts` defines `__DEMO__: false`. Components branch on it to hide hardware-only controls; without the define a component test crashes on an undefined global.
- `src/app/test/queryWrapper.tsx` builds the React Query provider. `gcTime: Infinity` is deliberate — an entry seeded with `setQueryData` has no observer, and a zero gcTime collects it before an assertion can read it back.
- jsdom's `window.location` is unforgeable, so anything needing a different page URL (the wss:// upgrade in `websocket.secure.test.ts`) needs its own file with a `@vitest-environment-options` docblock rather than a redefine.

`services/websocket.ts` is tested against a fake `WebSocket` under fake timers, and the reconnect assertions count `vi.getTimerCount()` rather than sockets: `connect()`'s own idempotence swallows surplus timers that fire in the same tick, so counting sockets would pass with the scheduler's dedupe guard deleted.

## Display Simulator

```bash
make sim          # cmake -S simulator -B simulator/build && bisque_sim --diff
make sim-verify   # same build, then bisque_sim --verify (state assertions, no pixels)
```

Builds the LVGL UI against SDL2 on the host and renders each scene, diffing it against the baselines at `docs/screenshots/lcd-<scene>.png`. **Use this to validate any `components/display/` change without flashing hardware.** `bisque_sim --screenshot` rewrites those baselines — run it (and eyeball the result) when a UI change is intentional, since the README screenshots come from the same files.

**Pixel diffing has a blind spot, so `--verify` complements it.** The chart's "actual" temperature series is drawn with 0x0 point markers, so plotted points at non-adjacent indices are invisible in a capture — a wiped chart and a populated one can render identically. Stale cached state (e.g. a peak temperature carried between firings) likewise only shows up across a multi-step sequence no single scene expresses. `--verify` drives `dashboard_update()` through those sequences and asserts on the resulting LVGL tree (chart series contents, label text), exiting non-zero on failure. Add a check there — not a new baseline — when a fix is about *state surviving a transition* rather than appearance. It runs in CI ahead of the pixel diff so a state regression is reported on its own rather than buried in a wall of screenshot failures.

**Captures come from an offscreen SDL render target, never the window back buffer.** LVGL's SDL driver presents at the end of every flush, and a presented back buffer is invalidated by definition — `SDL_RenderReadPixels` on it returns a recycled swapchain image (two presents stale on macOS/Metal), which made `--diff` compare each scene against the wrong baseline (#196). `read_current_pixels()` in `simulator/main.c` binds its own render target instead. `--diff` and `--screenshot` both run `capture_self_test()` first, which draws two known full-screen colours and asserts each capture returns the colour just drawn, so a regression of that class fails with one line naming the harness instead of 15 bogus scene diffs.

ESP-IDF calls are stubbed in `simulator/mock_esp.c`, and the simulator has its own `simulator/lv_conf.h` — LVGL config changes must be mirrored there or the sim silently diverges from the device.

## iOS App

`ios/Bisque/` is a SwiftUI app (iOS 17+, Swift 6) for full remote control, plus a `BisqueLiveActivity` target. The Xcode project is **generated by XcodeGen** — edit `ios/Bisque/project.yml`, not `Bisque.xcodeproj`, then:

```bash
cd ios/Bisque && xcodegen generate && open Bisque.xcodeproj
cd web_ui && npm run mock-server   # HTTP + WS on :8080; tap "Use Mock Server" in the sim
```

Versioning for firmware, web UI, and iOS is unified off git tags via `scripts/version.sh`.

`ConnectionView` lists kilns found by `Networking/KilnDiscovery.swift` rather than
asking for an IP address. The firmware advertises `_http._tcp` with **no TXT
record** (`main/main.c`), so a browse result is only a candidate: each one is
resolved (via an `NWConnection` to the service endpoint — there is no
resolve-only API) and then probed with a real `GET /api/v1/status`. A `401`
counts as a kiln only when `WWW-Authenticate` or the Bonjour instance name says
Bisque, otherwise every password-protected device on the LAN would list as one.
If you change the mDNS advertisement or the auth challenge in
`components/web_server/api_handlers.c`, that classifier is what breaks.

A connection remembers both the address and the Bonjour instance name behind
it. The address is what the next launch dials; the name is the fallback for when
a DHCP lease has moved the kiln, in which case `connect()` re-resolves the name
once and retries. That retry fires only after an *unreachable* result and only
when the resolved address actually differs — a 401 means the kiln was found, and
a kiln that is simply off should fail once, not twice. A hand-typed address
carries no service name, so it never re-resolves.

Discovery needs `NSBonjourServices` and `NSLocalNetworkUsageDescription`; both
live in `project.yml` under `targets.Bisque.info.properties` — `Bisque/Info.plist`
is **generated** from it by xcodegen, so edit the yml and regenerate.

iOS unit tests live in `ios/Bisque/BisqueTests/` and run via `make test-ios`.
They are **not** in `make test` — that runs in the Linux container CI uses for
firmware and web, and these need a Mac with a simulator. `scripts/pick-simulator.sh`
chooses the destination at run time so no device name is pinned.

`FirmwareContractTests` is the iOS half of the same firmware contract the web
UI checks (#154): it decodes the `make fixtures` JSON with the app's own
`Codable` models, so a renamed or retyped key fails the build rather than
reaching a user as `APIError.decodingError`. `test-ios` therefore depends on
`fixtures`, exactly as `test-web` does, and missing or stale fixtures **fail**.
`BISQUE_SKIP_CONTRACTS=1 make test-ios` is the opt-out, and the target has to do
two things to honour it: drop the `fixtures` prerequisite (a prerequisite runs
whatever the recipe would have, so it would otherwise start the very C build the
flag exists to avoid) and re-export the flag as
`TEST_RUNNER_BISQUE_SKIP_CONTRACTS` — xcodebuild forwards that prefix and
nothing else, so the plain name set on a bare `xcodebuild test` never reaches
the simulator and the suite runs anyway. Three tables in that file must stay
honest, and each one fails loudly when it doesn't: `decoded` (fixture → model),
`notModelled` (endpoints iOS deliberately doesn't call), and `knownUnmodelled`
(fields the firmware emits that the app drops — `Codable` ignores unknown keys
silently, so this is the Swift stand-in for the web schemas' `.strict()` pass).
A new fixture fails until it lands in one of them. The fixtures are read off
disk via `#filePath` rather than bundled as a resource: `tests/host/build/`
doesn't exist when xcodegen generates the project, so it can't be declared one.

Two gotchas
worth knowing before you debug the wrong thing: `BISQUE_MARKETING_VERSION` /
`BISQUE_BUILD_NUMBER` must be set or the simulator refuses to install the app
(empty `CFBundleVersion` on the Live Activity extension, reported as
"bundleVersion must be set in placeholder attributes"), and xcodegen must run
*without* them so the committed pbxproj keeps its `${BISQUE_*}` placeholders —
xcodebuild expands those from its own environment. The `test-ios` target handles
both.

**CI builds iOS with Xcode 16.4; a current Mac has Xcode 26.** That gap is
wide enough to compile differently, so a green `make test-ios` locally is not
proof CI will pass. The one that has already bitten: `XCTestCase.setUp()` /
`tearDown()` are nonisolated in the Xcode 16 XCTest and `@MainActor` in the
Xcode 26 one, so an override touching `@MainActor` test state builds locally and
fails on CI. Avoid overriding them — set fixtures up inside each test instead.

## Project Structure

```
components/
  app_config/       # Pin definitions, hardware constants
  display/          # LVGL UI — all screens, init, task loop
  status_led/       # WS2812B status LED driver
  firing_engine/    # Firing profile execution, PID integration
  pid_control/      # PID temperature controller
  thermocouple/     # MAX31856 SPI thermocouple driver (2 channels)
  safety/           # Safety watchdog, over-temp protection
  history/          # Firing history storage (NVS)
  cone_table/       # Ceramic cone temperature lookup
  device_log/       # In-RAM log ring behind GET /api/v1/log
  web_server/       # HTTP API server
  wifi_manager/     # Wi-Fi provisioning
  ota/              # GitHub-backed OTA firmware updates
main/               # Entry point, task creation
web_ui/             # Frontend web dashboard (separate from LVGL UI)
ios/Bisque/         # SwiftUI companion app (see below)
simulator/          # Host LVGL/SDL2 build of the display UI
tests/host/         # Unity host unit tests + API fixture generator
hardware/kicad/     # Generated KiCad project for the single-board PCB
docs/               # Pin map, task/timer map, roadmap, screenshots
spiffs_data/        # SPIFFS filesystem image for web assets
partitions.csv      # ESP32 partition table (16MB, OTA-enabled)
Makefile            # Dispatcher over every dev entry point (`make help`)
```

### Web UI icons (PWA)

`web_ui/public/` holds the favicon, apple-touch-icon, manifest icons, and
`manifest.webmanifest` — Vite copies the directory verbatim into the bundle, so
these ship in SPIFFS and are served by the static handler.

The PNGs are **generated, committed artifacts**. Edit the SVG sources in
`web_ui/icons/` (or `web_ui/public/favicon.svg`, which is hand-written and
shipped as-is), then:

```bash
make web-icons
```

That rasterizes with whichever of rsvg-convert / cairosvg / `sips` is installed,
then losslessly re-encodes via `scripts/optimize_png.py` — macOS `sips` writes
unfiltered RGBA PNGs, which costs ~4.5x on the gradient icons. It is deliberately
**not** part of `build.sh` or CI, so no SVG rasterizer sits on the critical path
of a firmware build; regenerate and commit by hand.

Icon art mirrors the app's own header logo (the Lucide `Flame` on an
orange→red gradient tile), *not* the LCD splash mark in
`components/display/assets/` — the two brand marks differ on purpose. Keep the
theme colours in `index.html`, `manifest.webmanifest`, and `THEME_COLORS` in
`src/app/utils/theme.ts` in agreement; `web_ui/test/pwaAssets.test.ts` enforces
that, and that every referenced icon file actually exists.

Anything new under `www/` that should be gzipped needs adding to the `find` in
**both** `build.sh` and the Makefile's `gzip` target, and to `get_mime_type()` in
`components/web_server/web_server.c`.

## Display / UI System

### Hardware

- **Panel:** ST7796S, 480x320px (landscape), 16-bit RGB565, BGR byte order
- **Interface:** SPI @ 40 MHz (SPI2_HOST)
- **Pins:** MOSI=11, SCLK=12, CS=8, DC=9, RST=46, BL=3 (active-high)
- **Input:** 5-way nav switch (Up=GPIO38, Down=GPIO39, Left=GPIO40, Right=GPIO41, Center/Select=GPIO42), active-low with pull-up, 50ms debounce. Source of truth: `components/app_config/include/app_config.h` (`APP_PIN_BTN_*`). GPIO 4/2/1 are the rev B board's three protected dry-contact inputs (lid switch, gas-flow interlock, spare — see below); GPIO 5/6 are the touch controller's CS/IRQ (no touch driver yet). Do not reuse the rev A nav-button map.
- **Lid switch (`CONFIG_KILN_PIN_LID_SWITCH`, default GPIO 4 to match the rev B PCB's J11 protected-input terminal; set -1 if not fitted — an enabled but unwired input reads open and holds the SSR off, so it needs a switch or a jumper to GND):** a lid/door interlock (#83). Responsibility splits across two components and it is easy to put a change in the wrong one: **`safety` owns the pin** (polarity, the asymmetric debounce in `safety_helpers.c`, and a hard SSR gate in `ssr_window_apply()` beside the emergency-stop gate), while **`firing_engine` owns the policy** — it reads `lid_mode` from `kiln_settings_t` and decides what an open lid means for firing status and the program clock. Three modes: `warn` (report only), `pause` (hold the program, auto-resume on close — the ceramic convention, and the default) and `interlock` (elements off, program keeps running — the heat-treat oven convention, where the door is opened at temperature by design). Two non-obvious consequences: `interlock` advances the elapsed accumulator itself because its early return never reaches the bottom of the tick, and it re-arms the not-rising window on lid close, since a long door-open is a real stall by that watchdog's measure. Reported as `lidOpen`, **omitted entirely when no switch is fitted**, exactly as `ventActive` is. It is a supplementary interlock, not a safety device — the real protection is a mechanical microswitch in series with the element contactor, and the Kconfig help says so.
- **Rendering:** Partial refresh, double-buffered DMA (30 rows), ~30 FPS

### LVGL Configuration

- LVGL v9.5.0, `LV_OS_FREERTOS` (LVGL lock API)
- Color depth: 16-bit, `LV_COLOR_16_SWAP=y`
- Memory pool: 24KB (`CONFIG_LV_MEM_SIZE_KILOBYTES` in `sdkconfig.defaults`)
- Fonts enabled: Montserrat 24, 36, 48 (default: 24)
- Widgets in use: label, chart, list, buttonmatrix, obj (containers/dots)
- Layout: mostly absolute positioning via `lv_obj_set_pos()`/`lv_obj_align()`. Flex (`LV_USE_FLEX`) is enabled and used by `modal_profile_picker.c` to stack each list row's name+subtitle; grid is compiled out.
- Theme: a custom theme registered via `lv_display_set_theme()`. Source: `components/display/ui_theme.c`. It applies shared `lv_style_t` defaults by widget class — screen baseline (white bg, black text, base font), plain panels (transparent + chrome-free), buttons (radius + bg_opa + focused outline), lists and list buttons (with focused state), and chart parts (frame + grid + items + indicator). Tweak the styles there to retune the whole UI.

### Design Tokens (defined in `components/display/ui_common.h`)

**Colors:**
| Token | Value | Usage |
|---|---|---|
| `UI_COLOR_BG` | `#FFFFFF` | Screen backgrounds |
| `UI_COLOR_TEXT` | `#000000` | Primary text |
| `UI_COLOR_TEXT_DIM` | `#5C5C5C` | Secondary/dimmed text |
| `UI_COLOR_HEATING` | `#E07A00` | Heating status, chart line |
| `UI_COLOR_HOLDING` | `#E0B800` | Holding status |
| `UI_COLOR_COOLING` | `#1E66D0` | Cooling status |
| `UI_COLOR_ERROR` | `#CC1F1F` | Error status |
| `UI_COLOR_COMPLETE` | `#1E9E3A` | Firing complete |
| `UI_COLOR_PAUSED` | `#E0B800` | Paused (same as holding) |
| `UI_COLOR_IDLE` | `#1E9E3A` | Idle/ready (same as complete) |
| `UI_COLOR_AUTOTUNE` | `#E07A00` | PID autotune (same as heating) |
| `UI_COLOR_SURFACE_1` | `#F2F2F2` | Chart background, low-elevation surfaces |
| `UI_COLOR_SURFACE_2` | `#E6E6E6` | Control backgrounds (button matrix, etc.) |
| `UI_COLOR_BORDER`    | `#BFBFBF` | Borders, chart grid, focus outlines |
| `UI_COLOR_BUTTON_BG` | `#D9D9D9` | Button face |
| `UI_COLOR_ON_ACCENT` | `#000000` | Text on warm-accent surfaces (orange buttons, focused list item, status-pill default) |
| `UI_SPLASH_BG` | `#FFFFFF` | Splash bg |
| `UI_SPLASH_WORDMARK` | `#000000` | Splash wordmark |
| `UI_SPLASH_SUBTITLE` | `#444444` | Splash subtitle |
| `UI_SPLASH_STATUS` | `#666666` | Splash status text |
| `UI_SPLASH_VERSION` | `#999999` | Splash version label |

**Fonts:**
| Token | Font | Size | Usage |
|---|---|---|---|
| `UI_FONT_BIG` | Montserrat | 48px | Home temperature |
| `UI_FONT_MEDIUM` | Montserrat | 36px | Screen titles, chart temp |
| `UI_FONT_SMALL` | Montserrat | 24px | Labels, buttons, secondary info |

**Dimensions:**
| Token | Value |
|---|---|
| `UI_LCD_W` | 480px |
| `UI_LCD_H` | 320px |

### Screen Architecture

**Single adaptive dashboard.** `components/display/dashboard.c` owns one full-screen layout that swaps content based on `firing_progress_t::status` (idle vs. heating/holding/cooling/etc.). `dashboard_update()` is called every 500ms by `display_task`.

**Modal stack on top.** `components/display/modal.c` provides a frame stack parented to `lv_layer_top()`:

- `dashboard_modal_open(builder, ctx)` — push a frame; the builder populates widgets and they auto-join the modal's input group.
- `dashboard_modal_close()` — pop top; rebuilds parent if any.
- `dashboard_modal_close_all()` — used when an action commits (Start/Stop) to dismiss the workflow.

Existing modal builders: `modal_profile_picker.c`, `modal_action_menu.c`.

**No "new screens".** Either extend `dashboard.c` (if the surface is status-driven) or add a modal builder in `components/display/modal_*.c` and push it via `dashboard_modal_open()`. Builders run under the LVGL lock; pass long-lived (static/global) ctx, never stack data.

**Input model — joystick is a pure navigator.** The 5-way switch only ever moves focus or activates the focused widget; there is no "back via LEFT" gesture. Every dismissible modal must include a visible **Cancel** button — the user navigates to it like any other control and presses SELECT to close the frame.

- UP / LEFT → `lv_group_focus_prev()` on the active group
- DOWN / RIGHT → `lv_group_focus_next()` on the active group
- SELECT → activate the focused widget
- LEFT/RIGHT alias UP/DOWN so the user doesn't have to know which axis a layout uses (vertical lists, horizontal Start/Cancel pairs — both work).

Plumbing: the dashboard parks an invisible focusable trap (`s_select_trap`) in `g_input_group` so SELECT on the bare dashboard fires `LV_EVENT_CLICKED` and opens the contextual modal; modals swap the indev to `g_modal_group` while open. UP/DOWN and SELECT flow through LVGL's encoder driver; LEFT/RIGHT are polled outside LVGL via `display_consume_left_press()` / `display_consume_right_press()` and dispatched in `display_task::route_lr_focus()` to `dashboard_modal_nav_left/right()` (modal active) or `lv_group_focus_prev/next(g_input_group)` (dashboard).

### Icons & Images

- `LV_SYMBOL_RIGHT` (chevron "→") is used as a target-temperature prefix.
- Compile-time embedded bitmaps (static `lv_image_dsc_t` C arrays generated by `lv_img_conv` or the LVGL online converter) are permitted. The startup splash uses one — the flame icon at `components/display/assets/flame_icon.c`.
- **Runtime image decoders** (PNG/JPEG/BMP file decoders — `LV_USE_LODEPNG`, `LV_USE_BMP`, `LV_USE_TJPGD`, etc.) are **not** enabled and should not be turned on; each adds significant flash. Reach for an embedded bitmap only when LVGL primitives or symbols would be too lossy.

### Styling Conventions

- **Default styling comes from the theme** (`ui_theme.c`) and the shared widget helpers (`ui_widgets.h`: `ui_make_label`, `ui_make_button`, `ui_make_separator`). Use them. New label/button/separator call sites should not hand-roll `lv_label_create` + `lv_obj_set_style_*` boilerplate.
- **Tune defaults centrally.** Adjust the `lv_style_t`s in `ui_theme.c` to change all themed widgets at once. Add new shared styles there if a recurring composite emerges.
- **Inline `lv_obj_set_style_*()` is for runtime-dynamic state**, not visual defaults. Legitimate uses today: status-bar color updates driven by `firing_status_t`, the modal overlay's 90% opacity, splash's light palette overrides, and per-instance button bg colors used as a semantic flag (ERROR / HEATING / BUTTON_BG).
- New visual tokens belong as `UI_COLOR_*` / `UI_FONT_*` macros in `ui_common.h`; reference them from `ui_theme.c` styles, not hard-coded at call sites.
- Status colors map via `ui_status_color(firing_status_t)` helper.
- Status labels map via `ui_status_label(firing_status_t)` helper.
- All LVGL access (dashboard create/update, modal open/close) must happen with LVGL locked via `lv_lock()` / `lv_unlock()`; `lv_timer_handler()` locks internally when `LV_OS_FREERTOS` is enabled.

## Hardware

**KiCad PCB:** `hardware/kicad/` holds a full KiCad project (schematic + routed 4-layer board, 100 × 100 mm) for a single-board version of the controller — ESP32-S3-WROOM-1U-N16R2 module (U.FL external antenna, quad PSRAM), 2× MAX31856 thermocouple front-ends (**mirrored on purpose** — U3 rot 270, U5 rot 90, so their digital rows face each other and the whole SPI bus plus both chip selects live in one 6 mm channel between them; turning U5 to match U3 drags that bundle into the ADE7953's escape corridor and `I2C_SDA` cannot reach U7's SDA escape even when routed first, measured over three full re-routes. The mirror's real cost was channel 2's *filter* being left un-mirrored on the far side of the package from its own analog pins, which `design.py`'s `TC2_DY` now prevents), dual opto-isolated SSR drive, a ULN2003 aux output bank, an ADE7953 digital current-sense front-end, USB-C — targeting JLCPCB assembly. Both files are generated from `hardware/kicad/generator/design.py` (one connectivity/placement table + grid autorouter + geometry checker); see `hardware/kicad/README.md` for the regen workflow and `hardware/kicad/FAB-READINESS-REVIEW-REVB.md` for the current fab sign-off. Keep `design.py` in sync with `main/Kconfig.projbuild` pin defaults — `make pcb-check`'s `check_pinmap.py` step asserts they agree, and CI now enforces it: the `pcb-check` job in `build.yml` runs **`make pcb-check-portable`**, the seven checkers that read the board and schematic as text with nothing but the standard library (~3 s, unfiltered by path, because the drift most likely to happen is a firmware-only PR editing a Kconfig default and never touching `hardware/`). The other six are **not** in CI, since a KiCad 10 PPA install costs minutes and ~1 GB per run. **A script needs KiCad in three independent ways, and the portable list was wrong twice because each fix only considered the one that had just failed:** `import pcbnew` (`check_via_in_pad.py`, `check_silk.py`, `check_placement.py`), a **`kicad-cli` subprocess** (`check_netlist.py`, which exports the netlist in order to diff it, and `check_sch_uuids.py`, which re-saves the schematic to see what KiCad adds to it), and **KiCad's footprint libraries on disk** (`check_jlc_placement.py`, whose `find_footprint_dir()` needs the real `.kicad_mod` to fit LCSC's land pattern against). Every dev machine satisfies all three, so a green local run proves nothing about that list — check all three and let CI be the arbiter. So a green PR means the pin map, schematic bounds and layout, copper/DRC, drill clearances, canonical form and gerber zip agree — it does *not* mean the netlist round-trip, schematic uuid stability, CPL placement, silk, via-in-pad or courtyard overlap were checked. Run `make pcb-check` before a fab order. Fab outputs (`gerbers/`, `jlcpcb/gerbers.zip`, `jlcpcb/BOM.csv`, `jlcpcb/CPL.csv`, `pdf/`) are derived artifacts, and `make pcb` now regenerates them — it runs `pcb-build` (schematic + board), then `pcb-fab` (exports, in that order because zone fills must be current first), then `pcb-check`, then `pcb-render` — checks before the raytrace, so a board a checker has already rejected does not also cost you the slowest step. Nothing derived is left to remember. The **3D renders are content-addressed** rather than rebuilt, and this is the one place in the repo where a derived artifact cannot simply be regenerated on demand: `kicad-cli`'s raytracer is *not* reproducible — two runs over a byte-identical board differ in 5.6% of channel bytes (mean delta 89 of 255, sampling noise rather than rounding), so re-rendering unconditionally would drop a ~900 KB binary diff into every full build and teach you to discard `3d/` unread. `render-3d.sh` hashes the board, `3dmodels/` and its own render flags into `3d/.render-stamp` and skips on a match (~0.2 s against ~13 s); the stamp is committed so a clean clone skips too, which works only because the board build itself is reproducible. `make pcb-render FORCE=1` overrides it. The raytrace is 13 s, not the "minutes" this file and the README both used to claim — that figure predated dropping the two angled views. **`make pcb-build` costs ~340 s on the current placement (three routing passes over 92 nets and 141 parts; the 221 s this used to claim predates several placement revisions - re-measure with `make pcb-cosmetic-verify`, which reports both halves) — but that is the cost of a placement the router CAN close, and a placement change is exactly what stops it being one.** A design that strands a net spends all its time in rip-up: the failing revisions of the rev-B silk/placement work ran 10–40 minutes each, one of them nine minutes on a single net. Read the per-pass `N net(s) unrouted` lines instead of waiting in silence — a count that is not shrinking means stop and look at the placement — and note the run keeps the best pass, not the last. Never let the runtime talk you out of a full rebuild — when there is any doubt whether a change can move copper, run it. **Three traps in diagnosing a net that will not route, each of which cost a full rebuild here:** measure congestion against a FULLY ROUTED board (`git show HEAD:…kicad_pcb`) — measuring the failed build is circular, because the nets that failed are the ones missing, so the region they wanted reads as empty; CLIP each track to the window rather than testing whether an endpoint falls inside it — a corridor is traces passing straight *through*, and the endpoint test scored two of them zero (the escape south of U1 and the lane at the middle of the board actually carry 336 mm and 220 mm of track, and putting parts in either stranded nets); and when a net fails even after being PROMOTED to route first, ordering is not the problem — only fixed geometry exists at that point, so the lane is genuinely blocked. That last one is what `gen_pcb.ADE_I2C_SEEDS` + `MANUAL_VIAS` + `ADE_I2C_TERMS` exist for: the ADE7953's SDA/SCL escapes are one track wide, the committed board routes both but only as a fixed point, and six unrelated placement changes re-rolled it. A hand seed must also move the net's TERMINAL to its far end (as `USB_STUB_TERMS` does for J1) or the router reaches the fanout stub the short way and leaves the seed dangling. The fast path below is a convenience for the handful of changes that provably cannot, not a rule to route around. Silkscreen placement (`silk.py`, the `SILK` table, the nameplate's `TITLE_*`/`SILK_GRAPHICS`/`logo.py`, reference text metrics), 3D models (`MODEL_FIXUP`, files in `hardware/kicad/3dmodels/`) and the board title block get **`make pcb-cosmetic`** instead (`kicad_build.py --no-route`), which reuses the tracks, vias and filled zones already on disk and re-derives everything else with the same code: **~47 s for the board half against ~340 s, byte-identical to a full rebuild** — `make pcb-cosmetic-verify` proves it by building both and diffing, including over a board whose cosmetics were deliberately wrecked first. (Those were 421 s and 104 s until `silk.py`'s placer stopped linearly scanning all 492 pads and every other label for each of ~200,000 candidate placements; a `router.py`-style bucket grid plus hoisting `pcbnew.FromMM` out of the scan loops — 171 million SWIG calls to re-answer a constant — took the placer from 95.2 s to 3.8 s, byte-identically. It is now ~45% of `pcb-cosmetic` rather than ~96%, so the fast path's floor is KiCad process startup and DRC, not silk.) The **nameplate** (`BISQUE / KILN CONTROLLER / REV B / © 2026 Ben Severson` under the project's flame) is the one silk item that is placed rather than anchored: it goes wherever `gen_pcb.largest_empty_rect()` finds the most empty board — every part's keep-out rasterised on a 0.25 mm lattice, largest all-free rectangle by the histogram sweep — and then **scales to fit** it, with a floor at the board's own 0.8 mm silk-text-height rule (a 0.876 scale once put the copyright line at 0.789 mm and earned a `text_height` warning against a file whose whole claim is 0/0/0). Its rows are derived from `TITLE_ROWS` via the fact that KiCad's text bbox is 1.7× the glyph size, never typed as four y-coordinates. This replaced the hand-measured constant `TITLE_POCKET = (68, 63, 86, 95)`, and the search reproduces exactly that rectangle from the placement it was measured against — which is the point: the constant was not wrong, it was *un-remeasured*, and the nameplate is the one thing on the board with no reason to be anywhere in particular, so it is the thing that should give way when a part wants the space. The WS2812 cluster moved into that lane and the nameplate shrank to 75% and slid north with no edit. The flame is a board-level `gr_poly` and `generator/logo.py` carries it as **the SVG path string from `web_ui/public/favicon.svg`**, flattened at build time rather than traced into a point table, with `check_silk.py` failing on drift between the two. That graphic is also why `silk.py`'s obstacle set now includes board-level F.SilkS drawings and not just footprint ones: `collect_labels()` only ever collects text, so a board drawing is unmovable, and until it was filed as an obstacle it was also unavoided — the one graphic on the board that is not a part outline was the one thing a designator could legally print straight through, against a silk-on-silk budget of zero. **Printable is not the same as useful, and `silk.py` enforces both only since the two association rules were extended past reference designators.** `W_ON_PART` (a cost for sitting on an F.Fab body big enough to hide the label, which is *not* the courtyard) and the ring around a text's anchor used to apply, respectively, to references only and to nothing: a board text could be moved anywhere in a 14 mm ring at no charge for landing under a part. Both failures that produced were silent and DRC-clean — `CT A+/A-/B+/B-` slid exactly 14.00 mm (the last ring radius, which is the tell) to print 12.98 mm from the CT block and 8.38 mm from the thermocouple block, directly under *that* block's legend, and `WDT DEFEAT` slid exactly 10.00 mm into the middle of the buzzer; `RESET`, `BOOT` and three of J7's eight pin names printed under the parts they name, and `+`/`-`, the board's only per-terminal polarity marks, printed *inside* J2 because their anchors were 1.25 mm inside its body. Board texts now pay `W_ON_PART` too, and `silk.RING_MAX` caps the ring at 3.0 mm — above every drift the board legitimately uses (2.60 mm, a pin name stepping clear of a connector) and below the smallest that has ever been wrong. Exceeding it is not silently allowed and not silently forbidden either: the placer retries uncapped so the artefact still exists to diagnose, names what needed it, and `kicad_build.py` then fails the build, because an anchor aimed at occupied board is a human's call. Footprint texts are deliberately exempt from the body weight — LED1's pin-1 `1` and BZ1's `+` mark their part *by* sitting on it. The two checks split along what each side can see: `check_silk.py` owns the body test (budgeted **by name** in `ON_PART_OK`, so a new burial fails and a stale entry fails too), while the drift test lives in `kicad_build.py` because it needs each label's authored anchor and a saved `gr_text` is just a coordinate. `ON_PART_OK` is now **empty** and should stay that way: every entry it ever held was a placement problem dressed as a silk exemption, and each was fixed by moving a part — LED1 (a 5 × 5 mm WS2812 sitting in J7's pin-name band, taking out the labels for pins 5–7) to the middle of the board, SW1 alongside SW2, and U2's whole bulk-cap row 1.0–1.5 mm east because its SOT-223 leads left 0.93 mm of column for J2's 1.32 mm `+` glyph at exactly the `+` screw's y. **Every connector now carries one legend per terminal** (`gen_pcb.PIN_LEGENDS`, 50 of them, generated from the real pad geometry and the real drawn body), replacing the horizontal `SSR1  5V / OUT` / `CT A+/A-/B+/B-` lists that told a reader nothing about a *vertical* stack of screws. Each declares the axis carrying its meaning — `x` for a pin name over a pin, `y` for a mark beside a screw — and that is a hard constraint: `silk.py` refuses any candidate off it and `kicad_build.py` fails the build if one lands off it anyway. `W_LATERAL` remains the fallback for labels that don't declare one, and it is *backwards* for every vertically stacked terminal, which is why declaring beats guessing. Two ties had to be re-decided for it to hold: a reference designator may not take a seated legend's space, and a legend does not yield to a designator merely SEEDED in it (board texts are scored before references are ever placed, so `K-` twice fled J3's lower screw for `R15`'s unplaced library-default position). `RESET` and `BOOT` had been recorded on the claim that no room existed beside their buttons, and that was **wrong**: what the anchors had run into was the switch's own reference designator, and there was 4.20 mm west of SW1 (between H1's pad ring and SW1's pads) and 2.43 mm south of SW2. That distinction is worth knowing before adding an entry, and so is the asymmetry that produced it — **a board text cannot evict a seated reference.** The placer is greedy over a live index, so every designator is an obstacle from pass 1 and moves only if something makes *it* move; `RESET` got its spot only because `SW1` independently preferred another side, and `BOOT` stayed pinned to its button for two rebuilds because `SW2` did not. When a legend and a designator want the same gap, aim the legend somewhere the designator is not. `HIDE_REFS` in `gen_pcb.py` is the other side of that trade: H1-H4's designators are not printed at all (hidden, not deleted, so the netlist/BOM/CPL are untouched), because "which screw hole is this" is not a question anyone asks and four labels in the four most crowded corners is a cost with no reader. **The full path went 318 s to 158 s by the same lesson, and it is worth reading before optimising the router again**: profiling said A* node expansion was only 20%, while 71% was `_clear_of` calling the exact point-to-shape `dist()` on every obstacle within 3 mm — 381 million times. Caching a bounding box per `Shape`/`Seg` and rejecting on four float compares first, returning a cached flat list from `_near()` instead of a generator over nine dict lookups, and interleaving `via_ok()`'s three separate neighbourhood walks into one, took routing from 310 s to 144 s with a byte-identical board. `GRID` is *not* a knob left at 0.25 mm on faith — it was measured: 0.4 mm strands 14 nets and 0.3 mm strands 5, both on the ADE7953 and the MAX31856s, because the fanout and plane-via stubs snap their ends to `GRID` and a coarser one walks the escape off the pad centreline. 0.3 mm is also 3x *slower*, since an unroutable net exhausts the entire grid before saying so. See `hardware/kicad/README.md`. Anything touching placement, connectivity, footprint choice, net classes, `MANUAL_VIAS` or router parameters needs the full `make pcb-build`; `--no-route` compares the loaded board against `design.py` and refuses with the mismatches named rather than emitting a plausible-but-wrong board, but it cannot see a router-parameter change, so that judgement is yours — and the cheap side of it is the full build. Two properties of that fast path are load-bearing and documented in the README: it deliberately does **not** pass `--refill-zones` (KiCad's filler does not give the same answer refilling a full zone as filling an empty one), and it canonicalises the board on the way *in* (copper the GUI *added* carries a random uuid, and KiCad's writer breaks position ties on them, so a tie against derived uuids would land wherever chance put it). **Both files now leave the pipeline in KiCad's own item ORDER rather than `canonicalize.py`'s, and that reversal is the point of the whole arrangement.** KiCad sorts board items by uuid - footprints outright, tracks and vias as the tie-break after position - so with every uuid derived from item content that order is a function of the design, and a file stored in it makes opening the board in the GUI and saving a **no-op** instead of a **61,654-line reorder against 58,737 lines for 7 real edits**. `kicad_build.py`'s `resort_to_kicad_order()` and `gen_sch.py`'s closing `kicad-cli sch upgrade --force` are what put them there. **Three traps, each of which produced a confidently wrong verification here.** `kicad-cli pcb drc --save-board` does *not* sort - it writes items back in the order it read them, so it will preserve content order and report byte-identical output, which makes it worthless as a stand-in for a GUI save and was believed to be one for two full rebuilds; **`pcb upgrade --force` is the writer that sorts**, and is what any "would the GUI churn this?" test must use. One pass does not settle it either: KiCad's sort leaves ties in load order, so a file arriving in a foreign order needs more (this board takes **three**, and pass 1 vs pass 2 differ by 16,860 lines), which is why `resort_to_kicad_order()` loops to a fixpoint and fails loudly rather than assuming a count. And the board must still be **canonicalised after the fill**, not just before: a uuid derives from the item's serialised content and a zone's content is its `filled_polygon`, which the full path has not written yet at that point but the fast path inherits - deriving only before the fill gives the five pours one uuid on `pcb-build` and another on `pcb-cosmetic`, which is a `pcb-cosmetic-verify` failure on the only five items in the file whose bytes KiCad writes rather than pcbnew. Paid for once: the schematic went 20,060 -> 45,361 lines (KiCad's one-field-per-line form) and the board took one reordering commit with **zero** content change (the gerbers move with it - aperture D-codes get renumbered and `%TO.N%` net attributes regroup - but every coordinate line is identical, which is the thing to check if that diff ever looks alarming). Chasing that reorder also turned up an older bug, which is why `read_project()`/`restore_project()` now bracket the whole board-write sequence: **every tool here attaches the project to the board it saves and writes it back from the PCB side alone, dropping whatever it never loaded.** `schematic.top_level_sheets` was the known casualty and `sync_project()` puts it back - but a full build was also silently taking out the entire `erc` block and `sch_revision` (`build_board()` starts from a bare `pcbnew.BOARD()` with an empty project attached) and `net_inspector_panel` from the `.kicad_prl`. Nothing noticed because both repairs downstream only rebuild the blocks THEY own. Snapshot the bytes rather than enumerating what might go missing; the two syncs still run afterwards and are idempotent, so derived blocks stay derived. `check_canonical.py` still guards the uuid half, and `check_sch_uuids.py` the claim that kicad-cli invents none of its own. The **physical stack-up** is generated too: `gen_pcb.STACKUP` holds JLCPCB's `JLC04161H-7628` 1.6 mm press and `apply_stackup()` writes it into the saved file, because KiCad 10's SWIG bindings do not wrap `BOARD_STACKUP` at all — there is no pcbnew API for it, so it is patched into the text like `canonicalize.py`'s uuids. Do not set it in the GUI: `apply_stackup()` *replaces* whatever block it finds, so a hand-edited stack-up survives exactly until the next regen. It has to emit KiCad's own one-field-per-line formatting, since only the full path's `kicad-cli ... --save-board` rewrites the board and the fast path would otherwise differ by 66 lines of whitespace. This is not decoration: with no `(stackup ...)` the board declares no dielectric heights or ε_r, `.gbrjob` shipped `0.48 mm`/`FR4` placeholders to the fab, and impedance tools answer "layer F.Cu not found in stackup" and fall back to 0.1 mm widths. The board's one impedance target is USB 2.0 FS at 90 Ω differential, and the 0.3 mm/0.25 mm geometry reads 93.1 Ω *on this press only* — 2116/3313/1080 prepreg would read 75/70/61 Ω — so `check_pcb.py`'s check 5 pins the dielectric thicknesses and ε_r. **That 93.1 Ω is the fully-coupled figure and the routed pair is barely coupled at all**: measured against `bisque-controller.kicad_pcb`, **0.0%** of USB_DP's 39.08 mm runs within 0.30 mm of USB_DN and 93.0% runs beyond 0.75 mm, so the effective differential impedance sits essentially at the uncoupled limit of 2 × ~55 Ω single-ended. Nothing checks the routed *gap* — check 5 only guarantees the stack-up any such figure is computed against. This is tolerable rather than correct: the ESP32-S3 has Full-Speed USB only (12 Mbps), where the route is electrically short. Those numbers were 3.6% / 81.2% over 40.13 mm before U4 became an SRV05-4, so the swap that saved the feeder fee also gave up what little coupling there was — worth knowing before treating the drift as a router regression. Skew is not the problem and got *better* over the same change — measured pad-to-pad through the copper, J1→U1 is 32.333 mm on DP against 32.611 mm on DN, **0.278 mm (~1.9 ps)**, against 0.430 mm on the pre-swap board measured identically. **The topology changed with it, and that is what a re-measurement has to get right.** The USBLC6 was *in line* — the pair entered pins 1/3 and left 6/4 — so the path was two legs joined inside the package and had to be summed as `J1→U4` + `U4→U1`. The SRV05-4's four channels are independent, so U4 is now a **stub** and `J1→U1` is one continuous run; summing legs through U4 on this board reports 3.944 mm, which is not a skew, just a walk down a stub and back. Two further traps, both of which have produced published-looking wrong answers: never take the difference of each net's *total* copper (two separate AI board reviews reported 3.39 mm and 9.34 mm that way), and collapse every track endpoint that lands inside a pad onto one node before path-finding — two tracks meeting at different points on the same pad are connected in copper and disconnected in a naive endpoint graph, which reports DP as unreachable outright. Widening to 0.35 mm and routing the pair coupled end-to-end at a 0.25 mm gap is what would actually land on 90 Ω, if a future rev wants it. Schematic *geometry* is checked too, by two checkers, because every other checker validates connectivity — which is complete no matter where a symbol sits. `check_sch_bounds.py` fails if any item falls off the declared sheet (an A3 declaration once clipped 40% of the circuit out of the exported PDF with every gate green), and `check_sch_layout.py` fails on any symbol/symbol, text/symbol or text/text overlap (containment is not readability: the 20-line notes block once printed straight through the AUX OUTPUT BANK). It compares a symbol's body and its two visible fields as **separate** parts, not one unioned rectangle — unioning them made a field printed over its own part invisible by construction, which hid 44 of them. Schematic **uuids** get a third checker, and the reason is that an omission there is invisible until someone opens the file: `gen_sch.py` derives every uuid it writes from stable content (uuid5 over the per-instance part key, so `U10#1` and `U10#2` differ for the same pin number), but KiCad mints a random v4 for any item it loads *without* one and writes it back on the first save - which then re-rolls on every round-trip. A `SCH_SYMBOL` owns a `SCH_PIN` for every pin of the LIBRARY symbol, not just the ones its own unit draws, and that is exactly the omission that happened: emitting only the unit view's pins left U10's two `74LVC1G123` units 8 uuids short between them. `check_sch_uuids.py` runs `kicad-cli sch upgrade --force` on a copy and fails on any uuid minted or dropped, so the next multi-unit part fails loudly instead of quietly churning the schematic. Rails (`GND`, `+3V3`, `+5V`, `VBUS`) terminate in real `power:` port symbols rather than global labels; membership is derived from what KiCad's power library actually holds, never hand-listed, because an exact name match is also the guarantee the net name survives (`check_netlist.py` proves it). Adding a rail net is therefore free, but a rail *without* a library symbol silently stays a label. A block-local net with two pins is **fused**: the parts become one cell the packer places whole, joined by a real wire with a plain local label; nets of 3-8 pins fuse too, as one spine wire plus junction taps, when they have a hub-and-branches shape. `gen_sch.py` prints how many fused and names any it had to demote — fusing is planned to a fixpoint (a demoted net is withdrawn and the plan re-run, then offered one re-admission), so the reserved extents always match the drawn stubs; the fixpoint is also why a contested plan costs ~90 s of `make pcb-cosmetic` where an uncontested one costs seconds. Ports are never rotated — a ground triangle hangs below its wire and a rail bar sits above it, so `power_path()` bends the *wire* (one elbow, turning 1.5 pin pitches so the port lands between rows rather than on the next pin's wire) rather than turning the port sideways. Fusing added long wires to a sheet that had none, so `check_sch_layout.py` also fails on **wire/wire** collisions — specifically a T (an endpoint landing mid-wire, which looks soldered and is not) or a collinear overlap; a plain crossing is legal schematic practice and is allowed. The schematic is *laid out* programmatically — `gen_sch.py`'s `GROUPS` is a hand-maintained taxonomy mapping every ref to a functional block, and a two-level packer computes every coordinate from real symbol and text extents. Do not add coordinates by hand; add the ref to a `GROUPS` entry (an assertion fails on an ungrouped ref). Placement reserves each symbol's *label-inclusive* extent, which is what keeps two pin-label stubs from coinciding and silently merging two nets — a failure mode `check_netlist.py` has caught twice. The **CPL** is the one fab output whose correctness does not live in the board file at all: JLCPCB places *LCSC's* footprint for a part number, not ours, anchoring its origin at Mid X / Mid Y and turning its pin 1 by Rotation — so `gen_jlc.py`'s `JLC_PLACEMENT` carries a `(rotation, dx, dy)` per LCSC part, and `check_jlc_placement.py` (in `make pcb-check`) derives it by fitting LCSC's real land pattern (`generator/lcsc_pads.json`, refreshed from EasyEDA's component API by `lcsc_pads.py --refresh` when a part number changes) onto the KiCad footprint. Do not go back to a package-family regex table: the community one this replaced was wrong for six parts here — `^SOT-23 -> 180` also matches SOT-23-**6**, whose LCSC land runs across the pins (270), and `^QFN- -> 90` was 180 out for the ADE7953, which no preview can show you because a square QFN's pads overlap at every quarter turn. Families cannot express an origin difference at all, and U1 and J1 have one (0.477 mm and 1.571 mm — KiCad anchors the module and the USB-C receptacle on the body centre, LCSC on the pad pattern). Pin *numbering* is a library convention rather than a physical fact, so the fit needs `PIN_REMAP`: LCSC numbers an LED's anode 1 where KiCad numbers its cathode 1, and matching numbers alone would flip all three LEDs. **3D models are vendored** in `hardware/kicad/3dmodels/` and referenced through `${KIPRJMOD}`, never `${KICAD10_3DMODEL_DIR}`: KiCad 10 ships no model for four of this board's footprints (U1's `-WROOM-1U`, SW1/SW2's `TS-1187A`, J1's `TYPE-C-31-M-12`, U7's `QFN-28`), which is ordinary upstream coverage — 12 models for 75 `Connector_USB` footprints — and the failure mode is silence: `kicad-cli pcb render` exits 0, prints "Loading 3D models…", and omits the part, which reads as a footprint with no part fitted rather than as an error. ~15.9 MB on disk is ~2.8 MB of git objects (STEP is text, ~6:1) and it buys back a setup step that was manual, wiped by every KiCad upgrade, and silently skippable. The three LCSC models come from the same EasyEDA component API `lcsc_pads.py` already uses; when adding one, read the package's `SVGNODE` `c_rotation` — EasyEDA authors the STEP in the *unrotated* frame, so J1 needs `rotate=(0,0,180)` and presents, misleadingly, as an ~8.9 mm translation error until you do. C515890's `0,0,90` is deliberately not applied, since a square QFN is invariant under it.

**How to update:**
- A pin change belongs in `main/Kconfig.projbuild`, then
  `hardware/kicad/generator/design.py` and `docs/pin-assignments.md` — `make
  pcb-check`'s `check_pinmap.py` asserts the first two agree, and CI runs it.
- `kicad-cli sch export svg` produces a professional schematic if one is ever needed. Regenerating the board requires **KiCad 10+** (the generator uses the `pcbnew` Python module); KiCad 7/9 are no longer supported.
