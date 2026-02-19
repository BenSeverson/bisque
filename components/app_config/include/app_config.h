#pragma once

/*
 * Bisque — Hardware Pin Assignments and Default Constants
 *
 * All pins are configurable via Kconfig (menuconfig), these are compile-time defaults.
 */

/* --- SPI Bus (shared by thermocouple + display) --- */
#define APP_SPI_HOST        SPI2_HOST
#define APP_PIN_SPI_MOSI    11
#define APP_PIN_SPI_MISO    13
#define APP_PIN_SPI_SCLK    12

/* --- MAX31855 Thermocouple --- */
#define APP_PIN_TC_CS       10

/* --- SSR Output --- */
#define APP_PIN_SSR         17

/* --- ST7735 Display --- */
#define APP_PIN_LCD_CS      9
#define APP_PIN_LCD_DC      46
#define APP_PIN_LCD_RST     3
#define APP_PIN_LCD_BL      8

#define APP_LCD_H_RES       128
#define APP_LCD_V_RES       160
#define APP_LCD_SPI_FREQ_HZ (20 * 1000 * 1000)

/* --- PID Defaults --- */
#define APP_PID_KP_DEFAULT  2.0f
#define APP_PID_KI_DEFAULT  0.01f
#define APP_PID_KD_DEFAULT  50.0f
#define APP_PID_OUTPUT_MIN  0.0f
#define APP_PID_OUTPUT_MAX  1.0f
#define APP_PID_PERIOD_MS   1000

/* --- SSR Time-Proportional Period --- */
#define APP_SSR_WINDOW_MS   2000

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
#define APP_TASK_SAFETY_PRIO     6
#define APP_TASK_TEMP_READ_PRIO  5
#define APP_TASK_FIRING_PRIO     4
#define APP_TASK_HTTPD_PRIO      3
#define APP_TASK_DISPLAY_PRIO    2

#define APP_TASK_SAFETY_STACK    4096
#define APP_TASK_TEMP_READ_STACK 4096
#define APP_TASK_FIRING_STACK    8192
#define APP_TASK_DISPLAY_STACK   4096

/* --- Alarm / Vent GPIO (optional, -1 = disabled) --- */
#ifdef CONFIG_KILN_PIN_ALARM
#define APP_PIN_ALARM        CONFIG_KILN_PIN_ALARM
#else
#define APP_PIN_ALARM        (-1)
#endif

#ifdef CONFIG_KILN_PIN_VENT
#define APP_PIN_VENT         CONFIG_KILN_PIN_VENT
#else
#define APP_PIN_VENT         (-1)
#endif

/* --- Firmware Info --- */
#define APP_FIRMWARE_VERSION "2.0.0"
