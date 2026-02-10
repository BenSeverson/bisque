idf_component_register(
    SRCS "web_server.c" "api_handlers.c" "ws_handler.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server spiffs json firing_engine thermocouple safety pid_control
)
