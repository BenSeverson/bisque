idf_component_register(
    SRCS "web_server.c" "api_handlers.c" "ws_handler.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server spiffs cjson esp_driver_tsens firing_engine thermocouple safety pid_control
             cone_table history esp_http_client app_update app_config
)
