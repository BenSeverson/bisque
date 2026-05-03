cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "components")

# Layer an untracked sdkconfig.defaults.local on top of sdkconfig.defaults so
# local-only settings (e.g. Wi-Fi creds) persist without being committed.
# Missing files are tolerated by ESP-IDF.
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults;sdkconfig.defaults.local")

# Derive PROJECT_VER from scripts/version.sh (git describe) unless the caller
# already exported BISQUE_VERSION. ESP-IDF embeds PROJECT_VER into esp_app_desc.
if(DEFINED ENV{BISQUE_VERSION} AND NOT "$ENV{BISQUE_VERSION}" STREQUAL "")
    set(PROJECT_VER "$ENV{BISQUE_VERSION}")
else()
    execute_process(
        COMMAND "${CMAKE_CURRENT_SOURCE_DIR}/scripts/version.sh"
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
        OUTPUT_VARIABLE PROJECT_VER
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endif()

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
