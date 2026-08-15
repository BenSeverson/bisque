#pragma once

#include <stdint.h>
#include "esp_err.h"
#include "driver/spi_master.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Fault flag bits.
 *
 * TC_FAULT_SHORT_VCC is vestigial on rev B hardware: the MAX31855 detected
 * short-to-GND and short-to-VCC as separate conditions, and the MAX31856 does
 * not — its OVUV bit covers both and maps onto TC_FAULT_SHORT_GND. The bit is
 * kept because it is part of the REST and WebSocket contract; nothing sets it.
 * See max31856_decode_faults() in max31856_regs.h. */
#define TC_FAULT_OPEN_CIRCUIT (1 << 0)
#define TC_FAULT_SHORT_GND    (1 << 1)
#define TC_FAULT_SHORT_VCC    (1 << 2)
/* The hot junction is outside the thermocouple type's measurable range, so the
 * reported temperature is a clamp, not a measurement. This is a fault because
 * the clamp sits *below* APP_HARDWARE_MAX_TEMP_C: without it, a kiln past
 * 1372 °C on a K-type probe reads a steady 1372 °C forever and no over-temp
 * comparison can ever trip. See max31856_decode_faults(). */
#define TC_FAULT_OUT_OF_RANGE (1 << 3)

typedef struct {
    float temperature_c;   /* Thermocouple temperature in Celsius */
    float internal_temp_c; /* Cold-junction (internal) temperature */
    uint8_t fault;         /* Bitfield: TC_FAULT_* flags, 0 = no fault */
    int64_t timestamp_us;  /* esp_timer_get_time() when reading was taken */
} thermocouple_reading_t;

/**
 * Initialize the MAX31856 thermocouple on the given SPI host, writing its
 * configuration registers (K type, 4-sample averaging, continuous conversion,
 * 60 Hz rejection) and reading CR0 back to confirm the part is actually there.
 * The SPI bus must already be initialized.
 *
 * @param host  SPI host (e.g. SPI2_HOST)
 * @param cs_pin  GPIO for chip select
 * @return ESP_OK on success; ESP_ERR_NOT_FOUND if CR0 does not read back what
 *         was written, which is what an absent or miswired part looks like
 */
esp_err_t thermocouple_init(spi_host_device_t host, int cs_pin);

/**
 * Read the MAX31856's fault-status, cold-junction and linearized-temperature
 * registers and populate `out`. On any fault both temperatures are reported as
 * 0 °C — firing_engine's PID gate depends on that.
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
