/**
 * LVGL configuration for the desktop SDL simulator.
 * Mirrors the ESP-IDF sdkconfig.defaults settings.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

/* Color depth: 16-bit RGB565 (matches hardware) */
#define LV_COLOR_DEPTH 16

/* Memory: generous for desktop */
#define LV_MEM_SIZE (256 * 1024)

/* OS: use pthread for tick/mutex */
#define LV_USE_OS LV_OS_PTHREAD

/* SDL display driver */
#define LV_USE_SDL 1
#define LV_SDL_RENDER_MODE LV_DISPLAY_RENDER_MODE_DIRECT
#define LV_SDL_BUF_COUNT 2
#define LV_SDL_ACCELERATED 1
#define LV_SDL_FULLSCREEN 0
#define LV_SDL_DIRECT_EXIT 1
#define LV_SDL_MOUSEWHEEL_MODE LV_SDL_MOUSEWHEEL_MODE_ENCODER
#define LV_SDL_INCLUDE_PATH <SDL2/SDL.h>

/* Fonts: same as firmware */
#define LV_FONT_MONTSERRAT_24 1
#define LV_FONT_MONTSERRAT_36 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT &lv_font_montserrat_24

/* Widgets: only what the UI uses */
#define LV_USE_LABEL 1
#define LV_USE_CHART 1
#define LV_USE_LIST 1
#define LV_USE_BUTTONMATRIX 1
#define LV_USE_BAR 1
#define LV_USE_BUTTON 1
#define LV_USE_IMAGE 1
#define LV_USE_SLIDER 0
#define LV_USE_SWITCH 0
#define LV_USE_ROLLER 0
#define LV_USE_CANVAS 0
#define LV_USE_TABLE 0
#define LV_USE_CALENDAR 0
#define LV_USE_KEYBOARD 0
#define LV_USE_TEXTAREA 0
#define LV_USE_SPINBOX 0
#define LV_USE_SPAN 0
#define LV_USE_TABVIEW 0
#define LV_USE_TILEVIEW 0
#define LV_USE_WIN 0
#define LV_USE_LED 0
#define LV_BUILD_EXAMPLES 0

/* Layout */
#define LV_USE_FLEX 1
#define LV_USE_GRID 1

/* No file system or image decoders needed */
#define LV_USE_FS_STDIO 0
#define LV_USE_FS_POSIX 0
#define LV_USE_PNG 0
#define LV_USE_BMP 0
#define LV_USE_GIF 0
#define LV_USE_SJPG 0

/* Logging */
#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN

/* Stdlib */
#define LV_USE_STDLIB_MALLOC LV_STDLIB_BUILTIN
#define LV_USE_STDLIB_STRING LV_STDLIB_BUILTIN
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_BUILTIN

/* No GPU/draw unit beyond SW */
#define LV_USE_DRAW_SW 1

/* Observer (needed by LVGL internals) */
#define LV_USE_OBSERVER 1

#endif /* LV_CONF_H */
