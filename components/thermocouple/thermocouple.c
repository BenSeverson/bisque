#include "thermocouple.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "thermocouple";

static spi_device_handle_t s_spi_dev;
static portMUX_TYPE s_reading_mux = portMUX_INITIALIZER_UNLOCKED;
static thermocouple_reading_t s_latest_reading;

esp_err_t thermocouple_init(spi_host_device_t host, int cs_pin)
{
    spi_device_interface_config_t dev_cfg = {
        .clock_speed_hz = 1 * 1000 * 1000,  /* MAX31855 supports up to 5 MHz */
        .mode = 0,                            /* SPI mode 0 */
        .spics_io_num = cs_pin,
        .queue_size = 1,
        .command_bits = 0,
        .address_bits = 0,
    };

    esp_err_t ret = spi_bus_add_device(host, &dev_cfg, &s_spi_dev);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to add SPI device: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Initialize cached reading */
    memset(&s_latest_reading, 0, sizeof(s_latest_reading));
    s_latest_reading.temperature_c = 0.0f;

    ESP_LOGI(TAG, "MAX31855 initialized on CS pin %d", cs_pin);
    return ESP_OK;
}

esp_err_t thermocouple_read(thermocouple_reading_t *out)
{
    uint8_t rx_buf[4] = {0};
    spi_transaction_t txn = {
        .length = 32,
        .rx_buffer = rx_buf,
    };

    esp_err_t ret = spi_device_transmit(s_spi_dev, &txn);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "SPI read failed: %s", esp_err_to_name(ret));
        return ret;
    }

    uint32_t raw = ((uint32_t)rx_buf[0] << 24) |
                   ((uint32_t)rx_buf[1] << 16) |
                   ((uint32_t)rx_buf[2] << 8)  |
                   (uint32_t)rx_buf[3];

    out->timestamp_us = esp_timer_get_time();
    out->fault = 0;

    /* Check fault bit (D16) */
    if (raw & (1 << 16)) {
        if (raw & (1 << 0)) out->fault |= TC_FAULT_OPEN_CIRCUIT;
        if (raw & (1 << 1)) out->fault |= TC_FAULT_SHORT_GND;
        if (raw & (1 << 2)) out->fault |= TC_FAULT_SHORT_VCC;
        out->temperature_c = 0.0f;
        out->internal_temp_c = 0.0f;
        ESP_LOGW(TAG, "Thermocouple fault: 0x%02x", out->fault);
        return ESP_OK;
    }

    /* Thermocouple temperature: bits[31:18], 14-bit signed, 0.25°C resolution */
    int16_t tc_raw = (int16_t)((raw >> 18) & 0x3FFF);
    if (tc_raw & 0x2000) {
        tc_raw |= 0xC000;  /* Sign extend */
    }
    out->temperature_c = tc_raw * 0.25f;

    /* Internal (cold junction) temperature: bits[15:4], 12-bit signed, 0.0625°C resolution */
    int16_t int_raw = (int16_t)((raw >> 4) & 0x0FFF);
    if (int_raw & 0x0800) {
        int_raw |= 0xF000;  /* Sign extend */
    }
    out->internal_temp_c = int_raw * 0.0625f;

    return ESP_OK;
}

void thermocouple_get_latest(thermocouple_reading_t *out)
{
    portENTER_CRITICAL(&s_reading_mux);
    *out = s_latest_reading;
    portEXIT_CRITICAL(&s_reading_mux);
}

void temp_read_task(void *param)
{
    (void)param;
    thermocouple_reading_t reading;
    TickType_t last_wake = xTaskGetTickCount();

    ESP_LOGI(TAG, "temp_read_task started");

    for (;;) {
        if (thermocouple_read(&reading) == ESP_OK) {
            portENTER_CRITICAL(&s_reading_mux);
            s_latest_reading = reading;
            portEXIT_CRITICAL(&s_reading_mux);

            if (reading.fault == 0) {
                ESP_LOGD(TAG, "Temp: %.1f°C (internal: %.1f°C)",
                         reading.temperature_c, reading.internal_temp_c);
            }
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(250));
    }
}
