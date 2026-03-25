# Bisque — Kiln Controller Firmware

## Project Overview

ESP32-S3 ceramic kiln controller. Firmware built with **ESP-IDF** (C), using **LVGL v9.2** for the embedded display UI. The display is a **3.5" ST7796S TFT LCD** (480x320 landscape, SPI, RGB565).

## Build & Flash

```bash
./build.sh          # Build firmware (wraps idf.py build)
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
- **Pins:** MOSI=11, SCLK=12, CS=9, DC=46, RST=3, BL=8 (active-high)
- **Input:** 3-button encoder (Up=GPIO4, Down=GPIO5, Select=GPIO6), active-low with pull-up, 50ms debounce
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
| `UI_COLOR_DOT_ACTIVE` | `#FFFFFF` | Active page dot |
| `UI_COLOR_DOT_INACTIVE` | `#444444` | Inactive page dot |

Inline colors (not yet in tokens): `#111111` (chart bg), `#222222` (btnmatrix bg), `#333333` (chart border/grid, profile focus), `#444444` (button bg).

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

4 screens, all created at startup, switched via long-press Select (800ms), animated with `LV_SCR_LOAD_ANIM_FADE_IN` (200ms):

| ID | Screen | Key Widgets |
|---|---|---|
| 0 | Home | Status bar (colored), big temp, target/seg/time labels |
| 1 | Chart | Temp label, 120-point line chart (0-1400°C range) |
| 2 | Profiles | Title, scrollable list of firing profiles |
| 3 | Firing | Temp+status, segment info, button matrix (Start/Pause/Resume/Stop) |

Each screen module (`ui_screen_*.c`) follows the pattern:
- `ui_screen_X_create()` — allocates widgets, returns root `lv_obj_t*`
- `ui_screen_X_update(...)` — refreshes from live data (called every 500ms)
- `ui_screen_X_set_page_dots(active, total)` — updates dot indicators

### Icons

Only `LV_SYMBOL_RIGHT` (chevron "→") is used, as a target temperature prefix. No custom icon fonts or image assets on the LCD UI.

### Styling Conventions

- All styles are **inline** (`lv_obj_set_style_*()` calls), no `lv_style_t` structs
- Every screen root: black bg, `LV_OPA_COVER`, non-scrollable
- Status colors map via `ui_status_color(firing_status_t)` helper
- Status labels map via `ui_status_label(firing_status_t)` helper
- Page dots: 4x 12px circles at Y=298, spaced 24px apart, centered

## Figma-to-Code Guidelines

When translating Figma designs for this project:

1. **Target: LVGL C code**, not web frameworks. Map Figma layers to `lv_obj_t` widgets.
2. **480x320 constraint** — designs must fit this resolution (landscape). Use absolute pixel positioning.
3. **3 font sizes only** — map Figma text to `UI_FONT_BIG` (48), `UI_FONT_MEDIUM` (36), or `UI_FONT_SMALL` (24).
4. **Dark theme** — pure black background, white text, semantic status colors.
5. **Color tokens** — use existing `UI_COLOR_*` macros. Add new ones to `ui_common.h` if needed.
6. **No images/SVGs** — the display has no image decoder enabled. Use LVGL primitives and symbols only.
7. **Input model** — 3-button encoder (up/down/select). Interactive widgets must be added to `g_input_group`.
8. **Memory budget** — 128KB LVGL heap. Keep widget counts minimal.
9. **New screens** — follow the `ui_screen_*.c/.h` module pattern. Add to `ui_screen_id_t` enum and `UI_SCREEN_COUNT`.
