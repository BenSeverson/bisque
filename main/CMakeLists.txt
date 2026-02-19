idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "include"
    REQUIRES
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
