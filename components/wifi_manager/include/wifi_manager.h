#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Credential limits, fixed by the 802.11 field sizes NVS stores them in.
 * Anything longer cannot be read back by wifi_manager_load_creds() — nvs_get_str
 * fails with ESP_ERR_NVS_INVALID_LENGTH and the device silently falls back to AP
 * mode on the next boot (#134). Validate against these *before* storing.
 * The _BUF_ variants include room for the NUL. */
#define WIFI_SSID_MAX_LEN 32
#define WIFI_PASS_MAX_LEN 64
#define WIFI_SSID_BUF_LEN (WIFI_SSID_MAX_LEN + 1)
#define WIFI_PASS_BUF_LEN (WIFI_PASS_MAX_LEN + 1)

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
esp_err_t wifi_manager_init(const char *sta_ssid, const char *sta_pass, const char *ap_ssid, const char *ap_pass);

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

/**
 * Load Wi-Fi STA credentials from NVS.
 * Returns ESP_OK if credentials were found, ESP_ERR_NVS_NOT_FOUND otherwise.
 * Buffers must be at least WIFI_SSID_BUF_LEN / WIFI_PASS_BUF_LEN bytes.
 */
esp_err_t wifi_manager_load_creds(char *ssid, size_t ssid_len, char *pass, size_t pass_len);

/**
 * Save Wi-Fi STA credentials to NVS. Takes effect after reboot.
 * Returns ESP_ERR_INVALID_SIZE if either string exceeds WIFI_SSID_MAX_LEN /
 * WIFI_PASS_MAX_LEN, rather than storing something that cannot be loaded back.
 */
esp_err_t wifi_manager_save_creds(const char *ssid, const char *pass);

/**
 * Clear saved Wi-Fi STA credentials from NVS.
 */
esp_err_t wifi_manager_clear_creds(void);

#ifdef __cplusplus
}
#endif
