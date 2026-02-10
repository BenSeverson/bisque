#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize Wi-Fi in STA mode. Falls back to AP mode if STA credentials are empty
 * or connection fails after retries.
 *
 * @param sta_ssid    Station SSID (empty string = skip STA, go straight to AP)
 * @param sta_pass    Station password
 * @param ap_ssid     AP mode SSID
 * @param ap_pass     AP mode password
 * @return ESP_OK on successful init (doesn't guarantee connection)
 */
esp_err_t wifi_manager_init(const char *sta_ssid, const char *sta_pass,
                            const char *ap_ssid, const char *ap_pass);

/**
 * Block until Wi-Fi is connected (STA) or AP is started. Timeout in ms.
 * Returns ESP_OK if connected, ESP_ERR_TIMEOUT otherwise.
 */
esp_err_t wifi_manager_wait_connected(uint32_t timeout_ms);

/**
 * Check if currently connected to an AP (STA mode).
 */
bool wifi_manager_is_connected(void);

/**
 * Check if running in AP mode.
 */
bool wifi_manager_is_ap_mode(void);

/**
 * Get the current IP address as a string.
 */
const char *wifi_manager_get_ip(void);

#ifdef __cplusplus
}
#endif
