idf_component_register(
    SRCS "safety.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos esp_driver_gpio thermocouple esp_timer
)
