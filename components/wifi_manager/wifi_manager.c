#include "wifi_manager.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include <string.h>

static const char *TAG = "wifi_mgr";

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static EventGroupHandle_t s_wifi_event_group;
static int s_retry_count = 0;
static int s_max_retries = 5;
static bool s_is_ap_mode = false;
static char s_ip_str[16] = "0.0.0.0";

static const char *s_ap_ssid;
static const char *s_ap_pass;

static void start_ap(void);

static void event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT) {
        switch (event_id) {
        case WIFI_EVENT_STA_START:
            esp_wifi_connect();
            break;
        case WIFI_EVENT_STA_DISCONNECTED:
            if (s_retry_count < s_max_retries) {
                s_retry_count++;
                ESP_LOGI(TAG, "STA retry %d/%d", s_retry_count, s_max_retries);
                esp_wifi_connect();
            } else {
                ESP_LOGW(TAG, "STA connection failed, switching to AP mode");
                xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
                start_ap();
            }
            break;
        case WIFI_EVENT_AP_STACONNECTED: {
            wifi_event_ap_staconnected_t *evt = (wifi_event_ap_staconnected_t *)event_data;
            ESP_LOGI(TAG, "Station connected to AP, AID=%d", evt->aid);
            break;
        }
        default:
            break;
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evt = (ip_event_got_ip_t *)event_data;
        snprintf(s_ip_str, sizeof(s_ip_str), IPSTR, IP2STR(&evt->ip_info.ip));
        ESP_LOGI(TAG, "STA connected, IP: %s", s_ip_str);
        s_retry_count = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

/**
 * Copy a credential into a fixed-width 802.11 config field.
 *
 * Deliberately not `strncpy(dst, src, sizeof(dst) - 1)`. These fields are not
 * C strings: an SSID is 0–32 bytes and a WPA2 PSK may be 64 hex characters,
 * neither NUL-terminated at full width. Reserving a byte for a terminator
 * therefore drops the last character of exactly the longest *legal*
 * credentials — a 32-character SSID silently became a 31-character one, and
 * the device spent the rest of its life trying to join a network that does not
 * exist. `wifi_config_t` is zero-initialised at both call sites, so anything
 * shorter than the field stays NUL-terminated.
 *
 * NULL `src` leaves the field zeroed rather than trapping, which is the right
 * reading of "no password configured".
 */
static void copy_credential(uint8_t *dst, size_t dst_size, const char *src)
{
    if (!src) {
        return;
    }
    memcpy(dst, src, strnlen(src, dst_size));
}

static void start_ap(void)
{
    /* Stop STA first */
    esp_wifi_stop();

    wifi_config_t ap_config = {
        .ap =
            {
                .channel = 1,
                .max_connection = 4,
                .authmode = WIFI_AUTH_WPA2_PSK,
            },
    };
    copy_credential(ap_config.ap.ssid, sizeof(ap_config.ap.ssid), s_ap_ssid);
    ap_config.ap.ssid_len = strnlen(s_ap_ssid, sizeof(ap_config.ap.ssid));
    copy_credential(ap_config.ap.password, sizeof(ap_config.ap.password), s_ap_pass);

    if (strlen(s_ap_pass) < 8) {
        ap_config.ap.authmode = WIFI_AUTH_OPEN;
    }

    esp_netif_create_default_wifi_ap();
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    s_is_ap_mode = true;
    snprintf(s_ip_str, sizeof(s_ip_str), "192.168.4.1");
    ESP_LOGI(TAG, "AP started: SSID=%s, IP=%s", s_ap_ssid, s_ip_str);
    xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
}

esp_err_t wifi_manager_init(const char *sta_ssid, const char *sta_pass, const char *ap_ssid, const char *ap_pass)
{
    s_ap_ssid = ap_ssid;
    s_ap_pass = ap_pass;
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL, NULL));

    /* If no STA SSID, go directly to AP mode */
    if (sta_ssid == NULL || sta_ssid[0] == '\0') {
        ESP_LOGI(TAG, "No STA SSID configured, starting AP mode");
        start_ap();
        return ESP_OK;
    }

    /* Try STA mode */
    esp_netif_create_default_wifi_sta();

    wifi_config_t sta_config = {};
    copy_credential(sta_config.sta.ssid, sizeof(sta_config.sta.ssid), sta_ssid);
    copy_credential(sta_config.sta.password, sizeof(sta_config.sta.password), sta_pass);

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "STA mode started, connecting to %s", sta_ssid);
    return ESP_OK;
}

esp_err_t wifi_manager_wait_connected(uint32_t timeout_ms)
{
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT, pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(timeout_ms));

    if (bits & WIFI_CONNECTED_BIT) {
        return ESP_OK;
    }
    return ESP_ERR_TIMEOUT;
}

bool wifi_manager_is_connected(void)
{
    EventBits_t bits = xEventGroupGetBits(s_wifi_event_group);
    return (bits & WIFI_CONNECTED_BIT) != 0;
}

bool wifi_manager_is_ap_mode(void)
{
    return s_is_ap_mode;
}

const char *wifi_manager_get_ip(void)
{
    return s_ip_str;
}

/* ── NVS Credential Persistence ───────────────────── */

#define WIFI_NVS_NAMESPACE "wifi_cfg"

esp_err_t wifi_manager_load_creds(char *ssid, size_t ssid_len, char *pass, size_t pass_len)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(WIFI_NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err != ESP_OK) {
        return ESP_ERR_NVS_NOT_FOUND;
    }

    err = nvs_get_str(handle, "ssid", ssid, &ssid_len);
    if (err != ESP_OK) {
        nvs_close(handle);
        return ESP_ERR_NVS_NOT_FOUND;
    }

    err = nvs_get_str(handle, "pass", pass, &pass_len);
    if (err != ESP_OK) {
        /* SSID without password is valid (open network) */
        pass[0] = '\0';
    }

    nvs_close(handle);
    ESP_LOGI(TAG, "Loaded Wi-Fi credentials from NVS: SSID=%s", ssid);
    return ESP_OK;
}

esp_err_t wifi_manager_save_creds(const char *ssid, const char *pass)
{
    if (!ssid) {
        return ESP_ERR_INVALID_ARG;
    }
    /* Reject anything load_creds() could not read back, so a save that reports
     * success is one the device can actually use after a reboot (#134). */
    if (strlen(ssid) > WIFI_SSID_MAX_LEN || (pass && strlen(pass) > WIFI_PASS_MAX_LEN)) {
        ESP_LOGW(TAG, "Refusing over-length Wi-Fi credentials (ssid=%u pass=%u, max %d/%d)", (unsigned)strlen(ssid),
                 (unsigned)(pass ? strlen(pass) : 0), WIFI_SSID_MAX_LEN, WIFI_PASS_MAX_LEN);
        return ESP_ERR_INVALID_SIZE;
    }

    nvs_handle_t handle;
    esp_err_t err = nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }

    nvs_set_str(handle, "ssid", ssid);
    nvs_set_str(handle, "pass", pass ? pass : "");
    err = nvs_commit(handle);
    nvs_close(handle);

    ESP_LOGI(TAG, "Saved Wi-Fi credentials to NVS: SSID=%s", ssid);
    return err;
}

esp_err_t wifi_manager_clear_creds(void)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        return err;
    }

    nvs_erase_all(handle);
    err = nvs_commit(handle);
    nvs_close(handle);

    ESP_LOGI(TAG, "Cleared Wi-Fi credentials from NVS");
    return err;
}
