idf_component_register(
    SRCS "ota_manager.c" "ota_confirm.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_client app_update esp-tls mbedtls cjson firing_engine
)
