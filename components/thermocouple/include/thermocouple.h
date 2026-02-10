#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "driver/spi_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Fault flag bits */
#define TC_FAULT_OPEN_CIRCUIT  (1 << 0)
#define TC_FAULT_SHORT_GND     (1 << 1)
#define TC_FAULT_SHORT_VCC     (1 << 2)

typedef struct {
    float temperature_c;      /* Thermocouple temperature in Celsius */
    float internal_temp_c;    /* Cold-junction (internal) temperature */
    uint8_t fault;            /* Bitfield: TC_FAULT_* flags, 0 = no fault */
    int64_t timestamp_us;     /* esp_timer_get_time() when reading was taken */
} thermocouple_reading_t;

/**
 * Initialize the MAX31855 thermocouple on the given SPI host.
 * The SPI bus must already be initialized.
 *
 * @param host  SPI host (e.g. SPI2_HOST)
 * @param cs_pin  GPIO for chip select
 * @return ESP_OK on success
 */
esp_err_t thermocouple_init(spi_host_device_t host, int cs_pin);

/**
 * Perform a single SPI read of the MAX31855 and populate `out`.
 * Thread-safe: acquires internal spinlock.
 */
esp_err_t thermocouple_read(thermocouple_reading_t *out);

/**
 * Get the most recent cached reading (updated by temp_read_task).
 * Lock-free read protected by spinlock.
 */
void thermocouple_get_latest(thermocouple_reading_t *out);

/**
 * FreeRTOS task that reads the thermocouple at ~250ms intervals.
 * Pass NULL as parameter.
 */
void temp_read_task(void *param);

#ifdef __cplusplus
}
#endif
