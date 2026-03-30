/**
 * Bisque LVGL SDL Simulator
 *
 * Renders the kiln controller LCD UI in a desktop window using SDL2.
 * Useful for UI development without hardware and for capturing screenshots.
 *
 * Usage:
 *   ./bisque_sim              # Interactive mode (keyboard: left/right to switch screens)
 *   ./bisque_sim --screenshot # Capture all 4 screens to docs/screenshots/ and exit
 */
#include "lvgl.h"
#include "app_config.h"
#include "ui_common.h"
#include "ui_screen_home.h"
#include "ui_screen_chart.h"
#include "ui_screen_profiles.h"
#include "ui_screen_firing.h"
#include "thermocouple.h"
#include "firing_types.h"
#include "firing_engine.h"

#include <SDL2/SDL.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* Screen array */
static lv_obj_t *screens[UI_SCREEN_COUNT];
static int current_screen = UI_SCREEN_HOME;

static void update_all_page_dots(void)
{
    ui_screen_home_set_page_dots(current_screen, UI_SCREEN_COUNT);
    ui_screen_chart_set_page_dots(current_screen, UI_SCREEN_COUNT);
    ui_screen_profiles_set_page_dots(current_screen, UI_SCREEN_COUNT);
    ui_screen_firing_set_page_dots(current_screen, UI_SCREEN_COUNT);
}

static void update_screens(void)
{
    thermocouple_reading_t tc;
    firing_progress_t prog;
    thermocouple_get_latest(&tc);
    firing_engine_get_progress(&prog);

    ui_screen_home_update(&tc, &prog);
    ui_screen_chart_update(&tc);
    ui_screen_firing_update(&tc, &prog);
}

static void switch_screen(int idx)
{
    if (idx < 0) idx = UI_SCREEN_COUNT - 1;
    if (idx >= UI_SCREEN_COUNT) idx = 0;
    current_screen = idx;
    update_all_page_dots();
    lv_screen_load_anim(screens[current_screen], LV_SCR_LOAD_ANIM_FADE_IN, 200, 0, false);
}

static bool save_screenshot(lv_display_t *disp, const char *path)
{
    void *renderer = lv_sdl_window_get_renderer(disp);
    if (!renderer) return false;

    /* Force LVGL to fully re-render the current screen into SDL */
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(disp);

    /* SDL_RenderReadPixels reads from the render target (back buffer).
     * After lv_refr_now -> flush -> SDL_RenderPresent, buffers swapped.
     * Force one more render so current frame is in the back buffer. */
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(disp);

    int w = APP_LCD_H_RES;
    int h = APP_LCD_V_RES;

    SDL_Surface *surface = SDL_CreateRGBSurface(0, w, h, 32,
        0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
    if (!surface) return false;

    if (SDL_RenderReadPixels(renderer, NULL, SDL_PIXELFORMAT_ARGB8888,
                             surface->pixels, surface->pitch) != 0) {
        SDL_FreeSurface(surface);
        return false;
    }

    int result = SDL_SaveBMP(surface, path);
    SDL_FreeSurface(surface);
    return result == 0;
}

int main(int argc, char *argv[])
{
    bool screenshot_mode = false;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--screenshot") == 0) {
            screenshot_mode = true;
        }
    }

    /* Initialize LVGL */
    lv_init();

    /* Create SDL display */
    lv_display_t *disp = lv_sdl_window_create(APP_LCD_H_RES, APP_LCD_V_RES);
    lv_sdl_window_set_title(disp, "Bisque Kiln Controller");

    /* Create input group (needed by profiles and firing screens) */
    lv_group_t *group = lv_group_create();
    lv_group_set_default(group);

    /* Create mouse input (doubles as encoder for clicking buttons) */
    lv_indev_t *mouse = lv_sdl_mouse_create();
    lv_indev_set_group(mouse, group);

    /* Create all screens */
    screens[UI_SCREEN_HOME] = ui_screen_home_create();
    screens[UI_SCREEN_CHART] = ui_screen_chart_create();
    screens[UI_SCREEN_PROFILES] = ui_screen_profiles_create();
    screens[UI_SCREEN_FIRING] = ui_screen_firing_create();

    /* Initial data update */
    update_screens();

    /* Populate chart with some mock history */
    thermocouple_reading_t tc_hist;
    thermocouple_get_latest(&tc_hist);
    for (int i = 0; i < 80; i++) {
        tc_hist.temperature_c = 25.0f + (842.0f - 25.0f) * i / 80.0f;
        ui_screen_chart_update(&tc_hist);
    }
    /* Reset to current reading */
    thermocouple_get_latest(&tc_hist);
    ui_screen_chart_update(&tc_hist);

    /* Load home screen */
    update_all_page_dots();
    lv_screen_load(screens[UI_SCREEN_HOME]);

    if (screenshot_mode) {
        /* Render a few frames to let LVGL settle */
        for (int i = 0; i < 10; i++) {
            lv_timer_handler();
            SDL_Delay(16);
        }

        const char *names[] = {"lcd-home", "lcd-chart", "lcd-profiles", "lcd-firing"};
        for (int i = 0; i < UI_SCREEN_COUNT; i++) {
            current_screen = i;
            update_all_page_dots();
            lv_screen_load(screens[i]);

            /* Render enough frames for LVGL to fully flush to SDL renderer */
            for (int f = 0; f < 30; f++) {
                lv_timer_handler();
                SDL_Delay(16);
            }
            /* Force one more full refresh */
            lv_refr_now(disp);
            lv_timer_handler();
            SDL_Delay(50);

            char path[256];
            snprintf(path, sizeof(path), "docs/screenshots/%s.bmp", names[i]);
            if (save_screenshot(disp, path)) {
                printf("Saved %s\n", path);
            } else {
                fprintf(stderr, "Failed to save %s: %s\n", path, SDL_GetError());
            }
        }

        lv_sdl_quit();
        return 0;
    }

    /* Interactive mode */
    printf("Bisque LCD Simulator\n");
    printf("  Left/Right arrows: switch screens\n");
    printf("  Q or close window: quit\n");

    bool running = true;
    while (running) {
        lv_timer_handler();

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
                case SDLK_LEFT:
                    switch_screen(current_screen - 1);
                    break;
                case SDLK_RIGHT:
                    switch_screen(current_screen + 1);
                    break;
                default:
                    break;
                }
            }
        }

        SDL_Delay(16); /* ~60 FPS */
    }

    lv_sdl_quit();
    return 0;
}
