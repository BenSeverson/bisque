#pragma once

#include "esp_err.h"

/* Real ESP-IDF nvs_flash.h. Host stub just no-ops; nvs.h does the real work. */

static inline esp_err_t nvs_flash_init(void)
{
    return ESP_OK;
}

static inline esp_err_t nvs_flash_erase(void)
{
    return ESP_OK;
}
