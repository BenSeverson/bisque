#pragma once

/*
 * Bisque — Hardware Pin Assignments and Default Constants
 *
 * All GPIO assignments are configurable via Kconfig (menuconfig). Defaults
 * live in main/Kconfig.projbuild; edit pins there (or via `idf.py menuconfig`),
 * not here.
 */

/* --- SPI Bus (shared by thermocouple + display) --- */
#define APP_SPI_HOST     SPI2_HOST
#define APP_PIN_SPI_MOSI CONFIG_KILN_PIN_SPI_MOSI
#define APP_PIN_SPI_MISO CONFIG_KILN_PIN_SPI_MISO
#define APP_PIN_SPI_SCLK CONFIG_KILN_PIN_SPI_SCLK

/* --- MAX31855 Thermocouple --- */
#define APP_PIN_TC_CS CONFIG_KILN_PIN_TC_CS

/* --- SSR Output --- */
#define APP_PIN_SSR CONFIG_KILN_PIN_SSR

/* --- ST7796S Display --- */
#define APP_PIN_LCD_CS  CONFIG_KILN_PIN_LCD_CS
#define APP_PIN_LCD_DC  CONFIG_KILN_PIN_LCD_DC
#define APP_PIN_LCD_RST CONFIG_KILN_PIN_LCD_RST
#define APP_PIN_LCD_BL  CONFIG_KILN_PIN_LCD_BL

#define APP_LCD_H_RES       480
#define APP_LCD_V_RES       320
#define APP_LCD_SPI_FREQ_HZ (40 * 1000 * 1000)

/* --- PID Defaults --- */
#define APP_PID_KP_DEFAULT 2.0f
#define APP_PID_KI_DEFAULT 0.01f
#define APP_PID_KD_DEFAULT 50.0f
#define APP_PID_OUTPUT_MIN 0.0f
#define APP_PID_OUTPUT_MAX 1.0f
#define APP_PID_PERIOD_MS  1000

/* --- SSR Time-Proportional Period --- */
#define APP_SSR_WINDOW_MS 2000

/* --- Safety --- */
#define APP_HARDWARE_MAX_TEMP_C   1400.0f
#define APP_DEFAULT_MAX_SAFE_TEMP 1300.0f
#define APP_TEMP_FAULT_TIMEOUT_MS 5000

/* --- Wi-Fi --- */
#define APP_WIFI_AP_SSID    "Bisque"
#define APP_WIFI_AP_PASS    "bisquesetup"
#define APP_WIFI_AP_CHANNEL 1
#define APP_WIFI_MAX_RETRY  5

/* --- Task Configuration --- */
#define APP_TASK_SAFETY_PRIO    6
#define APP_TASK_TEMP_READ_PRIO 5
#define APP_TASK_FIRING_PRIO    4
#define APP_TASK_HTTPD_PRIO     3
#define APP_TASK_DISPLAY_PRIO   2

#define APP_TASK_SAFETY_STACK    4096
#define APP_TASK_TEMP_READ_STACK 4096
#define APP_TASK_FIRING_STACK    8192
#define APP_TASK_DISPLAY_STACK   16384

/* --- Input Buttons (5-way navigation switch: Up/Down/Left/Right/Center) --- */
#define APP_PIN_BTN_UP     CONFIG_KILN_PIN_BTN_UP
#define APP_PIN_BTN_DOWN   CONFIG_KILN_PIN_BTN_DOWN
#define APP_PIN_BTN_SELECT CONFIG_KILN_PIN_BTN_SELECT
#define APP_PIN_BTN_LEFT   CONFIG_KILN_PIN_BTN_LEFT
#define APP_PIN_BTN_RIGHT  CONFIG_KILN_PIN_BTN_RIGHT

/* --- Status LED (WS2812B) --- */
#define APP_PIN_STATUS_LED CONFIG_KILN_PIN_STATUS_LED

/* --- Optional GPIOs (-1 = disabled) --- */
#define APP_PIN_ALARM      CONFIG_KILN_PIN_ALARM
#define APP_PIN_VENT       CONFIG_KILN_PIN_VENT
#define APP_PIN_LID_SWITCH CONFIG_KILN_PIN_LID_SWITCH
