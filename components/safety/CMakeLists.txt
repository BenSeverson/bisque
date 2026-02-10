idf_component_register(
    SRCS "safety.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos driver thermocouple esp_timer
)
