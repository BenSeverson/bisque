idf_component_register(
    SRCS "firing_history.c"
    INCLUDE_DIRS "include"
    REQUIRES spiffs cjson freertos
)
