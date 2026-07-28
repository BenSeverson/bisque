#include "wifi_manager.h"
#include "wifi_retry_policy.h"
#include "app_config.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include <string.h>

static const char *TAG = "wifi_mgr";

#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

/* The worker owns every mode switch and every esp_wifi_connect(). It is a plain
   low-priority task that sleeps on its queue, so nothing here can delay the
   firing or safety tasks, and it never touches the SSR. */
#define WIFI_WORKER_TICK_MS 1000
#define WIFI_WORKER_STACK   4096
#define WIFI_WORKER_PRIO    1
#define WIFI_WORKER_CORE    0

typedef enum {
    WIFI_CMD_STA_CONNECT = 0,   /* STA_START, or a paced retry */
    WIFI_CMD_ENTER_AP_FALLBACK, /* STA gave up; bring the provisioning AP up */
    WIFI_CMD_POLL,              /* wake the worker so it re-evaluates now */
} wifi_cmd_t;

static EventGroupHandle_t s_wifi_event_group;
static QueueHandle_t s_cmd_queue;

/* Shared between the event-loop task and the worker. Each has exactly one
   writer and every value is word-sized, so no lock is needed — but the
   direction differs per flag, so check before adding a writer:
     s_ap_clients, s_sta_connected — written by the event-loop task, read by
       the worker.
     s_ap_active — the reverse: written by the worker (and once by
       wifi_manager_init, before the worker task exists), read by the handler. */
static volatile int s_ap_clients = 0;
static volatile bool s_sta_connected = false;
static volatile bool s_ap_active = false;

static int s_retry_count = 0; /* fast pre-fallback attempts; event-loop task only */

/* Worker-task-owned. */
static wifi_retry_state_t s_retry;

static esp_netif_t *s_netif_sta;
static esp_netif_t *s_netif_ap;

static char s_ip_str[16] = "0.0.0.0";
static bool s_sta_configured = false;

static const char *s_ap_ssid;
static const char *s_ap_pass;

static void post_cmd(wifi_cmd_t cmd)
{
    if (s_cmd_queue != NULL) {
        /* Never block: this runs on the event-loop task. A full queue just means
           the worker already has work pending, which is the same outcome. */
        (void)xQueueSend(s_cmd_queue, &cmd, 0);
    }
}

/* ── Event handler — bookkeeping only, no radio calls ──────────────────── */

/* Everything that touches the radio is deferred to the worker. The old handler
   called esp_wifi_stop() and esp_netif_create_default_wifi_ap() inline, which is
   what made a second fallback abort on the duplicate netif (issue #78). */
