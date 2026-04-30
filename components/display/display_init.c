#include "display.h"
#include "ui_common.h"
#include "ui_theme.h"
#include "app_config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_st7796.h"
#include "driver/gpio.h"
#include "lvgl.h"
#include <string.h>

static const char *TAG = "display";

/* --- Globals shared with dashboard.c and modal.c --- */
lv_indev_t *g_indev_encoder = NULL;
lv_group_t *g_input_group = NULL;
lv_group_t *g_modal_group = NULL;

/* --- Static state --- */
static esp_lcd_panel_handle_t s_panel = NULL;
static lv_display_t *s_disp = NULL;
static int s_bl_pin = -1;

/* Double-buffered DMA draw buffers: 40 rows each */
#define DRAW_BUF_LINES 40
static uint8_t s_buf1[UI_LCD_W * DRAW_BUF_LINES * 2] __attribute__((aligned(4)));
static uint8_t s_buf2[UI_LCD_W * DRAW_BUF_LINES * 2] __attribute__((aligned(4)));

/* Button debounce state — 5-way nav switch */
enum { BTN_UP = 0, BTN_DOWN, BTN_SELECT, BTN_LEFT, BTN_RIGHT, BTN_COUNT };

static const char *const BTN_NAMES[BTN_COUNT] = {"UP", "DOWN", "SELECT", "LEFT", "RIGHT"};

static struct {
    int pin;
    bool pressed;
    int64_t last_change_us;
} s_buttons[BTN_COUNT];

#define BTN_DEBOUNCE_US 50000 /* 50ms */

/* ── Flush callback ────────────────────────────── */

static bool on_color_trans_done(esp_lcd_panel_io_handle_t io, esp_lcd_panel_io_event_data_t *edata, void *user_ctx)
{
    (void)io;
    (void)edata;
    lv_display_t *disp = (lv_display_t *)user_ctx;
    lv_display_flush_ready(disp);
    return false;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    esp_lcd_panel_draw_bitmap(s_panel, area->x1, area->y1, area->x2 + 1, area->y2 + 1, px_map);
}

/* ── Tick ──────────────────────────────────────── */

