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
chooses the destination at run time so no device name is pinned. Two gotchas
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
  thermocouple/     # MAX31855 SPI thermocouple driver
  safety/           # Safety watchdog, over-temp protection
  history/          # Firing history storage (NVS)
  cone_table/       # Ceramic cone temperature lookup
  web_server/       # HTTP API server
  wifi_manager/     # Wi-Fi provisioning
  ota/              # GitHub-backed OTA firmware updates
main/               # Entry point, task creation
web_ui/             # Frontend web dashboard (separate from LVGL UI)
ios/Bisque/         # SwiftUI companion app (see below)
simulator/          # Host LVGL/SDL2 build of the display UI
tests/host/         # Unity host unit tests + API fixture generator
hardware/kicad/     # Generated KiCad project for the single-board PCB
docs/               # Wiring/perfboard SVGs, screenshots
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
- **Input:** 5-way nav switch (Up=GPIO4, Down=GPIO5, Left=GPIO6, Right=GPIO2, Center/Select=GPIO1), active-low with pull-up, 50ms debounce. Source of truth: `components/app_config/include/app_config.h` (`APP_PIN_BTN_*`).
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

## Hardware Diagrams

Two SVG diagrams document the perfboard wiring layout:

| File | Shows |
|---|---|
| `docs/perfboard-layout.svg` | Top-down perfboard layout: ESP32 placement, header positions, wire routing |
| `docs/wiring-diagram.svg` | Wiring schematic: all electrical connections between ESP32 and peripherals |

**Generation method:** Hand-crafted SVG by Claude Code. Not produced by KiCad or any EDA tool.

**Source of truth for pin assignments:** `components/app_config/include/app_config.h` (`APP_PIN_*` defines). If pin assignments change in firmware, regenerate both diagrams.

**KiCad PCB:** `hardware/kicad/` holds a full KiCad project (schematic + routed 2-layer board) for a single-board version of the controller — ESP32-S3-WROOM-1 module, MAX31855, SSR driver, USB-C — targeting JLCPCB assembly. Both files are generated from `hardware/kicad/generator/design.py` (one connectivity/placement table + grid autorouter + geometry checker); see `hardware/kicad/README.md` for the regen workflow. Keep `design.py` in sync with `main/Kconfig.projbuild` pin defaults. Fab outputs (`gerbers/`, `jlcpcb/BOM.csv`, `jlcpcb/CPL.csv`) are derived artifacts — regenerate them whenever the board changes, or they silently go stale.

**How to update:**
- Ask Claude Code: "update the perfboard layout diagram" or "update the wiring diagram"
- Or edit the SVG directly in any SVG editor (Inkscape, Figma, browser dev tools)
- `kicad-cli sch export svg` produces a professional schematic if one is ever needed. Regenerating the board requires **KiCad 10+** (the generator uses the `pcbnew` Python module); KiCad 7/9 are no longer supported.
