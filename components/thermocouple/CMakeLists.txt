idf_component_register(
    SRCS "thermocouple.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_driver_spi esp_timer
)
