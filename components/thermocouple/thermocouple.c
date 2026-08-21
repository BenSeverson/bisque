#include "thermocouple.h"
#include "max31856_regs.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "thermocouple";

static spi_device_handle_t s_spi_dev;
static portMUX_TYPE s_reading_mux = portMUX_INITIALIZER_UNLOCKED;
static thermocouple_reading_t s_latest_reading;

/* The longest transfer this driver makes is the three-byte linearized-temperature
 * read plus its address byte. Staying inside four bytes lets both helpers use the
 * transaction's own tx_data/rx_data, which the SPI driver keeps word-aligned — a
 * plain stack buffer carries no such guarantee, and this bus is created with
 * SPI_DMA_CH_AUTO, where an unaligned rx buffer is rejected rather than fixed up. */
#define MAX31856_MAX_DATA_BYTES 3

static esp_err_t reg_write(uint8_t reg, uint8_t val)
{
    spi_transaction_t txn = {
        .flags = SPI_TRANS_USE_TXDATA,
        .length = 16,
        .tx_data = {reg | MAX31856_WRITE_BIT, val},
    };
    return spi_device_transmit(s_spi_dev, &txn);
}

/* Reads `n` bytes starting at `reg`. The address auto-increments inside one
 * chip-select, which is what the datasheet requires for the multi-byte
 * temperature registers: "All three bytes should be read as a multibyte
 * transfer to ensure all are from the same data update" (p. 13). Reading them
 * one at a time would let a conversion land mid-value. */
static esp_err_t reg_read(uint8_t reg, uint8_t *out, size_t n)
{
    if (n == 0 || n > MAX31856_MAX_DATA_BYTES) {
        return ESP_ERR_INVALID_SIZE;
    }

    spi_transaction_t txn = {
        .flags = SPI_TRANS_USE_TXDATA | SPI_TRANS_USE_RXDATA,
        .length = 8 * (n + 1),
        .tx_data = {reg},
    };

    esp_err_t ret = spi_device_transmit(s_spi_dev, &txn);
    if (ret == ESP_OK) {
        memcpy(out, txn.rx_data + 1, n); /* byte 0 is the address phase */
    }
    return ret;
}

esp_err_t thermocouple_init(spi_host_device_t host, int cs_pin)
{
    spi_device_interface_config_t dev_cfg = {
        .clock_speed_hz = 1 * 1000 * 1000, /* the part rates 5 MHz; 1 MHz keeps
                                              margin on the bus it shares with
                                              the display and its loom */
        .mode = 1,                         /* CPOL=0, CPHA=1. The datasheet fixes
                                              CPHA at 1 and leaves CPOL free, so
                                              mode 3 would work equally well. */
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

    /* CR0 is written twice, and the split is not redundant: the datasheet
     * forbids changing the notch-filter frequency outside "Normally Off" mode
     * (p. 19). CR0_SETUP settles the filter and open-circuit bits while CMODE is
     * still clear; CR0_INIT then starts continuous conversion. */
    esp_err_t cfg = reg_write(MAX31856_REG_CR0, MAX31856_CR0_SETUP);
    if (cfg == ESP_OK) {
        cfg = reg_write(MAX31856_REG_CR1, MAX31856_CR1_INIT);
    }
    if (cfg == ESP_OK) {
        cfg = reg_write(MAX31856_REG_MASK, MAX31856_MASK_INIT);
    }
    if (cfg == ESP_OK) {
        cfg = reg_write(MAX31856_REG_CR0, MAX31856_CR0_INIT);
    }

    /* Read CR0 back. An absent or miswired part clocks back 0x00 or 0xFF
     * rather than what we just wrote, and a driver that cannot tell those
     * apart reports 0 C forever — which firing_engine treats as a fault only
     * after APP_TEMP_FAULT_TIMEOUT_MS, with the element on the whole time. */
    uint8_t cr0 = 0;
    if (cfg == ESP_OK) {
        cfg = reg_read(MAX31856_REG_CR0, &cr0, 1);
    }
    if (cfg != ESP_OK) {
        ESP_LOGE(TAG, "MAX31856 config failed: %s", esp_err_to_name(cfg));
        spi_bus_remove_device(s_spi_dev);
        s_spi_dev = NULL;
        return cfg;
    }
    if (cr0 != MAX31856_CR0_INIT) {
        ESP_LOGE(TAG, "MAX31856 not responding: CR0 read back 0x%02x, expected 0x%02x", cr0, MAX31856_CR0_INIT);
        spi_bus_remove_device(s_spi_dev);
        s_spi_dev = NULL;
        return ESP_ERR_NOT_FOUND;
    }

    /* Initialize cached reading */
    memset(&s_latest_reading, 0, sizeof(s_latest_reading));
    s_latest_reading.temperature_c = 0.0f;

    ESP_LOGI(TAG, "MAX31856 initialized on CS pin %d", cs_pin);
    return ESP_OK;
}

esp_err_t thermocouple_read(thermocouple_reading_t *out)
{
    uint8_t sr = 0, cj[2] = {0}, tc[3] = {0};

    esp_err_t ret = reg_read(MAX31856_REG_SR, &sr, 1);
    if (ret == ESP_OK) {
        ret = reg_read(MAX31856_REG_CJTH, cj, sizeof(cj));
    }
    if (ret == ESP_OK) {
        ret = reg_read(MAX31856_REG_LTCBH, tc, sizeof(tc));
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "SPI read failed: %s", esp_err_to_name(ret));
        return ret;
    }

    out->timestamp_us = esp_timer_get_time();
    out->fault = max31856_decode_faults(sr);

    /* Zeroing the temperature on a fault is what firing_engine's PID gate
     * expects — see tests/host/test_firing_scenarios.c. Reporting the last
     * good value instead would look calmer and be far worse. */
    if (out->fault != 0) {
        out->temperature_c = 0.0f;
        out->internal_temp_c = 0.0f;
        ESP_LOGW(TAG, "Thermocouple fault: SR=0x%02x -> 0x%02x", sr, out->fault);
        return ESP_OK;
    }

    out->temperature_c = max31856_decode_tc(tc);
    out->internal_temp_c = max31856_decode_cj(cj);

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
                ESP_LOGD(TAG, "Temp: %.1f°C (internal: %.1f°C)", reading.temperature_c, reading.internal_temp_c);
            }
        }
        /* 250 ms comfortably outstrips the part's own cadence: auto-mode
         * conversions take ~132 ms typ / ~140 ms max with 4-sample averaging at
         * 60 Hz, so every poll sees a fresh conversion. */
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(250));
    }
}
