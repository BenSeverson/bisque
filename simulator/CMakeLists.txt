cmake_minimum_required(VERSION 3.16)
project(bisque_sim C)

set(CMAKE_C_STANDARD 11)

# SDL2
find_package(PkgConfig REQUIRED)
pkg_check_modules(SDL2 REQUIRED sdl2)

# LVGL source tree.
#
# Preferred: the copy the ESP-IDF component manager installs during a firmware
# build, so the simulator links exactly what the firmware links.
#
# Fallback: a standalone clone under simulator/.lvgl, used when there is no
# firmware build in the tree (CI's ui-screenshots job runs on its own runner,
# and the SessionStart hook provisions the simulator before ESP-IDF has ever
# been invoked).
#
# The fallback is NOT allowed to live in managed_components/ even though the
# directory is otherwise identical: that directory belongs to the component
# manager, which refuses to build against any component there lacking the
# .component_hash it writes itself —
#
#   ERROR: File .component_hash or CHECKSUMS.json for component "lvgl/lvgl" in
#   the managed components directory does not exist or cannot be parsed.
#
# so a plain `git clone` into it makes `idf.py build` fail outright.
set(LVGL_MANAGED ${CMAKE_CURRENT_SOURCE_DIR}/../managed_components/lvgl__lvgl)
set(LVGL_STANDALONE ${CMAKE_CURRENT_SOURCE_DIR}/.lvgl)
if(EXISTS ${LVGL_MANAGED}/lvgl.h)
    set(LVGL_DIR ${LVGL_MANAGED})
elseif(EXISTS ${LVGL_STANDALONE}/lvgl.h)
    set(LVGL_DIR ${LVGL_STANDALONE})
else()
    message(FATAL_ERROR
        "LVGL sources not found. Run .claude/hooks/install-sim-deps.sh, or build "
        "the firmware once so the component manager populates managed_components/.")
endif()
message(STATUS "Simulator LVGL source: ${LVGL_DIR}")

# Tell LVGL to use our lv_conf.h
add_definitions(-DLV_CONF_INCLUDE_SIMPLE)

# Collect LVGL sources (core + drivers we need)
file(GLOB_RECURSE LVGL_CORE_SRC
    ${LVGL_DIR}/src/core/*.c
    ${LVGL_DIR}/src/display/*.c
    ${LVGL_DIR}/src/draw/*.c
    ${LVGL_DIR}/src/font/*.c
    ${LVGL_DIR}/src/indev/*.c
    ${LVGL_DIR}/src/layouts/*.c
    ${LVGL_DIR}/src/libs/*.c
    ${LVGL_DIR}/src/lv_init.c
    ${LVGL_DIR}/src/misc/*.c
    ${LVGL_DIR}/src/osal/*.c
    ${LVGL_DIR}/src/stdlib/*.c
    ${LVGL_DIR}/src/tick/*.c
    ${LVGL_DIR}/src/themes/*.c
    ${LVGL_DIR}/src/widgets/*.c
    ${LVGL_DIR}/src/others/*.c
)

# SDL driver sources
file(GLOB LVGL_SDL_SRC ${LVGL_DIR}/src/drivers/sdl/*.c)

# Bisque UI sources (same files the firmware compiles)
set(BISQUE_DISPLAY_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../components/display)
set(BISQUE_UI_SRC
    ${BISQUE_DISPLAY_DIR}/dashboard.c
    ${BISQUE_DISPLAY_DIR}/modal.c
    ${BISQUE_DISPLAY_DIR}/modal_profile_picker.c
    ${BISQUE_DISPLAY_DIR}/modal_action_menu.c
    ${BISQUE_DISPLAY_DIR}/splash.c
    ${BISQUE_DISPLAY_DIR}/assets/flame_icon.c
    ${BISQUE_DISPLAY_DIR}/ui_widgets.c
    ${BISQUE_DISPLAY_DIR}/ui_theme.c
)

add_executable(bisque_sim
    main.c
    mock_esp.c
    ${LVGL_CORE_SRC}
    ${LVGL_SDL_SRC}
    ${BISQUE_UI_SRC}
)

target_include_directories(bisque_sim PRIVATE
    # Our lv_conf.h lives here
    ${CMAKE_CURRENT_SOURCE_DIR}
    # LVGL headers
    ${LVGL_DIR}/src
    ${LVGL_DIR}
    # Bisque component headers
    ${BISQUE_DISPLAY_DIR}
    ${BISQUE_DISPLAY_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../components/firing_engine/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../components/thermocouple/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../components/app_config/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../components/history/include
    # SDL2
    ${SDL2_INCLUDE_DIRS}
)

target_link_directories(bisque_sim PRIVATE ${SDL2_LIBRARY_DIRS})
target_link_libraries(bisque_sim ${SDL2_LIBRARIES} pthread m)
target_compile_options(bisque_sim PRIVATE ${SDL2_CFLAGS_OTHER} -Wno-unused-function)