static void event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT) {
        switch (event_id) {
        case WIFI_EVENT_STA_START:
            post_cmd(WIFI_CMD_STA_CONNECT);
            break;
        case WIFI_EVENT_STA_DISCONNECTED:
            s_sta_connected = false;
            if (!s_ap_active) {
                /* The AP is not up yet: burn through the fast retries, then fall
                   back. Losing an established STA link re-enters this path, so a
                   router reboot still reaches the AP. */
                xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
                if (s_retry_count < APP_WIFI_MAX_RETRY) {
                    s_retry_count++;
                    ESP_LOGI(TAG, "STA retry %d/%d", s_retry_count, APP_WIFI_MAX_RETRY);
                    post_cmd(WIFI_CMD_STA_CONNECT);
                } else {
                    ESP_LOGW(TAG, "STA connection failed, switching to AP mode");
                    xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
                    post_cmd(WIFI_CMD_ENTER_AP_FALLBACK);
                }
            }
            /* While the AP is up the backoff policy paces retries; reacting to
               the failure here would busy-loop the radio during a firing. */
            break;
        case WIFI_EVENT_AP_STACONNECTED: {
            wifi_event_ap_staconnected_t *evt = (wifi_event_ap_staconnected_t *)event_data;
            s_ap_clients++;
            ESP_LOGI(TAG, "Station connected to AP, AID=%d (%d associated)", evt->aid, s_ap_clients);
            break;
        }
        case WIFI_EVENT_AP_STADISCONNECTED: {
            if (s_ap_clients > 0) {
                s_ap_clients--;
            }
            ESP_LOGI(TAG, "Station left AP (%d associated)", s_ap_clients);
            /* A pending retry may have been suppressed by this client. */
            post_cmd(WIFI_CMD_POLL);
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
        s_sta_connected = true;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
        post_cmd(WIFI_CMD_POLL);
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

/* ── Worker task — the only place the Wi-Fi mode changes ───────────────── */

static void apply_ap_config(void)
{
    wifi_config_t ap_config = {
        .ap =
            {
                .channel = APP_WIFI_AP_CHANNEL,
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

    esp_err_t err = esp_wifi_set_config(WIFI_IF_AP, &ap_config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_set_config(AP) failed: %s", esp_err_to_name(err));
    }
}

/* Bring the provisioning AP up alongside (not instead of) the STA interface.
   APSTA keeps the STA interface available for the retry loop, so recovery never
   requires tearing the AP down. Idempotent: a second call is a no-op rather
   than a duplicate-netif abort. */
static void enter_ap_fallback(void)
{
    if (s_ap_active) {
        return;
    }

    wifi_mode_t mode = s_sta_configured ? WIFI_MODE_APSTA : WIFI_MODE_AP;
    esp_err_t err = esp_wifi_set_mode(mode);
    if (err != ESP_OK) {
        /* Deliberately not ESP_ERROR_CHECK: aborting the controller over a
           Wi-Fi hiccup would take a firing with it. Retry on the next tick. */
        ESP_LOGE(TAG, "esp_wifi_set_mode(%s) failed: %s", s_sta_configured ? "APSTA" : "AP", esp_err_to_name(err));
        return;
    }
    apply_ap_config();

    s_ap_active = true;
    wifi_retry_reset(&s_retry, esp_timer_get_time());
    snprintf(s_ip_str, sizeof(s_ip_str), "192.168.4.1");
    ESP_LOGI(TAG, "AP started: SSID=%s, IP=%s", s_ap_ssid, s_ip_str);
    xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
}

/* The configured network came back. Drop the AP and return to the plain STA
   steady state — but only when nobody is associated, so a user who joined the
   AP in the seconds since the successful retry is not cut off mid-form. */
static void leave_ap_fallback(void)
{
    if (s_ap_clients > 0) {
        return;
    }

    esp_err_t err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_set_mode(STA) failed: %s", esp_err_to_name(err));
        return;
    }

    s_ap_active = false;
    xEventGroupClearBits(s_wifi_event_group, WIFI_FAIL_BIT);
    ESP_LOGI(TAG, "STA recovered, AP stopped; IP: %s", s_ip_str);
}

static void try_sta_connect(void)
{
    esp_err_t err = esp_wifi_connect();
    if (err != ESP_OK && err != ESP_ERR_WIFI_CONN) {
        ESP_LOGW(TAG, "esp_wifi_connect failed: %s", esp_err_to_name(err));
    }
}

static void service_ap_fallback(void)
{
    if (!s_ap_active) {
        return;
    }
    if (s_sta_connected) {
        leave_ap_fallback();
        return;
    }
    if (!s_sta_configured) {
        return; /* provisioning-only AP; there is nothing to reconnect to */
    }

    switch (wifi_retry_step(&s_retry, s_ap_clients > 0, esp_timer_get_time())) {
    case WIFI_RETRY_ATTEMPT:
        ESP_LOGI(TAG, "AP fallback: STA reconnect attempt %u (next in %u s)", (unsigned)s_retry.attempt_count,
                 (unsigned)(wifi_retry_backoff_ms(s_retry.attempt_count) / 1000));
        try_sta_connect();
        break;
    case WIFI_RETRY_SUPPRESSED:
        ESP_LOGD(TAG, "AP fallback: retry due but %d client(s) associated, holding", s_ap_clients);
        break;
    case WIFI_RETRY_NOT_DUE:
    default:
        break;
    }
}

static void wifi_worker_task(void *arg)
{
    for (;;) {
        wifi_cmd_t cmd;
        if (xQueueReceive(s_cmd_queue, &cmd, pdMS_TO_TICKS(WIFI_WORKER_TICK_MS)) == pdTRUE) {
            switch (cmd) {
            case WIFI_CMD_STA_CONNECT:
                try_sta_connect();
                break;
            case WIFI_CMD_ENTER_AP_FALLBACK:
                enter_ap_fallback();
                break;
            case WIFI_CMD_POLL:
            default:
                break;
            }
        }
        service_ap_fallback();
    }
}

/* ── Init ──────────────────────────────────────────────────────────────── */

esp_err_t wifi_manager_init(const char *sta_ssid, const char *sta_pass, const char *ap_ssid, const char *ap_pass)
{
    s_ap_ssid = ap_ssid;
    s_ap_pass = ap_pass;
    s_sta_configured = (sta_ssid != NULL && sta_ssid[0] != '\0');
    s_wifi_event_group = xEventGroupCreate();
    s_cmd_queue = xQueueCreate(8, sizeof(wifi_cmd_t));
    if (s_wifi_event_group == NULL || s_cmd_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    /* Both netifs are created exactly once, here, before the radio starts.
       Creating them up front is what makes the AP fallback re-entrant — the old
       code created the AP netif inside the fallback path, so a second fallback
       aborted on the duplicate. The unused one costs a few hundred bytes. */
    if (s_netif_sta == NULL) {
        s_netif_sta = esp_netif_create_default_wifi_sta();
    }
    if (s_netif_ap == NULL) {
        s_netif_ap = esp_netif_create_default_wifi_ap();
    }
    if (s_netif_sta == NULL || s_netif_ap == NULL) {
        return ESP_ERR_NO_MEM;
    }

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &event_handler, NULL, NULL));

    if (s_sta_configured) {
        wifi_config_t sta_config = {};
        copy_credential(sta_config.sta.ssid, sizeof(sta_config.sta.ssid), sta_ssid);
        copy_credential(sta_config.sta.password, sizeof(sta_config.sta.password), sta_pass);

        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_config));
    } else {
        ESP_LOGI(TAG, "No STA SSID configured, starting AP mode");
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
        apply_ap_config();
    }

    BaseType_t rc = xTaskCreatePinnedToCore(wifi_worker_task, "wifi_worker", WIFI_WORKER_STACK, NULL, WIFI_WORKER_PRIO,
                                            NULL, WIFI_WORKER_CORE);
    if (rc != pdPASS) {
        ESP_LOGE(TAG, "Failed to create wifi_worker task (rc=%d)", (int)rc);
        return ESP_ERR_NO_MEM;
    }

    /* Started last, so the worker is already draining the queue when the first
       STA_START / AP_START event lands. */
    ESP_ERROR_CHECK(esp_wifi_start());

    if (s_sta_configured) {
        ESP_LOGI(TAG, "STA mode started, connecting to %s", sta_ssid);
    } else {
        s_ap_active = true;
        snprintf(s_ip_str, sizeof(s_ip_str), "192.168.4.1");
        ESP_LOGI(TAG, "AP started: SSID=%s, IP=%s", s_ap_ssid, s_ip_str);
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
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
    /* During APSTA recovery the AP is briefly still up while the STA already
       has an IP. Callers (status LED, boot banner, /api/wifi) mean "the AP is
       the only way in", so a live STA link wins. */
    return s_ap_active && !s_sta_connected;
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
