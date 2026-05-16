/* Stub for ESP-IDF esp_app_desc.h — the simulator has no app descriptor, so
 * splash.c gets a fixed version string. Hardcoded (rather than derived from
 * git) so the splash screenshot stays byte-reproducible for the --diff check.
 * Keep this in sync with the latest release tag. */
#pragma once

typedef struct {
    char version[32];
} esp_app_desc_t;

static inline const esp_app_desc_t *esp_app_get_description(void)
{
    /* Mirrors PROJECT_VER: scripts/version.sh emits git-describe of v* tags,
     * so the string carries its own leading 'v'. */
    static const esp_app_desc_t desc = {.version = "v2.0.0"};
    return &desc;
}
