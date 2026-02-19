idf_component_register(
    SRCS "main.c"
    REQUIRES
        app_config
        thermocouple
        pid_control
        firing_engine
        web_server
        display
        safety
        wifi_manager
        history
        mdns
        esp_netif
        lwip
)
