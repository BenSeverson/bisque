idf_component_register(
    SRCS "display_init.c"
         "display_task.c"
         "dashboard.c"
         "modal.c"
         "modal_profile_picker.c"
         "modal_action_menu.c"
    INCLUDE_DIRS "include" "."
    REQUIRES esp_driver_gpio esp_driver_spi esp_lcd esp_timer firing_engine thermocouple safety history app_config
)
