#pragma once

/* Minimal stand-in so thermocouple.h compiles on host without the ESP-IDF
 * SPI driver. The host harness never makes SPI calls — temperature comes
 * from thermocouple_test_set() instead. */

typedef enum {
    SPI1_HOST = 1,
    SPI2_HOST = 2,
    SPI3_HOST = 3,
} spi_host_device_t;
