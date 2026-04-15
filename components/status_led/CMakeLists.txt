idf_component_register(
    SRCS "status_led.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos esp_driver_rmt app_config wifi_manager safety firing_engine
)
