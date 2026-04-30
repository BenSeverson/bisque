# Bisque — Kiln Controller Firmware

## Project Overview

ESP32-S3 ceramic kiln controller. Firmware built with **ESP-IDF** (C), using **LVGL v9.5.0** for the embedded display UI. The display is a **3.5" ST7796S TFT LCD** (480x320 landscape, SPI, RGB565).

## Build & Flash

```bash
./build.sh          # Build web UI (npm ci + vite), gzip into spiffs_data/www/, then idf.py build
idf.py build        # Firmware-only rebuild (skips web UI)
idf.py flash monitor  # Flash and monitor
```

Build system: **CMake** via ESP-IDF's `idf.py`. Each `components/` subdirectory is an ESP-IDF component with its own `CMakeLists.txt`.

## Code Style

After editing any firmware C/H files under `main/` or `components/`, run `clang-format -i` on the changed files (or `./scripts/format.sh` to format all firmware + web sources). The CI format check uses the repo's `.clang-format`; unformatted code will fail the `clang-format` job.

## Project Structure

```
components/
  app_config/       # Pin definitions, hardware constants
  display/          # LVGL UI — all screens, init, task loop
  firing_engine/    # Firing profile execution, PID integration
  pid_control/      # PID temperature controller
  thermocouple/     # MAX31855 SPI thermocouple driver
  safety/           # Safety watchdog, over-temp protection
  history/          # Firing history storage (NVS)
  cone_table/       # Ceramic cone temperature lookup
  web_server/       # HTTP API server
  wifi_manager/     # Wi-Fi provisioning
main/               # Entry point, task creation
web_ui/             # Frontend web dashboard (separate from LVGL UI)
spiffs_data/        # SPIFFS filesystem image for web assets
partition_table/    # ESP32 partition layout
```

## Display / UI System

### Hardware

- **Panel:** ST7796S, 480x320px (landscape), 16-bit RGB565, BGR byte order
- **Interface:** SPI @ 40 MHz (SPI2_HOST)
- **Pins:** MOSI=11, SCLK=12, CS=8, DC=9, RST=46, BL=3 (active-high)
- **Input:** 5-way nav switch (Up=GPIO4, Down=GPIO5, Left=GPIO6, Right=GPIO2, Center/Select=GPIO1), active-low with pull-up, 50ms debounce. Source of truth: `components/app_config/include/app_config.h` (`APP_PIN_BTN_*`).
- **Rendering:** Partial refresh, double-buffered DMA (40 rows), ~30 FPS

### LVGL Configuration

- LVGL v9.5.0, `LV_OS_FREERTOS` (LVGL lock API)
- Color depth: 16-bit, `LV_COLOR_16_SWAP=y`
- Memory pool: 128KB
- Fonts enabled: Montserrat 24, 36, 48 (default: 24)
- Widgets in use: label, chart, list, buttonmatrix, obj (containers/dots)
- Layout: absolute positioning via `lv_obj_set_pos()`/`lv_obj_align()` (flex/grid compiled in but unused)
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
- `dashboard_modal_use_horizontal_nav()` — call from inside a builder to make Left/Right move focus between buttons instead of closing the frame. Resets per-build.

Existing modal builders: `modal_profile_picker.c`, `modal_action_menu.c`.

**No "new screens".** Either extend `dashboard.c` (if the surface is status-driven) or add a modal builder in `components/display/modal_*.c` and push it via `dashboard_modal_open()`. Builders run under the LVGL lock; pass long-lived (static/global) ctx, never stack data.

**Input routing:** the dashboard parks an invisible focusable trap (`s_select_trap`) in `g_input_group` so the encoder always has a focus target; modals swap the indev to their own group while open. Left/Right physical presses are routed via `display_consume_left_press()` / `display_consume_right_press()` and dispatched to `dashboard_modal_nav_left/right()` when a modal is active.

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

**How to update:**
- Ask Claude Code: "update the perfboard layout diagram" or "update the wiring diagram"
- Or edit the SVG directly in any SVG editor (Inkscape, Figma, browser dev tools)
- KiCad CLI v9.0.8 is installed (`kicad-cli sch export svg`) if a professional schematic is ever needed
