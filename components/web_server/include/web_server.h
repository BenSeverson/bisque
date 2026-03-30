#pragma once

#include "esp_err.h"
#include "esp_http_server.h"
#include "firing_types.h"

#ifdef __cplusplus
extern "C" {
#endif

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
 * Call from a timer or task to push periodic updates.
 */
void ws_broadcast_status(void);

/**
 * Convert firing status enum to lowercase string for JSON APIs.
 */
const char *firing_status_to_string(firing_status_t s);

/* Internal: register API handlers (called by web_server_start) */
esp_err_t api_handlers_register(httpd_handle_t server);
esp_err_t ws_handler_register(httpd_handle_t server);

#ifdef __cplusplus
}
#endif
