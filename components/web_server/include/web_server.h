#pragma once

#include "esp_err.h"
#include "esp_http_server.h"
#include "firing_types.h"
#include "cJSON.h"
#include "ota_manager.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Mount the "storage" SPIFFS partition at /www. Idempotent — safe to call
 * before web_server_start() so subsystems that only need the filesystem
 * (history_init()) can come up without waiting on the network stack.
 *
 * @return ESP_OK if mounted (or already mounted)
 */
esp_err_t web_server_mount_spiffs(void);

/**
 * Start the HTTP server with REST API, WebSocket, and static file serving.
 * All components must be initialized before calling this.
 *
 * @return ESP_OK on success
 */
esp_err_t web_server_start(void);

/**
 * Stop the HTTP server.
 */
void web_server_stop(void);

/**
 * Get the server handle (for WebSocket broadcasting from other tasks).
 */
httpd_handle_t web_server_get_handle(void);

/**
 * Broadcast a WebSocket message to all connected clients.
 * Called from the firing task to push temperature updates.
 */
void ws_broadcast(const char *json, size_t len);

/**
 * Compose and broadcast current status via WebSocket.
 * Runs on the dedicated ws_broadcast_task; do not call from ISR or
 * esp_timer context — use ws_broadcast_notify() to wake the task instead.
 */
void ws_broadcast_status(void);

/**
 * Wake the WebSocket broadcast task so it pushes a fresh status frame.
 * Safe to call from esp_timer callbacks; non-blocking.
 */
void ws_broadcast_notify(void);

/**
 * Start the WebSocket broadcast worker task. Call once after web_server_start().
 */
esp_err_t ws_handler_start(void);

/**
 * Broadcast an OTA progress/completion/error event to WebSocket clients.
 * Matches ota_progress_cb_t; registered with ota_set_progress_cb().
 */
void ws_send_ota_event(ota_phase_t phase, int percent, const char *err);

/**
 * Start the firing-event consumer task. Drains firing_engine_get_event_queue()
 * and runs slow side-effects (alarm, webhook POST) off the firing/safety path.
 */
esp_err_t notification_task_start(void);

/**
 * POST a JSON event to the configured webhook URL (5 s timeout). Blocking;
 * call from a worker task only.
 */
void send_webhook_event(const char *event, const char *profile_name, float peak_temp, uint32_t duration_s);

/**
 * Convert firing status enum to lowercase string for JSON APIs.
 */
const char *firing_status_to_string(firing_status_t s);

/**
 * Add the shared firing-progress fields (currentTemp, targetTemp, status,
 * segment counters, elapsed/remaining time, isActive, profileId, dutyPercent)
 * to `target`.
 * Used by both the REST status endpoint and the WebSocket broadcast so the two
 * payloads stay in sync.
 *
 * @param target       cJSON object to mutate.
 * @param prog         Snapshot from firing_engine_get_progress().
 * @param current_temp Temperature value to publish (caller decides whether
 *                     offset/fault adjustments apply).
 * @param ssr_duty     Live element duty 0.0–1.0, from safety_get_ssr_duty();
 *                     published as whole-percent `dutyPercent`.
 */
void json_add_progress_fields(cJSON *target, const firing_progress_t *prog, float current_temp, float ssr_duty);

/**
 * Check Bearer/query-parameter auth on a request. Returns true when the
 * request is authorized, including when no API token is configured (open
 * access). Shared so the WebSocket handshake is gated by exactly the same rule
 * as the REST endpoints rather than a second copy that can drift.
 *
 * Note the query-parameter path is not redundant with the header: browsers
 * cannot set headers on a WebSocket handshake, so `?token=` is the only
 * credential the web client can present on /api/v1/ws.
 */
bool web_auth_check(httpd_req_t *req);

/* Internal: register API handlers (called by web_server_start) */
esp_err_t api_handlers_register(httpd_handle_t server);
esp_err_t ws_handler_register(httpd_handle_t server);

#ifdef __cplusplus
}
#endif
