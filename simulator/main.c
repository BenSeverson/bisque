/**
 * Bisque LVGL SDL Simulator
 *
 * Renders the new single-dashboard kiln controller LCD UI in a desktop window.
 * Drives the same firmware sources (dashboard.c, modal.c, modal_*.c) so what
 * you see here matches what's on the panel.
 *
 * Interactive controls:
 *   Up / Down arrows     encoder rotation (UP/DOWN buttons on the kiln)
 *   Enter / Space        SELECT (open contextual modal, activate focused item)
 *   Left arrow           cancel current modal (no-op when no modal is open)
 *   Right arrow          reserved (matches firmware)
 *   S                    cycle through state presets (IDLE → HEATING → ...)
 *   Q / Esc / close      quit
 *
 * Screenshot mode (--screenshot):
 *   Dumps every state preset and every modal to docs/screenshots/lcd-*.bmp
 *   then exits.
 */
#include "lvgl.h"
#include "app_config.h"
#include "dashboard.h"
#include "modal.h"
#include "modal_profile_picker.h"
#include "modal_action_menu.h"
#include "thermocouple.h"
#include "firing_types.h"
#include "firing_engine.h"
#include "firing_history.h"
#include "mock_esp.h"

#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdbool.h>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

/* mock_esp.c defines these — main.c is what ties them to LVGL objects. */
extern lv_indev_t *g_indev_encoder;
extern lv_group_t *g_input_group;
extern lv_group_t *g_modal_group;

/* ── Custom encoder indev (reads SDL keyboard state) ─────────────────────── */

static int s_enc_diff = 0;
static bool s_select_pressed = false;

