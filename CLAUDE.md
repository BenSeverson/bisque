# Bisque — Kiln Controller Firmware

## Project Overview

ESP32-S3 ceramic kiln controller. Firmware built with **ESP-IDF** (C), using **LVGL v9.2** for the embedded display UI. The display is a **3.5" ST7796S TFT LCD** (480x320 landscape, SPI, RGB565).

## Build & Flash

```bash
./build.sh          # Build web UI (npm ci + vite), gzip into spiffs_data/www/, then idf.py build
idf.py build        # Firmware-only rebuild (skips web UI)
idf.py flash monitor  # Flash and monitor
```

Build system: **CMake** via ESP-IDF's `idf.py`. Each `components/` subdirectory is an ESP-IDF component with its own `CMakeLists.txt`.

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

- LVGL v9.2, `LV_OS_NONE` (manual FreeRTOS mutex)
- Color depth: 16-bit, `LV_COLOR_16_SWAP=y`
- Memory pool: 128KB
- Fonts enabled: Montserrat 24, 36, 48 (default: 24)
- Widgets in use: label, chart, list, buttonmatrix, obj (containers/dots)
- Layout: absolute positioning via `lv_obj_set_pos()`/`lv_obj_align()` (flex/grid compiled in but unused)
- Theme: default dark, overridden inline

### Design Tokens (defined in `components/display/ui_common.h`)

**Colors:**
| Token | Value | Usage |
|---|---|---|
| `UI_COLOR_BG` | `#000000` | Screen backgrounds |
| `UI_COLOR_TEXT` | `#FFFFFF` | Primary text |
| `UI_COLOR_TEXT_DIM` | `#999999` | Secondary/dimmed text |
| `UI_COLOR_HEATING` | `#FFA500` | Heating status, chart line |
| `UI_COLOR_HOLDING` | `#FFFF00` | Holding status |
| `UI_COLOR_COOLING` | `#0000FF` | Cooling status |
| `UI_COLOR_ERROR` | `#FF0000` | Error status |
| `UI_COLOR_COMPLETE` | `#00FF00` | Firing complete |
| `UI_COLOR_PAUSED` | `#FFFF00` | Paused (same as holding) |
| `UI_COLOR_IDLE` | `#00CC00` | Idle/ready |
| `UI_COLOR_AUTOTUNE` | `#FFA500` | PID autotune |
| `UI_COLOR_SURFACE_1` | `#111111` | Chart background, low-elevation surfaces |
| `UI_COLOR_SURFACE_2` | `#222222` | Control backgrounds (button matrix, etc.) |
| `UI_COLOR_BORDER`    | `#333333` | Borders, chart grid, focus outlines |
| `UI_COLOR_BUTTON_BG` | `#444444` | Button face |

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

**Input routing:** the dashboard parks an invisible focusable trap (`s_select_trap`) in `g_input_group` so the encoder always has a focus target; modals swap the indev to their own group while open. Left/Right physical presses are routed via `display_consume_left_press()` / `display_consume_right_press()` and dispatched to `dashboard_modal_nav_left/right()` when a modal is active.

### Icons

Only `LV_SYMBOL_RIGHT` (chevron "→") is used, as a target temperature prefix. No custom icon fonts or image assets on the LCD UI.

### Styling Conventions

- All styles are **inline** (`lv_obj_set_style_*()` calls), no `lv_style_t` structs
- Every screen root: black bg, `LV_OPA_COVER`, non-scrollable
- Status colors map via `ui_status_color(firing_status_t)` helper
- Status labels map via `ui_status_label(firing_status_t)` helper
- All LVGL access (dashboard create/update, modal open/close) must happen with `g_lvgl_mutex` held — `display_task` holds it while ticking LVGL.

## Figma-to-Code Guidelines

When translating Figma designs for this project:

1. **Target: LVGL C code**, not web frameworks. Map Figma layers to `lv_obj_t` widgets.
2. **480x320 constraint** — designs must fit this resolution (landscape). Use absolute pixel positioning.
3. **3 font sizes only** — map Figma text to `UI_FONT_BIG` (48), `UI_FONT_MEDIUM` (36), or `UI_FONT_SMALL` (24).
4. **Dark theme** — pure black background, white text, semantic status colors.
5. **Color tokens** — use existing `UI_COLOR_*` macros. Add new ones to `ui_common.h` if needed.
6. **No images/SVGs** — the display has no image decoder enabled. Use LVGL primitives and symbols only.
7. **Input model** — 5-way nav switch (up/down/left/right/center). Interactive widgets must be added to `g_input_group` (or to a modal's group when built inside a `modal_builder_fn`).
8. **Memory budget** — 128KB LVGL heap. Keep widget counts minimal.
9. **New surfaces** — there is no "new screen". Either extend `dashboard.c` (if status-driven) or add a modal builder in `components/display/modal_*.c` and push it via `dashboard_modal_open()`. Builders run under the LVGL mutex; pass long-lived (static/global) ctx, never stack data.

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
