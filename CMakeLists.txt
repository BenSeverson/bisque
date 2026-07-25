cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "components")

# Build the sdkconfig defaults list. Order matters — later files win.
#  1. sdkconfig.defaults                 — committed base
#  2. sdkconfig.defaults.debug           — only when BISQUE_PROFILE=debug;
#                                          enables -Og + LVGL FPS/heap overlays
#  3. sdkconfig.defaults.local           — untracked per-developer overrides
#                                          (e.g. Wi-Fi creds); included only
#                                          when it exists since IDF errors on
#                                          missing entries.
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults")
if("$ENV{BISQUE_PROFILE}" STREQUAL "debug")
    list(APPEND SDKCONFIG_DEFAULTS "sdkconfig.defaults.debug")
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/sdkconfig.defaults.local")
    list(APPEND SDKCONFIG_DEFAULTS "sdkconfig.defaults.local")
endif()

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

# spiffs_data/www/ holds the web UI bundle, which build.sh generates and
# .gitignore excludes — so a fresh clone or git worktree has no directory at
# all and spiffsgen.py aborts ("given base directory ... does not exist")
# before a single source file compiles. Create it so firmware-only builds work
# in a clean checkout; the storage image is then simply empty and the device
# serves no web UI until ./build.sh (or `make web gzip`) populates it.
set(BISQUE_WWW_DIR "${CMAKE_CURRENT_SOURCE_DIR}/spiffs_data/www")
if(NOT EXISTS "${BISQUE_WWW_DIR}")
    message(STATUS "spiffs_data/www not found — building an empty storage partition. "
                   "Run ./build.sh (or 'make web gzip') to bundle the web UI.")
    file(MAKE_DIRECTORY "${BISQUE_WWW_DIR}")
endif()

spiffs_create_partition_image(storage spiffs_data/www FLASH_IN_PROJECT)
