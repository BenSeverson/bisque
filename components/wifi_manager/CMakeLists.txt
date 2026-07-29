idf_component_register(
    SRCS "wifi_manager.c" "wifi_fallback.c" "wifi_retry_policy.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_event esp_netif esp_timer nvs_flash app_config
)
