#include "web_server.h"
#include "firing_engine.h"
#include "thermocouple.h"
#include "esp_log.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include <stdlib.h>
#include <string.h>

static const char *TAG = "ws";

/* Track connected WebSocket file descriptors. Mutated from the httpd task (on
 * connect) and the broadcast worker task (pruning dead fds on send failure), so
 * every access is guarded by s_ws_mutex. */
#define MAX_WS_CLIENTS 4
static int s_ws_fds[MAX_WS_CLIENTS];
static int s_ws_count = 0;
static SemaphoreHandle_t s_ws_mutex;

/* Broadcast worker task */
static TaskHandle_t s_ws_task = NULL;

/* The client sends no application data (this is a one-way telemetry channel), so
 * any inbound frame is tiny. Cap it so a malfunctioning or hostile client can't
 * make the device malloc() an arbitrary, header-advertised length and exhaust
 * the heap out from under the firing/safety tasks. */
#define MAX_WS_FRAME_LEN 1024

/* ── WebSocket handler ─────────────────────────────── */

static esp_err_t ws_handler(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        /* New WebSocket connection */
        int fd = httpd_req_to_sockfd(req);
        if (s_ws_mutex) {
            xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        }
        bool already = false;
        for (int i = 0; i < s_ws_count; i++) {
            if (s_ws_fds[i] == fd) {
                already = true; /* fd reused for a fresh handshake; keep one entry */
                break;
            }
        }
        if (already) {
            ESP_LOGD(TAG, "WebSocket fd=%d already tracked", fd);
        } else if (s_ws_count < MAX_WS_CLIENTS) {
            s_ws_fds[s_ws_count++] = fd;
            ESP_LOGI(TAG, "WebSocket client connected (fd=%d, total=%d)", fd, s_ws_count);
        } else {
            /* Not silent: the client completes the handshake but will never get
               updates, which is otherwise invisible to operators. */
            ESP_LOGW(TAG, "WebSocket client table full (%d); fd=%d will receive no updates", MAX_WS_CLIENTS, fd);
        }
        if (s_ws_mutex) {
            xSemaphoreGive(s_ws_mutex);
        }
        return ESP_OK;
    }

    /* Receive a WebSocket frame */
    httpd_ws_frame_t ws_pkt;
    memset(&ws_pkt, 0, sizeof(ws_pkt));
    ws_pkt.type = HTTPD_WS_TYPE_TEXT;

    /* First call to get the frame length */
    esp_err_t ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
    if (ret != ESP_OK) {
        return ret;
    }

    if (ws_pkt.len > MAX_WS_FRAME_LEN) {
        ESP_LOGW(TAG, "WS frame length %u exceeds cap %d; dropping connection", (unsigned)ws_pkt.len, MAX_WS_FRAME_LEN);
        return ESP_ERR_INVALID_SIZE;
    }

    if (ws_pkt.len > 0) {
        uint8_t *buf = malloc(ws_pkt.len + 1);
        if (!buf) {
            return ESP_ERR_NO_MEM;
        }
        ws_pkt.payload = buf;
        ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
        if (ret == ESP_OK) {
            buf[ws_pkt.len] = '\0';
            ESP_LOGD(TAG, "WS received: %s", (char *)buf);
            /* Could handle client commands here in the future */
        }
        free(buf);
    }

    return ESP_OK;
}

/* ── Broadcast to all connected WebSocket clients ──── */

void ws_broadcast(const char *json, size_t len)
{
    httpd_handle_t server = web_server_get_handle();
    if (!server) {
        return;
    }

    httpd_ws_frame_t ws_pkt = {
        .final = true,
        .fragmented = false,
        .type = HTTPD_WS_TYPE_TEXT,
        .payload = (uint8_t *)json,
        .len = len,
    };

    /* Snapshot the fd list under the lock, then send outside it: the async send
       can do real work and we must not hold the mutex (which the httpd task also
       needs on connect) across it. */
    int fds[MAX_WS_CLIENTS];
    int n = 0;
    if (s_ws_mutex) {
        xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    }
    n = s_ws_count;
    memcpy(fds, s_ws_fds, (size_t)n * sizeof(fds[0]));
    if (s_ws_mutex) {
        xSemaphoreGive(s_ws_mutex);
    }

    int dead[MAX_WS_CLIENTS];
    int n_dead = 0;
    for (int i = 0; i < n; i++) {
        if (httpd_ws_send_frame_async(server, fds[i], &ws_pkt) != ESP_OK) {
            ESP_LOGD(TAG, "WS client fd=%d disconnected", fds[i]);
            dead[n_dead++] = fds[i];
        }
    }

    /* Remove only the fds that actually failed, so a client that connected
       during the send above (and isn't in our snapshot) is preserved rather
       than clobbered by writing back a stale compacted list. */
    if (n_dead > 0) {
        if (s_ws_mutex) {
            xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        }
        int valid = 0;
        for (int i = 0; i < s_ws_count; i++) {
            bool is_dead = false;
            for (int j = 0; j < n_dead; j++) {
                if (s_ws_fds[i] == dead[j]) {
                    is_dead = true;
                    break;
                }
            }
            if (!is_dead) {
                s_ws_fds[valid++] = s_ws_fds[i];
            }
        }
        s_ws_count = valid;
        if (s_ws_mutex) {
            xSemaphoreGive(s_ws_mutex);
        }
    }
}

