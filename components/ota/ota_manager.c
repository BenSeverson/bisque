#include "ota_manager.h"

#include <stdio.h>
#include <string.h>
#include <strings.h>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/md.h"
#include "sdkconfig.h"

static const char *TAG = "ota";

#define MANIFEST_BUF_MAX 1024

static ota_progress_cb_t s_progress_cb = NULL;
static volatile bool s_busy = false;
static ota_manifest_t s_pending;

void ota_set_progress_cb(ota_progress_cb_t cb)
{
    s_progress_cb = cb;
}

const char *ota_current_version(void)
{
    return esp_app_get_description()->version;
}

bool ota_is_busy(void)
{
    return s_busy;
}

static void report(ota_phase_t phase, int percent, const char *err)
{
    if (s_progress_cb) {
        s_progress_cb(phase, percent, err);
    }
}

/* ── Manifest fetch ─────────────────────────────────── */

typedef struct {
    char buf[MANIFEST_BUF_MAX];
    int len;
} manifest_accum_t;

static esp_err_t manifest_http_event(esp_http_client_event_t *evt)
{
    if (evt->event_id == HTTP_EVENT_ON_DATA) {
        /* Skip bodies of 3xx redirect hops; only accumulate the final 200. */
        if (esp_http_client_get_status_code(evt->client) != 200) {
            return ESP_OK;
        }
        manifest_accum_t *a = (manifest_accum_t *)evt->user_data;
        int space = MANIFEST_BUF_MAX - 1 - a->len;
        int n = (evt->data_len < space) ? evt->data_len : space;
        if (n > 0) {
            memcpy(a->buf + a->len, evt->data, n);
            a->len += n;
        }
    }
    return ESP_OK;
}

static esp_err_t parse_manifest(const char *json, ota_manifest_t *out)
{
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        return ESP_FAIL;
    }

    memset(out, 0, sizeof(*out));
    esp_err_t err = ESP_FAIL;

    cJSON *version = cJSON_GetObjectItem(root, "version");
    cJSON *url = cJSON_GetObjectItem(root, "url");
    cJSON *sha256 = cJSON_GetObjectItem(root, "sha256");
    cJSON *size = cJSON_GetObjectItem(root, "size");
    cJSON *notes = cJSON_GetObjectItem(root, "notes");

    if (cJSON_IsString(version) && cJSON_IsString(url)) {
        strlcpy(out->version, version->valuestring, sizeof(out->version));
        strlcpy(out->url, url->valuestring, sizeof(out->url));
        if (cJSON_IsString(sha256)) {
            strlcpy(out->sha256, sha256->valuestring, sizeof(out->sha256));
        }
        if (cJSON_IsNumber(size)) {
            out->size = (uint32_t)size->valuedouble;
        }
        if (cJSON_IsString(notes)) {
            strlcpy(out->notes, notes->valuestring, sizeof(out->notes));
        }
        err = ESP_OK;
    }

    cJSON_Delete(root);
    return err;
}

esp_err_t ota_check(ota_manifest_t *out_manifest)
{
    if (!out_manifest) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_busy) {
        return ESP_ERR_INVALID_STATE;
    }
    s_busy = true;

    manifest_accum_t *accum = calloc(1, sizeof(manifest_accum_t));
    if (!accum) {
        s_busy = false;
        return ESP_ERR_NO_MEM;
    }

    esp_http_client_config_t cfg = {
        .url = CONFIG_OTA_MANIFEST_URL,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = CONFIG_OTA_CONNECT_TIMEOUT_MS,
        .event_handler = manifest_http_event,
        .user_data = accum,
        .keep_alive_enable = false,
    };

    esp_err_t err = ESP_FAIL;
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (client) {
        esp_err_t perr = esp_http_client_perform(client);
        int status = esp_http_client_get_status_code(client);
        esp_http_client_cleanup(client);

        if (perr == ESP_OK && status == 200 && accum->len > 0) {
            accum->buf[accum->len] = '\0';
            err = parse_manifest(accum->buf, out_manifest);
            if (err != ESP_OK) {
                ESP_LOGW(TAG, "Manifest parse failed");
            }
        } else {
            ESP_LOGW(TAG, "Manifest fetch failed (perr=%s status=%d)", esp_err_to_name(perr), status);
        }
    }

    free(accum);
    s_busy = false;
    return err;
}

/* ── Install ────────────────────────────────────────── */

typedef struct {
    esp_ota_handle_t ota_handle;
    mbedtls_md_context_t md;
    int written;
    int total;
    int last_pct;
    esp_err_t err;
} install_ctx_t;

