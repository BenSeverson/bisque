#include "nvs.h"
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#define MAX_ENTRIES   128
#define MAX_NS_LEN    16
#define MAX_KEY_LEN   16
#define MAX_VALUE_LEN 4096

typedef struct {
    bool used;
    char ns[MAX_NS_LEN];
    char key[MAX_KEY_LEN];
    uint8_t value[MAX_VALUE_LEN];
    size_t length;
} entry_t;

typedef struct {
    bool open;
    char ns[MAX_NS_LEN];
} handle_slot_t;

#define MAX_HANDLES 16

static entry_t s_entries[MAX_ENTRIES];
static handle_slot_t s_handles[MAX_HANDLES];

static entry_t *find_entry(const char *ns, const char *key)
{
    for (int i = 0; i < MAX_ENTRIES; i++) {
        if (s_entries[i].used && strcmp(s_entries[i].ns, ns) == 0 && strcmp(s_entries[i].key, key) == 0) {
            return &s_entries[i];
        }
    }
    return NULL;
}

static entry_t *find_or_create_entry(const char *ns, const char *key)
{
    entry_t *e = find_entry(ns, key);
    if (e) {
        return e;
    }
    for (int i = 0; i < MAX_ENTRIES; i++) {
        if (!s_entries[i].used) {
            s_entries[i].used = true;
            strncpy(s_entries[i].ns, ns, MAX_NS_LEN - 1);
            s_entries[i].ns[MAX_NS_LEN - 1] = '\0';
            strncpy(s_entries[i].key, key, MAX_KEY_LEN - 1);
            s_entries[i].key[MAX_KEY_LEN - 1] = '\0';
            s_entries[i].length = 0;
            return &s_entries[i];
        }
    }
    return NULL;
}

static const char *handle_ns(nvs_handle_t handle)
{
    if (handle == 0 || handle > MAX_HANDLES || !s_handles[handle - 1].open) {
        return NULL;
    }
    return s_handles[handle - 1].ns;
}

static bool namespace_has_entries(const char *ns)
{
    for (int i = 0; i < MAX_ENTRIES; i++) {
        if (s_entries[i].used && strcmp(s_entries[i].ns, ns) == 0) {
            return true;
        }
    }
    return false;
}

esp_err_t nvs_open(const char *name_space, nvs_open_mode_t mode, nvs_handle_t *out_handle)
{
    if (!name_space || !out_handle) {
        return ESP_ERR_INVALID_ARG;
    }
    /* Match real ESP-IDF: READONLY open on a never-written namespace fails
     * with ESP_ERR_NVS_NOT_FOUND. READWRITE creates the namespace lazily on
     * first write. */
    if (mode == NVS_READONLY && !namespace_has_entries(name_space)) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    for (int i = 0; i < MAX_HANDLES; i++) {
        if (!s_handles[i].open) {
            s_handles[i].open = true;
            strncpy(s_handles[i].ns, name_space, MAX_NS_LEN - 1);
            s_handles[i].ns[MAX_NS_LEN - 1] = '\0';
            *out_handle = (nvs_handle_t)(i + 1);
            return ESP_OK;
        }
    }
    return ESP_FAIL;
}

void nvs_close(nvs_handle_t handle)
{
    if (handle > 0 && handle <= MAX_HANDLES) {
        s_handles[handle - 1].open = false;
    }
}

esp_err_t nvs_commit(nvs_handle_t handle)
{
    (void)handle;
    return ESP_OK;
}

esp_err_t nvs_erase_key(nvs_handle_t handle, const char *key)
{
    const char *ns = handle_ns(handle);
    if (!ns) {
        return ESP_ERR_INVALID_ARG;
    }
    entry_t *e = find_entry(ns, key);
    if (!e) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    e->used = false;
    return ESP_OK;
}

