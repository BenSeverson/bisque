#include "thermocouple_host.h"

#include "esp_timer.h"

static thermocouple_reading_t s_reading = {.temperature_c = 20.0f, .internal_temp_c = 20.0f, .fault = 0};

void thermocouple_test_set(float temperature_c, uint8_t fault)
{
    s_reading.temperature_c = temperature_c;
    s_reading.fault = fault;
    s_reading.timestamp_us = esp_timer_get_time();
}

void thermocouple_get_latest(thermocouple_reading_t *out)
{
    *out = s_reading;
}

/* Unused by tests but referenced via the real thermocouple.h. Keep them as
 * link-time satisfiers. */
esp_err_t thermocouple_init(spi_host_device_t host, int cs_pin)
{
    (void)host;
    (void)cs_pin;
    return ESP_OK;
}

esp_err_t thermocouple_read(thermocouple_reading_t *out)
{
    thermocouple_get_latest(out);
    return ESP_OK;
}

void temp_read_task(void *param)
{
    (void)param;
}