static esp_err_t install_http_event(esp_http_client_event_t *evt)
{
    if (evt->event_id != HTTP_EVENT_ON_DATA) {
        return ESP_OK;
    }
    /* Ignore bodies of 3xx redirect hops; only the final 200 is the image. */
    if (esp_http_client_get_status_code(evt->client) != 200) {
        return ESP_OK;
    }

    install_ctx_t *ctx = (install_ctx_t *)evt->user_data;
    if (ctx->err != ESP_OK) {
        return ESP_FAIL;
    }

    if (esp_ota_write(ctx->ota_handle, evt->data, evt->data_len) != ESP_OK) {
        ctx->err = ESP_FAIL;
        return ESP_FAIL;
    }
    mbedtls_md_update(&ctx->md, (const unsigned char *)evt->data, evt->data_len);
    ctx->written += evt->data_len;

    if (ctx->total > 0) {
        int pct = (int)((int64_t)ctx->written * 100 / ctx->total);
        if (pct > 100) {
            pct = 100;
        }
        if (pct != ctx->last_pct) {
            ctx->last_pct = pct;
            report(OTA_PHASE_DOWNLOAD, pct, NULL);
        }
    }
    return ESP_OK;
}

static void install_task(void *arg)
{
    (void)arg;
    ota_manifest_t m = s_pending;
    install_ctx_t ctx = {0};
    esp_err_t result = ESP_FAIL;
    const char *errmsg = "install failed";

    report(OTA_PHASE_DOWNLOAD, 0, NULL);

    const esp_partition_t *part = esp_ota_get_next_update_partition(NULL);
    if (!part) {
        errmsg = "no update partition";
        goto finish;
    }

    ctx.total = (int)m.size;
    ctx.last_pct = -1;
    ctx.err = ESP_OK;

    if (esp_ota_begin(part, OTA_WITH_SEQUENTIAL_WRITES, &ctx.ota_handle) != ESP_OK) {
        errmsg = "ota begin failed";
        goto finish;
    }

    mbedtls_md_init(&ctx.md);
    if (mbedtls_md_setup(&ctx.md, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0) != 0) {
        esp_ota_abort(ctx.ota_handle);
        mbedtls_md_free(&ctx.md);
        errmsg = "sha init failed";
        goto finish;
    }
    mbedtls_md_starts(&ctx.md);

    esp_http_client_config_t cfg = {
        .url = m.url,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = CONFIG_OTA_CONNECT_TIMEOUT_MS,
        .event_handler = install_http_event,
        .user_data = &ctx,
        .buffer_size = 4096,
        .keep_alive_enable = false,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    esp_err_t perr = client ? esp_http_client_perform(client) : ESP_FAIL;
    int status = client ? esp_http_client_get_status_code(client) : 0;
    if (client) {
        esp_http_client_cleanup(client);
    }

    if (perr != ESP_OK || status != 200 || ctx.err != ESP_OK || ctx.written == 0) {
        esp_ota_abort(ctx.ota_handle);
        mbedtls_md_free(&ctx.md);
        errmsg = "download failed";
        goto finish;
    }

    unsigned char digest[32];
    mbedtls_md_finish(&ctx.md, digest);
    mbedtls_md_free(&ctx.md);

    char hex[65];
    for (int i = 0; i < 32; i++) {
        sprintf(hex + i * 2, "%02x", digest[i]);
    }
    hex[64] = '\0';

    if (m.sha256[0] != '\0' && strcasecmp(hex, m.sha256) != 0) {
        esp_ota_abort(ctx.ota_handle);
        ESP_LOGE(TAG, "SHA256 mismatch: got %s want %s", hex, m.sha256);
        errmsg = "sha256 mismatch";
        goto finish;
    }

    /* esp_ota_end() frees the handle on both success and failure. */
    if (esp_ota_end(ctx.ota_handle) != ESP_OK) {
        errmsg = "image verification failed";
        goto finish;
    }
    if (esp_ota_set_boot_partition(part) != ESP_OK) {
        errmsg = "set boot partition failed";
        goto finish;
    }
    result = ESP_OK;

finish:
    if (result == ESP_OK) {
        ESP_LOGI(TAG, "OTA complete, rebooting into %s", m.version);
        report(OTA_PHASE_COMPLETE, 100, NULL);
        vTaskDelay(pdMS_TO_TICKS(1500));
        esp_restart();
    } else {
        ESP_LOGE(TAG, "OTA failed: %s", errmsg);
        report(OTA_PHASE_ERROR, 0, errmsg);
        s_busy = false;
        vTaskDelete(NULL);
    }
}

esp_err_t ota_install_from_manifest(const ota_manifest_t *manifest)
{
    if (!manifest || manifest->url[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_busy) {
        return ESP_ERR_INVALID_STATE;
    }
    s_busy = true;
    s_pending = *manifest;

    BaseType_t ok = xTaskCreate(install_task, "ota_install", 8192, NULL, 5, NULL);
    if (ok != pdPASS) {
        s_busy = false;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