static uint32_t tick_get_cb(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* ── Encoder input ─────────────────────────────── */

static bool btn_is_pressed(int idx)
{
    bool raw = (gpio_get_level(s_buttons[idx].pin) == 0); /* active-low */
    int64_t now = esp_timer_get_time();
    if (raw != s_buttons[idx].pressed) {
        if (now - s_buttons[idx].last_change_us > BTN_DEBOUNCE_US) {
            s_buttons[idx].pressed = raw;
            s_buttons[idx].last_change_us = now;
            ESP_LOGI(TAG, "btn %s %s", BTN_NAMES[idx], raw ? "down" : "up");
        }
    }
    return s_buttons[idx].pressed;
}

static void encoder_read_cb(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    static bool prev_up = false, prev_down = false;

    bool up = btn_is_pressed(BTN_UP);
    bool down = btn_is_pressed(BTN_DOWN);
    bool sel = btn_is_pressed(BTN_SELECT);

    /* Encoder diff: generate ±1 on press edge */
    data->enc_diff = 0;
    if (up && !prev_up) {
        data->enc_diff = -1;
    }
    if (down && !prev_down) {
        data->enc_diff = 1;
    }
    prev_up = up;
    prev_down = down;

    data->state = sel ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

/* Left / Right press-edge consumers for screen switching in display_task.
 * Each returns true exactly once per debounced press; subsequent calls while
 * the button is still held return false. */
static bool consume_edge(int idx, bool *prev)
{
    bool now = btn_is_pressed(idx);
    bool edge = now && !*prev;
    *prev = now;
    return edge;
}

bool display_consume_left_press(void)
{
    static bool prev_left = false;
    return consume_edge(BTN_LEFT, &prev_left);
}

bool display_consume_right_press(void)
{
    static bool prev_right = false;
    return consume_edge(BTN_RIGHT, &prev_right);
}

void display_backlight_on(void)
{
    if (s_bl_pin >= 0) {
        gpio_set_level(s_bl_pin, 1);
    }
}

/* ── Init ──────────────────────────────────────── */

esp_err_t display_init(spi_host_device_t host, int cs_pin, int dc_pin, int rst_pin, int bl_pin)
{
    /* Backlight - ST7796S modules are typically active-high (1 = on).
     * Keep BL off through init so the panel's uninitialized VRAM isn't visible
     * as static at power-on. display_backlight_on() raises it after the first
     * frame has been flushed by display_task. */
    s_bl_pin = bl_pin;
    if (bl_pin >= 0) {
        gpio_config_t bl_cfg = {
            .pin_bit_mask = (1ULL << bl_pin),
            .mode = GPIO_MODE_OUTPUT,
        };
        gpio_config(&bl_cfg);
        gpio_set_level(bl_pin, 0);
    }

    /* LCD panel IO (SPI) — register trans_done callback for DMA pipelining */
    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = dc_pin,
        .cs_gpio_num = cs_pin,
        .pclk_hz = APP_LCD_SPI_FREQ_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
        .on_color_trans_done = NULL, /* registered after display is created */
        .user_ctx = NULL,
    };
    esp_err_t ret = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)host, &io_config, &io_handle);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create panel IO: %s", esp_err_to_name(ret));
        return ret;
    }

    /* LCD panel (ST7796S) */
    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = rst_pin,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR,
        .bits_per_pixel = 16,
    };
    ret = esp_lcd_new_panel_st7796(io_handle, &panel_config, &s_panel);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to create panel: %s", esp_err_to_name(ret));
        return ret;
    }

    esp_lcd_panel_reset(s_panel);
    esp_lcd_panel_init(s_panel);
    esp_lcd_panel_set_gap(s_panel, 0, 0);
    esp_lcd_panel_invert_color(s_panel, false);
    esp_lcd_panel_swap_xy(s_panel, true);
    esp_lcd_panel_mirror(s_panel, false, false);
    esp_lcd_panel_disp_on_off(s_panel, true);

    /* ── LVGL Init ───────────────────────────────── */
    lv_init();
    lv_tick_set_cb(tick_get_cb);

    /* Create display */
    s_disp = lv_display_create(UI_LCD_W, UI_LCD_H);
    lv_display_set_flush_cb(s_disp, flush_cb);
    lv_display_set_buffers(s_disp, s_buf1, s_buf2, sizeof(s_buf1), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_color_format(s_disp, LV_COLOR_FORMAT_RGB565_SWAPPED);

    /* Install the UI theme before any widget is created so every widget picks up
     * the shared defaults. The default screen created inside lv_display_create()
     * predates this and won't be themed, but splash and dashboard build their own
     * full-screen roots that do get themed. */
    ui_theme_init(s_disp);

    /* Now set the user_ctx on the IO handle so the ISR can call flush_ready */
    esp_lcd_panel_io_register_event_callbacks(
        io_handle, &(esp_lcd_panel_io_callbacks_t){.on_color_trans_done = on_color_trans_done}, s_disp);

    /* ── Button GPIO Init ────────────────────────── */
    s_buttons[BTN_UP].pin = APP_PIN_BTN_UP;
    s_buttons[BTN_DOWN].pin = APP_PIN_BTN_DOWN;
    s_buttons[BTN_SELECT].pin = APP_PIN_BTN_SELECT;
    s_buttons[BTN_LEFT].pin = APP_PIN_BTN_LEFT;
    s_buttons[BTN_RIGHT].pin = APP_PIN_BTN_RIGHT;

    for (int i = 0; i < BTN_COUNT; i++) {
        gpio_config_t btn_cfg = {
            .pin_bit_mask = (1ULL << s_buttons[i].pin),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&btn_cfg);
        s_buttons[i].pressed = false;
        s_buttons[i].last_change_us = 0;
    }

    /* ── Encoder Input Device ────────────────────── */
    g_indev_encoder = lv_indev_create();
    lv_indev_set_type(g_indev_encoder, LV_INDEV_TYPE_ENCODER);
    lv_indev_set_read_cb(g_indev_encoder, encoder_read_cb);

    /* ── Input Groups ────────────────────────────── */
    /* g_input_group: dashboard's base focus group. Holds the dashboard's invisible
     *   SELECT trap so SELECT presses on the bare dashboard fire LV_EVENT_CLICKED.
     * g_modal_group: populated when a modal opens; encoder is switched to it so
     *   UP/DOWN/SELECT navigate the modal's widgets. */
    g_input_group = lv_group_create();
    g_modal_group = lv_group_create();
    lv_indev_set_group(g_indev_encoder, g_input_group);
    lv_group_set_default(g_input_group);

    ESP_LOGI(TAG, "LVGL display initialized (%dx%d, double-buffered %d lines)", UI_LCD_W, UI_LCD_H, DRAW_BUF_LINES);
    return ESP_OK;
}