static void encoder_read_cb(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    data->enc_diff = (int16_t)s_enc_diff;
    s_enc_diff = 0;
    data->state = s_select_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

/* ── State presets ───────────────────────────────────────────────────────── */

typedef struct {
    const char *name;
    firing_status_t status;
    float current_temp;
    float target_temp;
    uint8_t segment;
    uint8_t total_segments;
    uint32_t elapsed_s;
    uint32_t remaining_s;
    bool with_history;
    bool tc_fault;
    firing_error_code_t error;
    const char *profile_id; /* "" for none */
} preset_t;

static const preset_t presets[] = {
    {"idle", FIRING_STATUS_IDLE, 24.0f, 0, 0, 0, 0, 0, false, false, FIRING_ERR_NONE, ""},
    {"idle-history", FIRING_STATUS_IDLE, 24.0f, 0, 0, 0, 0, 0, true, false, FIRING_ERR_NONE, ""},
    {"heating", FIRING_STATUS_HEATING, 1180.0f, 1222.0f, 1, 3, 19920, 8040, false, false, FIRING_ERR_NONE, "profile-1"},
    {"holding", FIRING_STATUS_HOLDING, 1218.0f, 1222.0f, 1, 3, 21300, 6660, false, false, FIRING_ERR_NONE, "profile-1"},
    {"cooling", FIRING_STATUS_COOLING, 850.0f, 500.0f, 2, 3, 25600, 2360, false, false, FIRING_ERR_NONE, "profile-1"},
    {"paused", FIRING_STATUS_PAUSED, 1180.0f, 1222.0f, 1, 3, 19920, 8040, false, false, FIRING_ERR_NONE, "profile-1"},
    {"complete", FIRING_STATUS_COMPLETE, 850.0f, 0, 2, 3, 28720, 0, false, false, FIRING_ERR_NONE, "profile-1"},
    {"error", FIRING_STATUS_ERROR, 850.0f, 1222.0f, 1, 3, 14400, 0, false, false, FIRING_ERR_TC_FAULT, "profile-1"},
    {"autotune", FIRING_STATUS_AUTOTUNE, 1100.0f, 1100.0f, 0, 0, 600, 0, false, false, FIRING_ERR_NONE, ""},
};
#define PRESET_COUNT (sizeof(presets) / sizeof(presets[0]))

static int s_current_preset = 0;

static void apply_preset(int idx)
{
    if (idx < 0 || idx >= (int)PRESET_COUNT) {
        return;
    }
    const preset_t *p = &presets[idx];

    thermocouple_reading_t tc = {
        .temperature_c = p->current_temp,
        .internal_temp_c = 24.0f,
        .fault = (uint8_t)(p->tc_fault ? TC_FAULT_OPEN_CIRCUIT : 0),
        .timestamp_us = 0,
    };
    mock_set_thermocouple(&tc);

    firing_progress_t prog = {0};
    prog.status = p->status;
    prog.current_temp = p->current_temp;
    prog.target_temp = p->target_temp;
    prog.current_segment = p->segment;
    prog.total_segments = p->total_segments;
    prog.elapsed_time = p->elapsed_s;
    prog.estimated_remaining = p->remaining_s;
    prog.is_active = (p->status == FIRING_STATUS_HEATING || p->status == FIRING_STATUS_HOLDING ||
                     p->status == FIRING_STATUS_COOLING || p->status == FIRING_STATUS_PAUSED ||
                     p->status == FIRING_STATUS_AUTOTUNE);
    if (p->profile_id) {
        strncpy(prog.profile_id, p->profile_id, FIRING_ID_LEN - 1);
    }
    mock_set_progress(&prog);

    mock_set_error_code(p->error);

    if (p->with_history) {
        history_record_t r = {0};
        r.id = 1;
        r.start_time = 0;
        strncpy(r.profile_name, "Glaze Cone 6", HISTORY_PROFILE_NAME_LEN - 1);
        strncpy(r.profile_id, "profile-1", sizeof(r.profile_id) - 1);
        r.peak_temp_c = 1218.0f;
        r.duration_s = 28720;
        r.outcome = HISTORY_OUTCOME_COMPLETE;
        r.error_code = 0;
        mock_set_last_firing(&r);
    } else {
        mock_set_last_firing(NULL);
    }

    s_current_preset = idx;
    printf("Preset: %s\n", p->name);
}

/* ── Frame pump ──────────────────────────────────────────────────────────── */

static void pump_frames(int n)
{
    thermocouple_reading_t tc;
    firing_progress_t prog;
    for (int i = 0; i < n; i++) {
        thermocouple_get_latest(&tc);
        firing_engine_get_progress(&prog);
        dashboard_update(&tc, &prog);
        lv_timer_handler();
        SDL_Delay(16);
    }
}

static void encoder_press(void)
{
    s_select_pressed = true;
    pump_frames(3);
    s_select_pressed = false;
    pump_frames(3);
}

static void encoder_step(int diff)
{
    s_enc_diff += diff;
    pump_frames(3);
}

/* ── Screenshot save ─────────────────────────────────────────────────────── */

static bool save_screenshot(lv_display_t *disp, const char *path)
{
    void *renderer = lv_sdl_window_get_renderer(disp);
    if (!renderer) {
        return false;
    }
    /* Two refresh passes so the current frame is in the back buffer that
     * SDL_RenderReadPixels samples from. */
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(disp);
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(disp);

    int w = APP_LCD_H_RES;
    int h = APP_LCD_V_RES;
    int stride = w * 4;
    unsigned char *pixels = (unsigned char *)malloc((size_t)stride * (size_t)h);
    if (!pixels) {
        return false;
    }
    /* SDL_PIXELFORMAT_RGBA32 is byte-order R,G,B,A regardless of endianness — what stb_image_write expects. */
    if (SDL_RenderReadPixels(renderer, NULL, SDL_PIXELFORMAT_RGBA32, pixels, stride) != 0) {
        free(pixels);
        return false;
    }
    int rc = stbi_write_png(path, w, h, 4, pixels, stride);
    free(pixels);
    return rc != 0;
}

static void shoot(lv_display_t *disp, const char *name)
{
    char path[256];
    snprintf(path, sizeof(path), "docs/screenshots/lcd-%s.png", name);
    if (save_screenshot(disp, path)) {
        printf("Saved %s\n", path);
    } else {
        fprintf(stderr, "Failed to save %s: %s\n", path, SDL_GetError());
    }
}

/* ── Init ────────────────────────────────────────────────────────────────── */

static lv_display_t *init_lvgl_sdl(void)
{
    lv_init();
    lv_display_t *disp = lv_sdl_window_create(APP_LCD_H_RES, APP_LCD_V_RES);
    lv_sdl_window_set_title(disp, "Bisque Kiln Controller (LCD preview)");

    /* Mirror display_init.c: two LVGL groups, encoder indev points at the base group. */
    g_input_group = lv_group_create();
    g_modal_group = lv_group_create();
    lv_group_set_default(g_input_group);

    g_indev_encoder = lv_indev_create();
    lv_indev_set_type(g_indev_encoder, LV_INDEV_TYPE_ENCODER);
    lv_indev_set_read_cb(g_indev_encoder, encoder_read_cb);
    lv_indev_set_group(g_indev_encoder, g_input_group);

    return disp;
}

/* ── Modes ───────────────────────────────────────────────────────────────── */

static int run_screenshot_mode(lv_display_t *disp)
{
    /* Capture every state preset. */
    for (int i = 0; i < (int)PRESET_COUNT; i++) {
        apply_preset(i);
        pump_frames(8);
        shoot(disp, presets[i].name);
    }

    /* Modal: profile picker (from IDLE). */
    apply_preset(0);
    pump_frames(4);
    modal_profile_picker_open();
    pump_frames(4);
    shoot(disp, "modal-picker");

    /* Push start-confirm by pressing SELECT on the focused profile. */
    encoder_press();
    pump_frames(2);
    shoot(disp, "modal-start-confirm");
    dashboard_modal_close_all();
    pump_frames(2);

    /* Modal: action menu (from HEATING). */
    apply_preset(2);
    pump_frames(4);
    modal_action_menu_open(FIRING_STATUS_HEATING);
    pump_frames(4);
    shoot(disp, "modal-actions");

    /* Step focus down twice (Pause → Skip Segment → Stop), then SELECT to push stop-confirm. */
    encoder_step(2);
    encoder_press();
    pump_frames(2);
    shoot(disp, "modal-stop-confirm");
    dashboard_modal_close_all();
    pump_frames(2);

    return 0;
}

static int run_interactive(lv_display_t *disp)
{
    (void)disp;
    printf("Bisque LCD Simulator (new dashboard)\n");
    printf("  Up / Down: encoder navigate (in modals)\n");
    printf("  Enter / Space: SELECT (open contextual modal / activate)\n");
    printf("  Left: cancel current modal\n");
    printf("  Right: reserved\n");
    printf("  S: cycle through state presets\n");
    printf("  Q / Esc: quit\n");

    apply_preset(0);

    bool running = true;
    while (running) {
        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_QUIT) {
                running = false;
            } else if (event.type == SDL_KEYDOWN) {
                switch (event.key.keysym.sym) {
                case SDLK_q:
                case SDLK_ESCAPE:
                    running = false;
                    break;
                case SDLK_UP:
                    s_enc_diff--;
                    break;
                case SDLK_DOWN:
                    s_enc_diff++;
                    break;
                case SDLK_RETURN:
                case SDLK_SPACE:
                    s_select_pressed = true;
                    break;
                case SDLK_LEFT:
                    if (dashboard_modal_active()) {
                        dashboard_modal_close();
                    }
                    break;
                case SDLK_RIGHT:
                    /* reserved (matches firmware) */
                    break;
                case SDLK_s:
                    apply_preset((s_current_preset + 1) % (int)PRESET_COUNT);
                    break;
                default:
                    break;
                }
            } else if (event.type == SDL_KEYUP) {
                if (event.key.keysym.sym == SDLK_RETURN || event.key.keysym.sym == SDLK_SPACE) {
                    s_select_pressed = false;
                }
            }
        }

        thermocouple_reading_t tc;
        firing_progress_t prog;
        thermocouple_get_latest(&tc);
        firing_engine_get_progress(&prog);
        dashboard_update(&tc, &prog);
        lv_timer_handler();

        SDL_Delay(16); /* ~60 FPS */
    }

    return 0;
}

/* ── main ────────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    bool screenshot_mode = false;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--screenshot") == 0) {
            screenshot_mode = true;
        }
    }

    lv_display_t *disp = init_lvgl_sdl();

    /* Build the dashboard the same way the firmware does. */
    dashboard_create();

    int rc;
    if (screenshot_mode) {
        rc = run_screenshot_mode(disp);
    } else {
        rc = run_interactive(disp);
    }

    lv_sdl_quit();
    return rc;
}
