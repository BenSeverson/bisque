cmake_minimum_required(VERSION 3.16)
project(bisque_host_tests C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Treat warnings strictly — host tests are the place to catch sloppy edits
# before they hit the firmware build.
add_compile_options(-Wall -Wextra -Wno-unused-parameter -Wno-unused-function -Wno-missing-field-initializers)

include(CTest)
enable_testing()

set(ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../..)

# ── Unity (vendored, MIT) ───────────────────────────────────────────────
add_library(unity STATIC unity/unity.c)
target_include_directories(unity PUBLIC unity)

# ── ESP-IDF host stubs ──────────────────────────────────────────────────
# In-memory NVS, virtual esp_timer clock, no-op esp_log. Tests that need to
# manipulate the clock or wipe NVS call host_clock_set / nvs_reset_for_test
# (declared in the headers).
add_library(host_stubs STATIC
    stubs/esp_timer.c
    stubs/nvs.c
    stubs/freertos_stub.c
    stubs/thermocouple_host.c
    stubs/safety_host.c
    stubs/history_host.c)
target_include_directories(host_stubs PUBLIC
    stubs
    ${ROOT}/components/thermocouple/include
    ${ROOT}/components/safety/include
    ${ROOT}/components/history/include)

# Convenience: every test gets unity + host_stubs + the component include
# directories.
add_library(test_common INTERFACE)
target_link_libraries(test_common INTERFACE unity host_stubs m)
target_include_directories(test_common INTERFACE
    ${ROOT}/components/app_config/include
    ${ROOT}/components/firing_engine/include
    ${ROOT}/components/cone_table/include
    ${ROOT}/components/pid_control/include)

function(add_host_test name)
    cmake_parse_arguments(T "" "" "SOURCES" ${ARGN})
    add_executable(${name} ${T_SOURCES})
    target_link_libraries(${name} PRIVATE test_common)
    add_test(NAME ${name} COMMAND ${name})
endfunction()

# ── Tests ───────────────────────────────────────────────────────────────

# firing_helpers — pure helpers extracted from firing_engine.c.
add_host_test(test_firing_helpers
    SOURCES test_firing_helpers.c ${ROOT}/components/firing_engine/firing_helpers.c)

# cone_table — profile generation for every cone × speed × {preheat, slow_cool}.
add_host_test(test_cone_table
    SOURCES test_cone_table.c ${ROOT}/components/cone_table/cone_table.c)

# pid_control — pid_compute properties, NVS roundtrip, autotune state machine.
add_host_test(test_pid
    SOURCES test_pid.c ${ROOT}/components/pid_control/pid_control.c)

# firing_scenarios — accelerated end-to-end firings driven through firing_tick.
# Compiles the real firing_engine.c against host stubs of safety, thermocouple,
# history, FreeRTOS, NVS, and esp_timer.
add_host_test(test_firing_scenarios
    SOURCES test_firing_scenarios.c
            scenario_helpers.c
            plant.c
            ${ROOT}/components/firing_engine/firing_engine.c
            ${ROOT}/components/firing_engine/firing_helpers.c
            ${ROOT}/components/pid_control/pid_control.c)
