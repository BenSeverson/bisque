idf_component_register(
    SRCS "safety.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos esp_driver_gpio esp_driver_ledc thermocouple esp_timer app_config
)
