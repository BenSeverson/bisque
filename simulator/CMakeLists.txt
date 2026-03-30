cmake_minimum_required(VERSION 3.16)
project(bisque_sim C)

set(CMAKE_C_STANDARD 11)

# SDL2
find_package(PkgConfig REQUIRED)
pkg_check_modules(SDL2 REQUIRED sdl2)

# LVGL source tree
set(LVGL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../managed_components/lvgl__lvgl)

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

# Bisque UI screen sources
set(BISQUE_DISPLAY_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../components/display)
set(BISQUE_UI_SRC
    ${BISQUE_DISPLAY_DIR}/ui_screen_home.c
    ${BISQUE_DISPLAY_DIR}/ui_screen_chart.c
    ${BISQUE_DISPLAY_DIR}/ui_screen_profiles.c
    ${BISQUE_DISPLAY_DIR}/ui_screen_firing.c
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
    # SDL2
    ${SDL2_INCLUDE_DIRS}
)

target_link_directories(bisque_sim PRIVATE ${SDL2_LIBRARY_DIRS})
target_link_libraries(bisque_sim ${SDL2_LIBRARIES} pthread m)
target_compile_options(bisque_sim PRIVATE ${SDL2_CFLAGS_OTHER} -Wno-unused-function)