static esp_err_t set_value(nvs_handle_t handle, const char *key, const void *value, size_t length)
{
    const char *ns = handle_ns(handle);
    if (!ns) {
        return ESP_ERR_INVALID_ARG;
    }
    if (length > MAX_VALUE_LEN) {
        return ESP_ERR_INVALID_SIZE;
    }
    entry_t *e = find_or_create_entry(ns, key);
    if (!e) {
        return ESP_ERR_NO_MEM;
    }
    memcpy(e->value, value, length);
    e->length = length;
    return ESP_OK;
}

static esp_err_t get_value(nvs_handle_t handle, const char *key, void *out, size_t expected)
{
    const char *ns = handle_ns(handle);
    if (!ns) {
        return ESP_ERR_INVALID_ARG;
    }
    entry_t *e = find_entry(ns, key);
    if (!e) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    if (e->length != expected) {
        return ESP_ERR_INVALID_SIZE;
    }
    memcpy(out, e->value, expected);
    return ESP_OK;
}

esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value)
{
    return set_value(handle, key, &value, sizeof(value));
}
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *out_value)
{
    return get_value(handle, key, out_value, sizeof(*out_value));
}
esp_err_t nvs_set_u32(nvs_handle_t handle, const char *key, uint32_t value)
{
    return set_value(handle, key, &value, sizeof(value));
}
esp_err_t nvs_get_u32(nvs_handle_t handle, const char *key, uint32_t *out_value)
{
    return get_value(handle, key, out_value, sizeof(*out_value));
}
esp_err_t nvs_set_i32(nvs_handle_t handle, const char *key, int32_t value)
{
    return set_value(handle, key, &value, sizeof(value));
}
esp_err_t nvs_get_i32(nvs_handle_t handle, const char *key, int32_t *out_value)
{
    return get_value(handle, key, out_value, sizeof(*out_value));
}

esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value)
{
    return set_value(handle, key, value, strlen(value) + 1);
}

esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *out_value, size_t *length)
{
    const char *ns = handle_ns(handle);
    if (!ns || !length) {
        return ESP_ERR_INVALID_ARG;
    }
    entry_t *e = find_entry(ns, key);
    if (!e) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    if (!out_value) {
        *length = e->length;
        return ESP_OK;
    }
    if (*length < e->length) {
        return ESP_ERR_INVALID_SIZE;
    }
    memcpy(out_value, e->value, e->length);
    *length = e->length;
    return ESP_OK;
}

esp_err_t nvs_set_blob(nvs_handle_t handle, const char *key, const void *value, size_t length)
{
    return set_value(handle, key, value, length);
}

esp_err_t nvs_get_blob(nvs_handle_t handle, const char *key, void *out_value, size_t *length)
{
    const char *ns = handle_ns(handle);
    if (!ns || !length) {
        return ESP_ERR_INVALID_ARG;
    }
    entry_t *e = find_entry(ns, key);
    if (!e) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    if (!out_value) {
        *length = e->length;
        return ESP_OK;
    }
    if (*length < e->length) {
        return ESP_ERR_INVALID_SIZE;
    }
    memcpy(out_value, e->value, e->length);
    *length = e->length;
    return ESP_OK;
}

const char *esp_err_to_name(esp_err_t code)
{
    switch (code) {
    case ESP_OK:
        return "ESP_OK";
    case ESP_FAIL:
        return "ESP_FAIL";
    case ESP_ERR_NO_MEM:
        return "ESP_ERR_NO_MEM";
    case ESP_ERR_INVALID_ARG:
        return "ESP_ERR_INVALID_ARG";
    case ESP_ERR_INVALID_STATE:
        return "ESP_ERR_INVALID_STATE";
    case ESP_ERR_INVALID_SIZE:
        return "ESP_ERR_INVALID_SIZE";
    case ESP_ERR_NOT_FOUND:
        return "ESP_ERR_NOT_FOUND";
    case ESP_ERR_NVS_NOT_FOUND:
        return "ESP_ERR_NVS_NOT_FOUND";
    default:
        return "UNKNOWN";
    }
}

void nvs_reset_for_test(void)
{
    memset(s_entries, 0, sizeof(s_entries));
    memset(s_handles, 0, sizeof(s_handles));
}
