#include "web_server.h"
#include "firing_engine.h"
#include "thermocouple.h"
#include "esp_log.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "ws";

/* Track connected WebSocket file descriptors */
#define MAX_WS_CLIENTS 4
static int s_ws_fds[MAX_WS_CLIENTS];
static int s_ws_count = 0;

/* Broadcast worker task */
static TaskHandle_t s_ws_task = NULL;

/* ── WebSocket handler ─────────────────────────────── */

static esp_err_t ws_handler(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        /* New WebSocket connection */
        int fd = httpd_req_to_sockfd(req);
        if (s_ws_count < MAX_WS_CLIENTS) {
            s_ws_fds[s_ws_count++] = fd;
            ESP_LOGI(TAG, "WebSocket client connected (fd=%d, total=%d)", fd, s_ws_count);
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

    int valid = 0;
    for (int i = 0; i < s_ws_count; i++) {
        esp_err_t ret = httpd_ws_send_frame_async(server, s_ws_fds[i], &ws_pkt);
        if (ret == ESP_OK) {
            s_ws_fds[valid++] = s_ws_fds[i];
        } else {
            ESP_LOGD(TAG, "WS client fd=%d disconnected", s_ws_fds[i]);
        }
    }
    s_ws_count = valid;
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
    cJSON_AddNumberToObject(data, "currentTemp", adjusted_temp);
    cJSON_AddNumberToObject(data, "targetTemp", prog.target_temp);
    cJSON_AddStringToObject(data, "status", firing_status_to_string(prog.status));
    cJSON_AddNumberToObject(data, "currentSegment", prog.current_segment);
    cJSON_AddNumberToObject(data, "totalSegments", prog.total_segments);
    cJSON_AddNumberToObject(data, "elapsedTime", prog.elapsed_time);
    cJSON_AddNumberToObject(data, "estimatedTimeRemaining", prog.estimated_remaining);
    cJSON_AddBoolToObject(data, "isActive", prog.is_active);

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
