cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

project(bisque)

# Strict warnings for project sources (does not affect ESP-IDF or LVGL)
list(APPEND common_warnings -Wall -Wextra -Werror -Wno-unused-parameter)
foreach(comp IN ITEMS
    cone_table display firing_engine history
    pid_control safety thermocouple web_server wifi_manager)
    idf_component_get_property(comp_lib ${comp} COMPONENT_LIB)
    target_compile_options(${comp_lib} PRIVATE ${common_warnings})
endforeach()
idf_component_get_property(main_lib main COMPONENT_LIB)
target_compile_options(${main_lib} PRIVATE ${common_warnings})

spiffs_create_partition_image(storage spiffs_data/www FLASH_IN_PROJECT)
