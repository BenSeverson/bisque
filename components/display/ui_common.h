#pragma once

#include "lvgl.h"
#include "app_config.h"
#include "firing_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* --- Color Palette (LVGL colors) --- */
#define UI_COLOR_BG        lv_color_black()
#define UI_COLOR_TEXT      lv_color_white()
#define UI_COLOR_TEXT_DIM  lv_color_make(0x99, 0x99, 0x99)
#define UI_COLOR_HEATING   lv_color_make(0xFF, 0xA5, 0x00) /* orange */
#define UI_COLOR_HOLDING   lv_color_make(0xFF, 0xFF, 0x00) /* yellow */
#define UI_COLOR_COOLING   lv_color_make(0x00, 0x00, 0xFF) /* blue */
#define UI_COLOR_ERROR     lv_color_make(0xFF, 0x00, 0x00) /* red */
#define UI_COLOR_COMPLETE  lv_color_make(0x00, 0xFF, 0x00) /* green */
#define UI_COLOR_PAUSED    lv_color_make(0xFF, 0xFF, 0x00) /* yellow */
#define UI_COLOR_IDLE      lv_color_make(0x00, 0xCC, 0x00) /* green */
#define UI_COLOR_AUTOTUNE  lv_color_make(0xFF, 0xA5, 0x00) /* orange */
#define UI_COLOR_SURFACE_1 lv_color_make(0x11, 0x11, 0x11) /* chart bg */
#define UI_COLOR_SURFACE_2 lv_color_make(0x22, 0x22, 0x22) /* control bg */
#define UI_COLOR_BORDER    lv_color_make(0x33, 0x33, 0x33) /* borders, grid */
#define UI_COLOR_BUTTON_BG lv_color_make(0x44, 0x44, 0x44) /* button face */

/* --- Font Aliases --- */
#define UI_FONT_BIG    &lv_font_montserrat_48
#define UI_FONT_MEDIUM &lv_font_montserrat_36
#define UI_FONT_SMALL  &lv_font_montserrat_24

/* --- Display Dimensions --- */
#define UI_LCD_W APP_LCD_H_RES
#define UI_LCD_H APP_LCD_V_RES

/* --- Status mapping helpers --- */

static inline lv_color_t ui_status_color(firing_status_t status)
{
    switch (status) {
    case FIRING_STATUS_HEATING:
        return UI_COLOR_HEATING;
    case FIRING_STATUS_HOLDING:
        return UI_COLOR_HOLDING;
    case FIRING_STATUS_COOLING:
        return UI_COLOR_COOLING;
    case FIRING_STATUS_ERROR:
        return UI_COLOR_ERROR;
    case FIRING_STATUS_COMPLETE:
        return UI_COLOR_COMPLETE;
    case FIRING_STATUS_PAUSED:
        return UI_COLOR_PAUSED;
    case FIRING_STATUS_AUTOTUNE:
        return UI_COLOR_AUTOTUNE;
    default:
        return UI_COLOR_IDLE;
    }
}

static inline const char *ui_status_label(firing_status_t status)
{
    switch (status) {
    case FIRING_STATUS_IDLE:
        return "IDLE";
    case FIRING_STATUS_HEATING:
        return "HEATING";
    case FIRING_STATUS_HOLDING:
        return "HOLDING";
    case FIRING_STATUS_COOLING:
        return "COOLING";
    case FIRING_STATUS_COMPLETE:
        return "COMPLETE";
    case FIRING_STATUS_ERROR:
        return "ERROR";
    case FIRING_STATUS_PAUSED:
        return "PAUSED";
    case FIRING_STATUS_AUTOTUNE:
        return "AUTOTUNE";
    default:
        return "UNKNOWN";
    }
}

#ifdef __cplusplus
}
#endif
