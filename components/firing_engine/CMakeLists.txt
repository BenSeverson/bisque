idf_component_register(
    SRCS "firing_engine.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos nvs_flash thermocouple pid_control safety history
)
