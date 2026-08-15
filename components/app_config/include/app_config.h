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

/* --- MAX31856 Thermocouple (2 channels on the shared SPI bus) --- */
#define APP_PIN_TC1_CS CONFIG_KILN_PIN_TC1_CS
#define APP_PIN_TC2_CS CONFIG_KILN_PIN_TC2_CS

/* --- SSR Outputs (opto-isolated, 2 zones) --- */
#define APP_PIN_SSR1 CONFIG_KILN_PIN_SSR1
#define APP_PIN_SSR2 CONFIG_KILN_PIN_SSR2

/* --- ST7796S Display --- */
#define APP_PIN_LCD_CS  CONFIG_KILN_PIN_LCD_CS
#define APP_PIN_LCD_DC  CONFIG_KILN_PIN_LCD_DC
#define APP_PIN_LCD_RST CONFIG_KILN_PIN_LCD_RST
#define APP_PIN_LCD_BL  CONFIG_KILN_PIN_LCD_BL

#define APP_LCD_H_RES 480
#define APP_LCD_V_RES 320
/* ST7796S datasheet rates the write cycle at 66 MHz (Tcycw=15ns); 40 MHz stays
 * within spec for the hand-soldered perfboard wiring in a noisy kiln environment. */
#define APP_LCD_SPI_FREQ_HZ (40 * 1000 * 1000)

/* --- PID Defaults --- */
#define APP_PID_KP_DEFAULT 2.0f
#define APP_PID_KI_DEFAULT 0.01f
/* Pre-autotune starting derivative gain. Kept modest because the MAX31855's
 * 0.25°C quantization step, at the 1 Hz tick, turned a large Kd into a
 * noise-driven bang-bang term (see pid_compute's filtered derivative).
 *
 * THAT RATIONALE IS REV A's. Rev B reads 2x MAX31856 at 19-bit resolution
 * (0.0078125°C), roughly 32x finer, so the quantization noise this value was
 * chosen to survive is gone. The value is carried forward unchanged because
 * nothing has measured the replacement — revisit it on the bench at rev B
 * bring-up rather than inheriting it silently. Autotune overrides it either
 * way; it is a safe default, not a tuned one. */
#define APP_PID_KD_DEFAULT 5.0f
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
/* Aux output bank (ULN2003 channels 1-3). Routed and populated on the rev B
   PCB but NOT DRIVEN BY ANY CODE except AUX1, which components/safety/ drives
   as the vent. Roles are firmware policy, not wiring — see
   docs/pin-assignments.md §5. */
#define APP_PIN_AUX2 CONFIG_KILN_PIN_AUX2
#define APP_PIN_AUX3 CONFIG_KILN_PIN_AUX3

/* Protected dry-contact inputs. IN1 is the lid switch (APP_PIN_LID_SWITCH). */
#define APP_PIN_IN_GASFLOW CONFIG_KILN_PIN_IN_GASFLOW
#define APP_PIN_IN_SPARE   CONFIG_KILN_PIN_IN_SPARE

/* I2C bus: on-board ADE7953 current metering + Qwiic expansion header. */
#define APP_PIN_I2C_SDA CONFIG_KILN_PIN_I2C_SDA
#define APP_PIN_I2C_SCL CONFIG_KILN_PIN_I2C_SCL

/* XPT2046 touch controller (on the display module, shared SPI bus). */
#define APP_PIN_TOUCH_CS  CONFIG_KILN_PIN_TOUCH_CS
#define APP_PIN_TOUCH_IRQ CONFIG_KILN_PIN_TOUCH_IRQ

/* Hardware watchdog kick — gates both SSR opto channels. */
#define APP_PIN_WDT_KICK CONFIG_KILN_PIN_WDT_KICK
/* True when a LOW level means the lid is open. The default is 0 — normally-closed
   wiring, where lid-open is the pulled-up HIGH and a broken wire therefore reads
   open and fails safe. See the Kconfig help. The Kconfig symbol only exists when
   a lid pin is configured, so default it here for the -1 case rather than making
   every consumer #ifdef. */
#ifdef CONFIG_KILN_LID_SWITCH_OPEN_IS_LOW
#define APP_LID_SWITCH_OPEN_IS_LOW 1
#else
#define APP_LID_SWITCH_OPEN_IS_LOW 0
#endif
