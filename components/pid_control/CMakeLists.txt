idf_component_register(
    SRCS "pid_control.c"
    INCLUDE_DIRS "include"
    REQUIRES nvs_flash esp_timer
)
