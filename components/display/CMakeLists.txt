idf_component_register(
    SRCS "display_init.c"
         "display_task.c"
         "ui_screen_home.c"
         "ui_screen_chart.c"
         "ui_screen_profiles.c"
         "ui_screen_firing.c"
    INCLUDE_DIRS "include" "."
    REQUIRES esp_driver_gpio esp_driver_spi esp_lcd esp_timer firing_engine thermocouple safety history app_config
)
