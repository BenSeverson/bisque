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
 *   Dumps the boot splash, every state preset and every modal to
 *   docs/screenshots/lcd-*.png then exits.
 *
 * Diff mode (--diff):
 *   Renders the same scenes and compares them against those baselines.
 *
 * Verify mode (--verify):
 *   Drives dashboard_update() through multi-step firing sequences and asserts on the
 *   resulting LVGL state rather than on pixels, covering regressions a screenshot
 *   cannot see. Exits non-zero on failure. See "State verification" below.
 */
#include "lvgl.h"
#include "app_config.h"
#include "dashboard.h"
#include "modal.h"
#include "modal_profile_picker.h"
#include "modal_action_menu.h"
#include "splash.h"
#include "ui_common.h"
#include "thermocouple.h"
#include "firing_types.h"
#include "firing_engine.h"
#include "firing_history.h"
#include "mock_esp.h"

#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdbool.h>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

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
    vent_state_t vent;
    lid_state_t lid;
} preset_t;

/* NOTE: for_each_scene() and the interactive keys address several of these by
 * index (2 = heating, 5 = paused). Append new presets; don't insert. */
static const preset_t presets[] = {
    {"idle", FIRING_STATUS_IDLE, 24.0f, 0, 0, 0, 0, 0, false, false, FIRING_ERR_NONE, "", VENT_STATE_NOT_FITTED,
     LID_STATE_NOT_FITTED},
    {"idle-history", FIRING_STATUS_IDLE, 24.0f, 0, 0, 0, 0, 0, true, false, FIRING_ERR_NONE, "", VENT_STATE_NOT_FITTED,
     LID_STATE_NOT_FITTED},
    {"heating", FIRING_STATUS_HEATING, 1180.0f, 1222.0f, 1, 3, 19920, 8040, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    {"holding", FIRING_STATUS_HOLDING, 1218.0f, 1222.0f, 1, 3, 21300, 6660, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    {"cooling", FIRING_STATUS_COOLING, 850.0f, 500.0f, 2, 3, 25600, 2360, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    {"paused", FIRING_STATUS_PAUSED, 1180.0f, 1222.0f, 1, 3, 19920, 8040, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    {"complete", FIRING_STATUS_COMPLETE, 850.0f, 0, 2, 3, 28720, 0, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    {"error", FIRING_STATUS_ERROR, 850.0f, 1222.0f, 1, 3, 14400, 0, false, false, FIRING_ERR_TC_FAULT, "profile-1",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    {"autotune", FIRING_STATUS_AUTOTUNE, 1100.0f, 1100.0f, 0, 0, 600, 0, false, false, FIRING_ERR_NONE, "",
     VENT_STATE_NOT_FITTED, LID_STATE_NOT_FITTED},
    /* Early in a bisque ramp on a kiln that has a downdraft vent fitted: below
       700°C the relay is energized, which is the only state that puts the VENT
       marker on the status bar (#184). Every preset above is a vent-less kiln —
       the firmware default — so none of them would ever show it. */
    {"vent", FIRING_STATUS_HEATING, 240.0f, 1222.0f, 0, 3, 5400, 22560, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_ON, LID_STATE_NOT_FITTED},
    /* A kiln whose lid was opened mid-firing in pause mode: the engine holds the
       program and the LID marker joins the bar. Deliberately also has the vent
       fitted and running, so the scene proves the two markers coexist without
       overlapping rather than only that each renders alone (#83). */
    {"lid-open", FIRING_STATUS_PAUSED, 240.0f, 1222.0f, 0, 3, 5400, 22560, false, false, FIRING_ERR_NONE, "profile-1",
     VENT_STATE_ON, LID_STATE_OPEN},
};
#define PRESET_COUNT (sizeof(presets) / sizeof(presets[0]))

static int s_current_preset = 0;

/* Vent state the next dashboard_update() will be driven with, standing in for
 * safety_get_vent_state() on device. */
static vent_state_t s_vent = VENT_STATE_NOT_FITTED;

/* Lid state for the next dashboard_update(), standing in for
 * safety_get_lid_state() on device. */
static lid_state_t s_lid = LID_STATE_NOT_FITTED;

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
    s_vent = p->vent;
    s_lid = p->lid;

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
        dashboard_update(&tc, &prog, s_vent, s_lid);
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

/* ── Render / save / diff ────────────────────────────────────────────────── */

/* Offscreen capture target, created on first use and owned by SDL_Quit(). */
static SDL_Texture *s_capture_target = NULL;

/* Allocate-and-fill a pixel buffer holding the frame LVGL renders right now.
 * Caller owns the returned buffer; returns NULL on failure.
 *
 * The capture must NOT come from the window's back buffer. LVGL's SDL driver
 * ends every flush with SDL_RenderPresent (lv_sdl_sw.c: window_update), and a
 * presented back buffer is invalidated by definition — SDL hands back whichever
 * swapchain image it recycled next. On macOS's Metal backend that is the frame
 * from two presents ago, so reading it returned a *previous scene* and every
 * diff was attributed to the wrong baseline (#196). Swapchain depth and
 * compositor timing decide how far back it lands, which is why the lag varied
 * between runs and could stick for several in a row.
 *
 * Binding our own render target sidesteps the swapchain entirely: LVGL's
 * RenderCopy lands in a texture we own, present does not rotate it, and the
 * read back is deterministic on every platform. It also pins the capture to
 * APP_LCD_H_RES x APP_LCD_V_RES instead of the window's drawable size. */
static unsigned char *read_current_pixels(lv_display_t *disp)
{
    SDL_Renderer *renderer = (SDL_Renderer *)lv_sdl_window_get_renderer(disp);
    if (!renderer) {
        return NULL;
    }

    if (!s_capture_target) {
        s_capture_target = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_TARGET,
                                             APP_LCD_H_RES, APP_LCD_V_RES);
        if (!s_capture_target) {
            return NULL;
        }
    }
    if (SDL_SetRenderTarget(renderer, s_capture_target) != 0) {
        return NULL;
    }

    /* Invalidate both the active screen and lv_layer_top so any open modal
     * redraws too — without this, a fully-opaque modal stays clean and the
     * screen redraw paints over it. LV_SDL_RENDER_MODE is DIRECT with two
     * buffers, so a full invalidate is what makes the active framebuffer a
     * complete frame rather than a partial update. */
    lv_obj_invalidate(lv_screen_active());
    lv_obj_invalidate(lv_layer_top());
    lv_refr_now(disp);

    int stride = APP_LCD_H_RES * 4;
    unsigned char *pixels = (unsigned char *)malloc((size_t)stride * (size_t)APP_LCD_V_RES);
    if (!pixels) {
        SDL_SetRenderTarget(renderer, NULL);
        return NULL;
    }
    /* SDL_PIXELFORMAT_RGBA32 is byte-order R,G,B,A regardless of endianness — what stb_image_write expects. */
    int rc = SDL_RenderReadPixels(renderer, NULL, SDL_PIXELFORMAT_RGBA32, pixels, stride);
    SDL_SetRenderTarget(renderer, NULL);
    if (rc != 0) {
        free(pixels);
        return NULL;
    }
    return pixels;
}

/* Guard for #196: prove the capture path returns the frame that was just
 * rendered, before any scene is compared against a baseline.
 *
 * Two full-screen probe colours are drawn and captured in turn. A capture path
 * that hands back a previously presented frame returns probe 1's colour when
 * probe 2 was drawn, and fails here — with one line naming the harness — rather
 * than mis-reporting every scene as a UI regression. One colour would not be
 * enough: a stale buffer that happens to already hold the probe colour would
 * pass. */
static bool capture_self_test(lv_display_t *disp)
{
    static const struct {
        uint32_t rgb;
        const char *name;
    } probes[] = {
        {0xFF0000, "red"},
        {0x0000FF, "blue"},
    };
    /* RGB565 round-trips these exactly, but leave room for renderer dithering. */
    const int tolerance = 8;

    lv_obj_t *probe = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(probe);
    lv_obj_set_size(probe, APP_LCD_H_RES, APP_LCD_V_RES);
    lv_obj_set_pos(probe, 0, 0);
    lv_obj_set_style_bg_opa(probe, LV_OPA_COVER, 0);

    bool ok = true;
    for (size_t i = 0; i < sizeof(probes) / sizeof(probes[0]); i++) {
        lv_obj_set_style_bg_color(probe, lv_color_hex(probes[i].rgb), 0);
        pump_frames(2);

        unsigned char *px = read_current_pixels(disp);
        if (!px) {
            fprintf(stderr, "capture self-test: failed to read render (%s)\n", SDL_GetError());
            ok = false;
            break;
        }
        /* Centre pixel — away from any window chrome or edge filtering. */
        size_t centre = ((size_t)(APP_LCD_V_RES / 2) * (size_t)APP_LCD_H_RES + (size_t)(APP_LCD_H_RES / 2)) * 4u;
        int got[3] = {px[centre], px[centre + 1], px[centre + 2]};
        int want[3] = {(int)((probes[i].rgb >> 16) & 0xFF), (int)((probes[i].rgb >> 8) & 0xFF),
                       (int)(probes[i].rgb & 0xFF)};
        free(px);

        for (int c = 0; c < 3; c++) {
            int d = got[c] - want[c];
            if (d < 0) {
                d = -d;
            }
            if (d > tolerance) {
                fprintf(stderr,
                        "capture self-test: drew %s (%d,%d,%d) but captured (%d,%d,%d) — the capture "
                        "path is returning a stale frame (see issue #196). This is a simulator harness "
                        "failure, not a UI regression.\n",
                        probes[i].name, want[0], want[1], want[2], got[0], got[1], got[2]);
                ok = false;
                break;
            }
        }
        if (!ok) {
            break;
        }
    }

    lv_obj_delete(probe);
    pump_frames(2);
    return ok;
}

static bool save_screenshot(lv_display_t *disp, const char *path)
{
    unsigned char *pixels = read_current_pixels(disp);
    if (!pixels) {
        return false;
    }
    int rc = stbi_write_png(path, APP_LCD_H_RES, APP_LCD_V_RES, 4, pixels, APP_LCD_H_RES * 4);
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

/* Compute per-pixel max/mean abs difference between two RGBA buffers of the
 * same dimensions. */
typedef struct {
    int max_channel_diff;
    double mean_abs_diff;
    int differing_pixels;
} pixel_diff_t;

static void compute_diff(const unsigned char *a, const unsigned char *b, int w, int h, pixel_diff_t *out)
{
    long total_abs = 0;
    out->max_channel_diff = 0;
    out->differing_pixels = 0;
    int n = w * h;
    for (int i = 0; i < n; i++) {
        bool any = false;
        for (int c = 0; c < 4; c++) {
            int d = (int)a[i * 4 + c] - (int)b[i * 4 + c];
            if (d < 0) {
                d = -d;
            }
            if (d > out->max_channel_diff) {
                out->max_channel_diff = d;
            }
            total_abs += d;
            if (d > 0) {
                any = true;
            }
        }
        if (any) {
            out->differing_pixels++;
        }
    }
    out->mean_abs_diff = (double)total_abs / (double)(n * 4);
}

/* Tolerance for a "pass": small per-pixel deltas from PNG re-encoding or
 * minor AA differences are accepted; structural changes are not. Bumps in
 * these limits should be paired with a comment explaining why. */
#define DIFF_MAX_CHANNEL_DELTA 12
#define DIFF_MEAN_ABS_DELTA    0.6

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

/* Scene iteration is shared between --screenshot and --diff so the two modes
 * stay byte-perfectly aligned. `action` is called once per scene, after the
 * UI has settled, with a canonical short name (the basename used in
 * docs/screenshots/lcd-<name>.png). */
typedef void (*scene_action_fn)(lv_display_t *disp, const char *name, void *ctx);

static void for_each_scene(lv_display_t *disp, scene_action_fn action, void *ctx)
{
    /* Boot splash — overlays the dashboard, then is torn down. Let the
     * dashboard settle first, then pump 8 frames so the freshly-created
     * subtree fully draws. */
    pump_frames(4);
    splash_create();
    splash_set_status("Connecting Wi-Fi...");
    pump_frames(8);
    action(disp, "splash", ctx);
    splash_destroy();
    pump_frames(2);

    /* Every state preset. */
    for (int i = 0; i < (int)PRESET_COUNT; i++) {
        apply_preset(i);
        pump_frames(8);
        action(disp, presets[i].name, ctx);
    }

    /* Modal: profile picker (from IDLE). */
    apply_preset(0);
    pump_frames(4);
    modal_profile_picker_open();
    pump_frames(4);
    action(disp, "modal-picker", ctx);

    /* Push start-confirm by pressing SELECT on the focused profile. */
    encoder_press();
    pump_frames(2);
    action(disp, "modal-start-confirm", ctx);
    dashboard_modal_close_all();
    pump_frames(2);

    /* Modal: action menu (from HEATING). */
    apply_preset(2);
    pump_frames(4);
    modal_action_menu_open(FIRING_STATUS_HEATING);
    pump_frames(4);
    action(disp, "modal-actions", ctx);

    /* Step focus down twice (Pause → Skip Segment → Stop), then SELECT to push stop-confirm. */
    encoder_step(2);
    encoder_press();
    pump_frames(2);
    action(disp, "modal-stop-confirm", ctx);
    dashboard_modal_close_all();
    pump_frames(2);

    /* Modal: action menu (from PAUSED) — swaps the "Pause" item for "Resume". */
    apply_preset(5); /* paused */
    pump_frames(4);
    modal_action_menu_open(FIRING_STATUS_PAUSED);
    pump_frames(4);
    action(disp, "modal-actions-paused", ctx);
    dashboard_modal_close_all();
    pump_frames(2);

    /* Modal: action menu (from AUTOTUNE) — only "Stop Autotune" + Cancel. */
    apply_preset(8); /* autotune */
    pump_frames(4);
    modal_action_menu_open(FIRING_STATUS_AUTOTUNE);
    pump_frames(4);
    action(disp, "modal-actions-autotune", ctx);
    dashboard_modal_close_all();
    pump_frames(2);
}

static void scene_shoot(lv_display_t *disp, const char *name, void *ctx)
{
    (void)ctx;
    shoot(disp, name);
}

static int run_screenshot_mode(lv_display_t *disp)
{
    if (!capture_self_test(disp)) {
        return 1;
    }
    for_each_scene(disp, scene_shoot, NULL);
    return 0;
}

typedef struct {
    int total;
    int passed;
    int failed;
    int missing_baseline;
} diff_summary_t;

static void scene_diff(lv_display_t *disp, const char *name, void *ctx)
{
    diff_summary_t *s = (diff_summary_t *)ctx;
    s->total++;

    char baseline_path[256];
    snprintf(baseline_path, sizeof(baseline_path), "docs/screenshots/lcd-%s.png", name);

    /* Capture current render. */
    unsigned char *current = read_current_pixels(disp);
    if (!current) {
        fprintf(stderr, "[%s] failed to read current render\n", name);
        s->failed++;
        return;
    }

    /* Load baseline. */
    int bw, bh, bc;
    unsigned char *baseline = stbi_load(baseline_path, &bw, &bh, &bc, 4);
    if (!baseline) {
        printf("[%s] MISSING baseline at %s\n", name, baseline_path);
        s->missing_baseline++;
        free(current);
        return;
    }
    if (bw != APP_LCD_H_RES || bh != APP_LCD_V_RES) {
        fprintf(stderr, "[%s] baseline size %dx%d != expected %dx%d\n", name, bw, bh, APP_LCD_H_RES, APP_LCD_V_RES);
        stbi_image_free(baseline);
        free(current);
        s->failed++;
        return;
    }

    pixel_diff_t diff;
    compute_diff(current, baseline, APP_LCD_H_RES, APP_LCD_V_RES, &diff);

    bool ok = diff.max_channel_diff <= DIFF_MAX_CHANNEL_DELTA && diff.mean_abs_diff <= DIFF_MEAN_ABS_DELTA;
    if (ok) {
        printf("[%s] OK (max=%d mean=%.3f diff_px=%d)\n", name, diff.max_channel_diff, diff.mean_abs_diff,
               diff.differing_pixels);
        s->passed++;
    } else {
        printf("[%s] FAIL (max=%d mean=%.3f diff_px=%d) — tolerance max≤%d mean≤%.2f\n", name, diff.max_channel_diff,
               diff.mean_abs_diff, diff.differing_pixels, DIFF_MAX_CHANNEL_DELTA, DIFF_MEAN_ABS_DELTA);
        s->failed++;
        /* Save the actual render so CI can upload it as an artifact for
         * inspection. Goes into docs/screenshots/actual/ which is gitignored
         * so dev runs don't leak diagnostic PNGs into the repo. */
        char actual_path[256];
        snprintf(actual_path, sizeof(actual_path), "docs/screenshots/actual/lcd-%s.png", name);
        stbi_write_png(actual_path, APP_LCD_H_RES, APP_LCD_V_RES, 4, current, APP_LCD_H_RES * 4);
        printf("       actual render saved to %s\n", actual_path);
    }

    stbi_image_free(baseline);
    free(current);
}

static int run_diff_mode(lv_display_t *disp)
{
    /* Ensure the actual-render dir exists so scene_diff can dump failures
     * even when invoked from a fresh worktree. mkdir(2) on POSIX returns
     * EEXIST harmlessly. */
    (void)mkdir("docs/screenshots/actual", 0755);

    if (!capture_self_test(disp)) {
        return 1;
    }

    diff_summary_t s = {0};
    for_each_scene(disp, scene_diff, &s);
    printf("\n== Screenshot diff summary ==\n");
    printf("  total:    %d\n", s.total);
    printf("  passed:   %d\n", s.passed);
    printf("  failed:   %d\n", s.failed);
    printf("  missing:  %d\n", s.missing_baseline);
    printf("  tolerance: max channel diff ≤ %d, mean abs diff ≤ %.2f\n", DIFF_MAX_CHANNEL_DELTA, DIFF_MEAN_ABS_DELTA);
    return (s.failed > 0 || s.missing_baseline > 0) ? 1 : 0;
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
        dashboard_update(&tc, &prog, s_vent, s_lid);
        lv_timer_handler();

        SDL_Delay(16); /* ~60 FPS */
    }

    return 0;
}

/* ── State verification (--verify) ────────────────────────────────────────── */

/* Screenshot diffing cannot catch this class of regression, so these checks assert on
 * widget state instead of pixels:
 *
 *   - The chart's "actual" temperature series is drawn with 0x0 point markers
 *     (s_chart_indicator in ui_theme.c), so plotted points at non-adjacent indices are
 *     literally invisible in a capture. A wiped series and a populated one can render
 *     identically — which is why #119 survived a passing screenshot suite.
 *   - A stale peak temperature (#127) only manifests across two consecutive firings, a
 *     sequence no single scene can express.
 *
 * Each check drives dashboard_update() through the transition that broke, then reads the
 * resulting LVGL tree back. Failures are counted and returned so this gates CI.
 */

static int s_verify_failures = 0;

static void check(bool ok, const char *what, const char *detail)
{
    printf("  %s  %s%s%s\n", ok ? "PASS" : "FAIL", what, detail ? " — " : "", detail ? detail : "");
    if (!ok) {
        s_verify_failures++;
    }
}

/* Depth-first search for the first descendant of `parent` with the given class. */
static lv_obj_t *find_by_class(lv_obj_t *parent, const lv_obj_class_t *cls)
{
    uint32_t n = lv_obj_get_child_count(parent);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *c = lv_obj_get_child(parent, i);
        if (lv_obj_check_type(c, cls)) {
            return c;
        }
        lv_obj_t *found = find_by_class(c, cls);
        if (found) {
            return found;
        }
    }
    return NULL;
}

/* Text of the first descendant label starting with `prefix`, or NULL. */
static const char *find_label_prefixed(lv_obj_t *parent, const char *prefix)
{
    uint32_t n = lv_obj_get_child_count(parent);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *c = lv_obj_get_child(parent, i);
        if (lv_obj_check_type(c, &lv_label_class)) {
            const char *t = lv_label_get_text(c);
            if (t && strncmp(t, prefix, strlen(prefix)) == 0) {
                return t;
            }
        }
        const char *found = find_label_prefixed(c, prefix);
        if (found) {
            return found;
        }
    }
    return NULL;
}

/* True if any label under `parent` has exactly this text. The prefix search above is
 * unsuitable for the COMPLETE view's profile label: that view's title is "Firing complete",
 * which shares a prefix with the no-profile fallback "Firing" and is created first, so a
 * prefix search returns the title and would pass even if the profile label were stale or
 * missing entirely. */
static bool label_with_exact_text(lv_obj_t *parent, const char *text)
{
    uint32_t n = lv_obj_get_child_count(parent);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *c = lv_obj_get_child(parent, i);
        if (lv_obj_check_type(c, &lv_label_class)) {
            const char *t = lv_label_get_text(c);
            if (t && strcmp(t, text) == 0) {
                return true;
            }
        }
        if (label_with_exact_text(c, text)) {
            return true;
        }
    }
    return false;
}

/* The status bar's vent marker, or NULL if the dashboard never created one. */
static lv_obj_t *find_label_by_text(lv_obj_t *parent, const char *text)
{
    uint32_t n = lv_obj_get_child_count(parent);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *c = lv_obj_get_child(parent, i);
        if (lv_obj_check_type(c, &lv_label_class)) {
            const char *t = lv_label_get_text(c);
            if (t && strcmp(t, text) == 0) {
                return c;
            }
        }
        lv_obj_t *found = find_label_by_text(c, text);
        if (found) {
            return found;
        }
    }
    return NULL;
}

/* Is the vent marker actually on screen? The label is created once and toggled
 * with LV_OBJ_FLAG_HIDDEN rather than destroyed, so a text search alone finds it
 * in both states and would pass unconditionally. */
static bool vent_marker_visible(void)
{
    lv_obj_t *marker = find_label_by_text(lv_screen_active(), "VENT");
    return marker != NULL && !lv_obj_has_flag(marker, LV_OBJ_FLAG_HIDDEN);
}

static bool lid_marker_visible(void)
{
    lv_obj_t *marker = find_label_by_text(lv_screen_active(), "LID");
    return marker != NULL && !lv_obj_has_flag(marker, LV_OBJ_FLAG_HIDDEN);
}

/* Number of plotted points on the chart's "actual" series. dashboard.c adds the planned
 * series first so it draws underneath, so "actual" is the second series. Negative on
 * structural surprises so a broken assumption fails loudly instead of reading as zero. */
static int count_plotted_points(void)
{
    lv_obj_t *chart = find_by_class(lv_screen_active(), &lv_chart_class);
    if (!chart) {
        return -1;
    }
    lv_chart_series_t *planned = lv_chart_get_series_next(chart, NULL);
    lv_chart_series_t *actual = planned ? lv_chart_get_series_next(chart, planned) : NULL;
    if (!actual) {
        return -2;
    }
    int32_t *y = lv_chart_get_y_array(chart, actual);
    uint32_t points = lv_chart_get_point_count(chart);
    int plotted = 0;
    for (uint32_t i = 0; i < points; i++) {
        if (y[i] != LV_CHART_POINT_NONE) {
            plotted++;
        }
    }
    return plotted;
}

/* Push one engine state through dashboard_update, the way display_task does on device. */
static void drive(firing_status_t status, float temp, uint32_t elapsed, const char *profile_id)
{
    thermocouple_reading_t tc = {
        .temperature_c = temp,
        .internal_temp_c = 24.0f,
        .fault = 0,
        .timestamp_us = 0,
    };
    mock_set_thermocouple(&tc);

    firing_progress_t prog = {0};
    prog.status = status;
    prog.current_temp = temp;
    prog.target_temp = 1222.0f;
    prog.current_segment = 1;
    prog.total_segments = 3;
    prog.elapsed_time = elapsed;
    prog.estimated_remaining = 600;
    prog.is_active =
        (status != FIRING_STATUS_IDLE && status != FIRING_STATUS_COMPLETE && status != FIRING_STATUS_ERROR);
    strncpy(prog.profile_id, profile_id, FIRING_ID_LEN - 1);
    mock_set_progress(&prog);
    pump_frames(2);
}

/* The COMPLETE view's peak line, formatted the way build_view_complete does, so these
 * checks follow the configured temperature unit instead of hardcoding °F. */
static void check_complete_peak(float expected_peak_c, const char *what)
{
    char expected[32];
    snprintf(expected, sizeof(expected), "Peak %.0f%s", (double)ui_temp_value(expected_peak_c), ui_temp_suffix());
    const char *actual = find_label_prefixed(lv_screen_active(), "Peak ");
    char detail[96];
    snprintf(detail, sizeof(detail), "want \"%s\", got \"%s\"", expected, actual ? actual : "(no peak label)");
    check(actual != NULL && strcmp(actual, expected) == 0, what, detail);
}

/* #119 — ACTIVE -> PAUSED -> ACTIVE shares one layout, so the chart must keep its points. */
static void verify_chart_survives_pause(void)
{
    printf("[#119] chart history across pause/resume\n");

    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    for (uint32_t i = 0; i <= 40; i++) {
        drive(FIRING_STATUS_HEATING, 25.0f + 25.0f * (float)i, i * 600u, "profile-1");
    }
    int ramped = count_plotted_points();

    char detail[96];
    snprintf(detail, sizeof(detail), "%d points plotted while heating", ramped);
    check(ramped >= 30, "ramp plots a curve worth preserving", detail);

    drive(FIRING_STATUS_PAUSED, 1025.0f, 24600, "profile-1");
    int paused = count_plotted_points();
    snprintf(detail, sizeof(detail), "%d points before pause, %d after", ramped, paused);
    check(paused >= ramped, "PAUSE keeps the plotted curve", detail);

    drive(FIRING_STATUS_HEATING, 1030.0f, 24700, "profile-1");
    int resumed = count_plotted_points();
    snprintf(detail, sizeof(detail), "%d points before pause, %d after resume", ramped, resumed);
    check(resumed >= ramped, "RESUME keeps the plotted curve", detail);
}

/* #127 — re-firing the same profile straight off the Complete screen is a new firing, so
 * the peak must restart rather than carry over. */
static void verify_peak_resets_on_refire(void)
{
    printf("[#127] peak temperature when re-firing the same profile\n");

    /* Firing 1: peaks at 1180C. */
    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    drive(FIRING_STATUS_HEATING, 200.0f, 100, "profile-1");
    drive(FIRING_STATUS_HEATING, 1180.0f, 20000, "profile-1");
    drive(FIRING_STATUS_COMPLETE, 900.0f, 28000, "profile-1");
    check_complete_peak(1180.0f, "firing 1 reports its own peak");

    /* Firing 2: same profile, started from COMPLETE with no IDLE in between, stopped early
       at 300C. The engine keeps the same profile_id, and COMPLETE already counts as a
       profile-using view, so nothing about the *profile* changes here. */
    drive(FIRING_STATUS_HEATING, 120.0f, 60, "profile-1");
    drive(FIRING_STATUS_HEATING, 300.0f, 3000, "profile-1");
    drive(FIRING_STATUS_COMPLETE, 280.0f, 3200, "profile-1");
    check_complete_peak(300.0f, "firing 2 reports its own peak, not firing 1's");
}

/* A profile that cannot be loaded must not look like a fresh profile on every update — that
 * re-ran the peak reset every tick, pinning the reported peak to the current temperature. */
static void verify_peak_survives_unloadable_profile(void)
{
    printf("[#127] peak tracking when the active profile cannot be loaded\n");

    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    mock_set_profile_load_fail(true);
    drive(FIRING_STATUS_HEATING, 100.0f, 60, "deleted-profile");
    drive(FIRING_STATUS_HEATING, 1000.0f, 18000, "deleted-profile"); /* the real peak */
    drive(FIRING_STATUS_COOLING, 400.0f, 26000, "deleted-profile");  /* falls back down */
    drive(FIRING_STATUS_COMPLETE, 380.0f, 27000, "deleted-profile");
    check_complete_peak(1000.0f, "peak is the firing's max, not the last reading");
    mock_set_profile_load_fail(false);
}

/* #128 — deleting the active profile out from under a running firing must not make the
 * dashboard re-open NVS on every 500ms tick; each read runs inside the LVGL lock. */
static void verify_unloadable_profile_is_not_reread(void)
{
    printf("[#128] profile reads after the active profile is deleted\n");

    const uint32_t ticks = 40;
    char detail[96];

    /* (1) Profile deleted mid-firing. The cached copy stays valid, so the dashboard keeps
       showing profile-derived detail and never needs to touch NVS again. */
    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    drive(FIRING_STATUS_HEATING, 100.0f, 60, "profile-1");
    mock_set_profile_load_fail(true);
    mock_reset_profile_load_calls();
    for (uint32_t i = 0; i < ticks; i++) {
        drive(FIRING_STATUS_HEATING, 100.0f + (float)i * 20.0f, 120 + i * 500, "profile-1");
    }
    unsigned reads = mock_profile_load_calls();
    snprintf(detail, sizeof(detail), "%u reads over %u ticks", reads, (unsigned)ticks);
    check(reads == 0, "deleting the active profile mid-firing triggers no re-read", detail);

    /* (2) Firing whose profile is already gone when the view is entered: one attempt, then
       the failure is remembered rather than retried every tick. */
    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    mock_reset_profile_load_calls();
    drive(FIRING_STATUS_HEATING, 100.0f, 60, "deleted-profile");
    unsigned first = mock_profile_load_calls();
    for (uint32_t i = 0; i < ticks; i++) {
        drive(FIRING_STATUS_HEATING, 100.0f + (float)i * 20.0f, 120 + i * 500, "deleted-profile");
    }
    reads = mock_profile_load_calls();
    snprintf(detail, sizeof(detail), "%u read(s) on entry, %u total over %u more ticks", first, reads, (unsigned)ticks);
    check(first == 1 && reads == 1, "an unloadable profile is attempted once, not once per tick", detail);

    /* Graceful degradation: the firing is still shown, just without the profile name.
       Assert the fallback label exactly — and separately that the previous firing's name
       is gone, which is the part that actually distinguishes degrading from showing stale
       detail. Step (1) cached "Glaze Cone 6" (profile-1). */
    drive(FIRING_STATUS_COMPLETE, 380.0f, 27000, "deleted-profile");
    bool fallback = label_with_exact_text(lv_screen_active(), "Firing");
    bool stale = label_with_exact_text(lv_screen_active(), "Glaze Cone 6");
    snprintf(detail, sizeof(detail), "fallback \"Firing\" %s, stale name %s", fallback ? "present" : "MISSING",
             stale ? "STILL SHOWN" : "gone");
    check(fallback && !stale, "COMPLETE degrades to the fallback label, no stale profile name", detail);

    mock_set_profile_load_fail(false);
}

/* #184 — the vent marker is a status-bar widget that outlives every layout swap,
 * so "does it appear" is not the interesting question; "does it go away again"
 * is. Show/hide is also change-guarded, which is exactly the shape of bug that
 * leaves a stale marker on screen. A screenshot of any single scene would pass
 * either way. */
static void verify_vent_indicator_tracks_state(void)
{
    printf("[#184] downdraft vent indicator\n");

    /* A kiln with no vent GPIO — the firmware default — must never show it,
       whatever the firing is doing. */
    s_vent = VENT_STATE_NOT_FITTED;
    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    drive(FIRING_STATUS_HEATING, 240.0f, 5400, "profile-1");
    check(!vent_marker_visible(), "a kiln with no vent relay never shows the marker", NULL);

    /* Vent fitted and running through the early, smoky part of the ramp. */
    s_vent = VENT_STATE_ON;
    drive(FIRING_STATUS_HEATING, 300.0f, 6000, "profile-1");
    check(vent_marker_visible(), "an energized vent shows the marker", NULL);

    /* Past 700°C the firmware drops the relay. The marker has to follow — this
       is the one that a change-guard bug strands on screen for the rest of the
       firing. */
    s_vent = VENT_STATE_OFF;
    drive(FIRING_STATUS_HEATING, 900.0f, 14000, "profile-1");
    check(!vent_marker_visible(), "the marker clears when the vent shuts off", NULL);

    /* And it survives a layout swap: the status bar is not rebuilt with the
       content area, so a re-shown marker must still be there after ACTIVE →
       COMPLETE → ACTIVE. */
    s_vent = VENT_STATE_ON;
    drive(FIRING_STATUS_COMPLETE, 400.0f, 20000, "profile-1");
    drive(FIRING_STATUS_HEATING, 200.0f, 60, "profile-1");
    check(vent_marker_visible(), "the marker survives a layout rebuild", NULL);

    s_vent = VENT_STATE_NOT_FITTED;
}

/* #83 — same class of bug as the vent marker, and the same reason a screenshot
 * cannot catch it: the lid marker is change-guarded status-bar furniture, so
 * "does it clear again" is the question, not "does it appear". A stale LID on a
 * kiln whose lid is shut is worse than none at all — it is the marker an
 * operator would use to decide whether it is safe to walk away. */
static void verify_lid_indicator_tracks_state(void)
{
    printf("[#83] lid interlock indicator\n");

    /* A kiln with no lid GPIO — the firmware default — must never show it. */
    s_lid = LID_STATE_NOT_FITTED;
    drive(FIRING_STATUS_IDLE, 25.0f, 0, "");
    drive(FIRING_STATUS_HEATING, 600.0f, 5400, "profile-1");
    check(!lid_marker_visible(), "a kiln with no lid switch never shows the marker", NULL);

    /* Fitted and shut is also silent — there is nothing to announce. */
    s_lid = LID_STATE_CLOSED;
    drive(FIRING_STATUS_HEATING, 620.0f, 6000, "profile-1");
    check(!lid_marker_visible(), "a closed lid shows no marker", NULL);

    /* Opened mid-firing: in pause mode the engine holds the program, so the
       status goes PAUSED and the marker appears together. */
    s_lid = LID_STATE_OPEN;
    drive(FIRING_STATUS_PAUSED, 620.0f, 6100, "profile-1");
    check(lid_marker_visible(), "an open lid shows the marker", NULL);

    /* Closed again: the firing resumes and the marker must go with it. This is
       the one a change-guard bug strands on screen for the rest of the run. */
    s_lid = LID_STATE_CLOSED;
    drive(FIRING_STATUS_HEATING, 615.0f, 6200, "profile-1");
    check(!lid_marker_visible(), "the marker clears when the lid closes", NULL);

    /* And it survives a layout swap, like the vent marker: the status bar is not
       rebuilt with the content area. */
    s_lid = LID_STATE_OPEN;
    drive(FIRING_STATUS_COMPLETE, 400.0f, 20000, "profile-1");
    drive(FIRING_STATUS_PAUSED, 200.0f, 60, "profile-1");
    check(lid_marker_visible(), "the marker survives a layout rebuild", NULL);

    /* Both markers at once must both be present — they are anchored to each
       other, and an alignment mistake hides one behind the other. */
    s_vent = VENT_STATE_ON;
    drive(FIRING_STATUS_PAUSED, 240.0f, 5400, "profile-1");
    check(lid_marker_visible() && vent_marker_visible(), "lid and vent markers coexist", NULL);

    /* …and they must not land on the status text. The bar is 480px and the
       markers are anchored right-to-left off the segment label, so the widest
       case — the longest status word with both markers showing — is where they
       run into it. This is invisible to a pixel diff of any *other* scene and
       shows up as a status word with its last letter painted over, which is
       exactly how it first appeared: "PAUSED" rendered as "PAUSE" under the LID
       pill. Checked against every status that can be on screen with a segment
       label, not just the one the lid-open scene happens to use. */
    static const firing_status_t bar_statuses[] = {
        FIRING_STATUS_HEATING,
        FIRING_STATUS_HOLDING,
        FIRING_STATUS_COOLING,
        FIRING_STATUS_PAUSED,
    };
    for (size_t i = 0; i < sizeof(bar_statuses) / sizeof(bar_statuses[0]); i++) {
        drive(bar_statuses[i], 240.0f, 5400, "profile-1");
        lv_obj_t *lid = find_label_by_text(lv_screen_active(), "LID");
        lv_obj_t *status = find_label_by_text(lv_screen_active(), ui_status_label(bar_statuses[i]));
        int32_t status_right = status ? lv_obj_get_x(status) + lv_obj_get_width(status) : -1;
        int32_t lid_left = lid ? lv_obj_get_x(lid) : -1;
        char detail[128];
        snprintf(detail, sizeof(detail), "%s ends at x=%d, lid starts at x=%d", ui_status_label(bar_statuses[i]),
                 (int)status_right, (int)lid_left);
        check(status && lid && lid_left >= status_right, "markers clear the status text", detail);
    }

    s_lid = LID_STATE_NOT_FITTED;
    s_vent = VENT_STATE_NOT_FITTED;
}

static int run_verify(void)
{
    s_verify_failures = 0;
    verify_chart_survives_pause();
    verify_peak_resets_on_refire();
    verify_peak_survives_unloadable_profile();
    verify_unloadable_profile_is_not_reread();
    verify_vent_indicator_tracks_state();
    verify_lid_indicator_tracks_state();

    printf("\n== Dashboard state verification ==\n");
    printf("  failures: %d\n", s_verify_failures);
    return s_verify_failures == 0 ? 0 : 1;
}

/* ── main ────────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    enum { MODE_INTERACTIVE, MODE_SCREENSHOT, MODE_DIFF, MODE_VERIFY } mode = MODE_INTERACTIVE;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--screenshot") == 0) {
            mode = MODE_SCREENSHOT;
        } else if (strcmp(argv[i], "--diff") == 0) {
            mode = MODE_DIFF;
        } else if (strcmp(argv[i], "--verify") == 0) {
            mode = MODE_VERIFY;
        }
    }

    lv_display_t *disp = init_lvgl_sdl();

    /* Build the dashboard the same way the firmware does. */
    dashboard_create();

    int rc;
    switch (mode) {
    case MODE_SCREENSHOT:
        rc = run_screenshot_mode(disp);
        break;
    case MODE_DIFF:
        rc = run_diff_mode(disp);
        break;
    case MODE_VERIFY:
        rc = run_verify();
        break;
    case MODE_INTERACTIVE:
    default:
        rc = run_interactive(disp);
        break;
    }

    lv_sdl_quit();
    return rc;
}