/* Compose and send a status frame. Runs on the broadcast worker task. */
void ws_broadcast_status(void)
{
    firing_progress_t prog;
    firing_engine_get_progress(&prog);

    thermocouple_reading_t tc;
    thermocouple_get_latest(&tc);

    kiln_settings_t settings;
    firing_engine_get_settings(&settings);
    float adjusted_temp = tc.fault ? 0.0f : (tc.temperature_c + settings.tc_offset_c);

    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "temp_update");

    cJSON *data = cJSON_AddObjectToObject(root, "data");
    json_add_progress_fields(data, &prog, adjusted_temp);

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    if (json) {
        ws_broadcast(json, strlen(json));
        free(json);
    }
}

/* ── OTA progress events ────────────────────────────── */

void ws_send_ota_event(ota_phase_t phase, int percent, const char *err)
{
    cJSON *root = cJSON_CreateObject();
    cJSON *data = cJSON_AddObjectToObject(root, "data");

    switch (phase) {
    case OTA_PHASE_DOWNLOAD:
    case OTA_PHASE_FLASH:
        cJSON_AddStringToObject(root, "type", "ota_progress");
        cJSON_AddStringToObject(data, "phase", phase == OTA_PHASE_FLASH ? "flash" : "download");
        cJSON_AddNumberToObject(data, "percent", percent);
        break;
    case OTA_PHASE_COMPLETE:
        cJSON_AddStringToObject(root, "type", "ota_complete");
        cJSON_AddNumberToObject(data, "percent", 100);
        break;
    case OTA_PHASE_ERROR:
        cJSON_AddStringToObject(root, "type", "ota_error");
        cJSON_AddStringToObject(data, "message", err ? err : "Update failed");
        break;
    default:
        cJSON_Delete(root);
        return;
    }

    char *json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (json) {
        ws_broadcast(json, strlen(json));
        free(json);
    }
}

/* ── Broadcast worker task ──────────────────────────── */

void ws_broadcast_notify(void)
{
    if (s_ws_task) {
        xTaskNotifyGive(s_ws_task);
    }
}

static void ws_broadcast_task(void *arg)
{
    (void)arg;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        ws_broadcast_status();
    }
}

esp_err_t ws_handler_start(void)
{
    if (s_ws_task) {
        return ESP_OK;
    }
    BaseType_t ok = xTaskCreatePinnedToCore(ws_broadcast_task, "ws_broadcast", 4096, NULL, 2, &s_ws_task, 0);
    return (ok == pdPASS) ? ESP_OK : ESP_ERR_NO_MEM;
}

/* ── Register ──────────────────────────────────────── */

esp_err_t ws_handler_register(httpd_handle_t server)
{
    /* Created once, before any client can connect (registration runs during
       server bring-up on a single task). Guards the fd table for the lifetime
       of the server. */
    if (!s_ws_mutex) {
        s_ws_mutex = xSemaphoreCreateMutex();
        if (!s_ws_mutex) {
            ESP_LOGE(TAG, "Failed to create WebSocket client mutex");
            return ESP_ERR_NO_MEM;
        }
    }

    httpd_uri_t ws_uri = {
        .uri = "/api/v1/ws",
        .method = HTTP_GET,
        .handler = ws_handler,
        .is_websocket = true,
    };

    esp_err_t ret = httpd_register_uri_handler(server, &ws_uri);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to register WebSocket handler");
    } else {
        ESP_LOGI(TAG, "WebSocket handler registered at /api/v1/ws");
    }
    return ret;
}
