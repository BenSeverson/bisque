#include "web_server.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include <string.h>
#include <sys/stat.h>
#include <stdio.h>

static const char *TAG = "web_server";

static httpd_handle_t s_server = NULL;

/* ── MIME type lookup ──────────────────────────────── */

static const char *get_mime_type(const char *path)
{
    const char *ext = strrchr(path, '.');
    if (!ext) return "application/octet-stream";
    ext++;

    if (strcmp(ext, "html") == 0) return "text/html";
    if (strcmp(ext, "js") == 0)   return "application/javascript";
    if (strcmp(ext, "css") == 0)  return "text/css";
    if (strcmp(ext, "json") == 0) return "application/json";
    if (strcmp(ext, "png") == 0)  return "image/png";
    if (strcmp(ext, "jpg") == 0 || strcmp(ext, "jpeg") == 0) return "image/jpeg";
    if (strcmp(ext, "svg") == 0)  return "image/svg+xml";
    if (strcmp(ext, "ico") == 0)  return "image/x-icon";
    if (strcmp(ext, "woff") == 0) return "font/woff";
    if (strcmp(ext, "woff2") == 0) return "font/woff2";
    if (strcmp(ext, "ttf") == 0)  return "font/ttf";
    return "application/octet-stream";
}

/* ── Static file handler (SPA fallback) ────────────── */

#define FILE_BUF_SIZE 2048

static esp_err_t static_file_handler(httpd_req_t *req)
{
    const char *uri = req->uri;

    /* Skip API routes — they are handled by api_handlers */
    if (strncmp(uri, "/api/", 5) == 0) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Not found");
        return ESP_FAIL;
    }

    /* Build file path — truncate long URIs safely */
    char filepath[128];
    if (strcmp(uri, "/") == 0) {
        snprintf(filepath, sizeof(filepath), "/www/index.html");
    } else {
        snprintf(filepath, sizeof(filepath), "/www%.122s", uri);
    }

    /* Strip query string */
    char *query = strchr(filepath, '?');
    if (query) *query = '\0';

    /* Try gzipped version first */
    char gz_path[132];
    snprintf(gz_path, sizeof(gz_path), "%s.gz", filepath);

    struct stat st;
    bool is_gzipped = false;
    FILE *f = NULL;

    if (stat(gz_path, &st) == 0) {
        f = fopen(gz_path, "r");
        if (f) is_gzipped = true;
    }

    if (!f) {
        if (stat(filepath, &st) == 0) {
            f = fopen(filepath, "r");
        }
    }

    /* SPA fallback: serve index.html for unknown paths */
    if (!f) {
        const char *fallback = "/www/index.html";
        const char *gz_fallback = "/www/index.html.gz";

        if (stat(gz_fallback, &st) == 0) {
            f = fopen(gz_fallback, "r");
            if (f) is_gzipped = true;
        }
        if (!f && stat(fallback, &st) == 0) {
            f = fopen(fallback, "r");
        }
        if (f) {
            /* Set Content-Type for index.html */
            httpd_resp_set_type(req, "text/html");
        }
    } else {
        httpd_resp_set_type(req, get_mime_type(filepath));
    }

    if (!f) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "File not found");
        return ESP_FAIL;
    }

    if (is_gzipped) {
        httpd_resp_set_hdr(req, "Content-Encoding", "gzip");
        /* Set MIME type based on original (non-.gz) path */
        httpd_resp_set_type(req, get_mime_type(filepath));
    }

    /* Cache static assets aggressively, but not index.html */
    if (strstr(filepath, "/assets/") || strstr(filepath, ".js") || strstr(filepath, ".css")) {
        httpd_resp_set_hdr(req, "Cache-Control", "public, max-age=31536000, immutable");
    }

    /* Stream the file */
    char buf[FILE_BUF_SIZE];
    size_t read_bytes;
    while ((read_bytes = fread(buf, 1, sizeof(buf), f)) > 0) {
        if (httpd_resp_send_chunk(req, buf, read_bytes) != ESP_OK) {
            fclose(f);
            httpd_resp_send_chunk(req, NULL, 0);
            return ESP_FAIL;
        }
    }
    fclose(f);
    httpd_resp_send_chunk(req, NULL, 0);
    return ESP_OK;
}

/* ── SPIFFS Init ───────────────────────────────────── */

static esp_err_t init_spiffs(void)
{
    esp_vfs_spiffs_conf_t conf = {
        .base_path = "/www",
        .partition_label = "storage",
        .max_files = 8,
        .format_if_mount_failed = false,
    };
    esp_err_t ret = esp_vfs_spiffs_register(&conf);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "SPIFFS mount failed: %s", esp_err_to_name(ret));
        return ret;
    }

    size_t total = 0, used = 0;
    esp_spiffs_info("storage", &total, &used);
    ESP_LOGI(TAG, "SPIFFS: total=%zu, used=%zu", total, used);
    return ESP_OK;
}

/* ── Server Start/Stop ─────────────────────────────── */

esp_err_t web_server_start(void)
{
    esp_err_t ret = init_spiffs();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "SPIFFS init failed, static files won't be served");
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.uri_match_fn = httpd_uri_match_wildcard;
    config.max_uri_handlers = 20;
    config.stack_size = 8192;
    config.lru_purge_enable = true;
    config.max_open_sockets = 7;

    ret = httpd_start(&s_server, &config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Register API + WebSocket handlers first (more specific routes) */
    api_handlers_register(s_server);
    ws_handler_register(s_server);

    /* Wildcard static file handler last (catch-all) */
    httpd_uri_t static_uri = {
        .uri = "/*",
        .method = HTTP_GET,
        .handler = static_file_handler,
    };
    httpd_register_uri_handler(s_server, &static_uri);

    ESP_LOGI(TAG, "HTTP server started");
    return ESP_OK;
}

void web_server_stop(void)
{
    if (s_server) {
        httpd_stop(s_server);
        s_server = NULL;
        ESP_LOGI(TAG, "HTTP server stopped");
    }
}

httpd_handle_t web_server_get_handle(void)
{
    return s_server;
}
