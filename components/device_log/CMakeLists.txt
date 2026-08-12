idf_component_register(
    SRCS "device_log.c" "log_sink.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos esp_common
)
