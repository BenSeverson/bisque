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

# ── cJSON (fetched at configure time, MIT) ──────────────────────────────
# Espressif's component registry pins a version like '1.7.19~2' — the
# trailing '~N' is their downstream patch counter on top of upstream
# 1.7.19. The host build only needs upstream cJSON (no ESP-IDF
# integration), so strip the suffix and fetch the matching upstream tag.
# Doing it this way keeps the host test tied to whatever dependencies.lock
# pins, so a future firmware bump of cJSON doesn't silently drift away
# from the host tests.
include(FetchContent)
# We intentionally call FetchContent_Populate (not MakeAvailable) so cJSON's
# own CMakeLists isn't processed — it would force -Werror and add targets we
# don't want. CMake 3.30+ marks this deprecated; set the policy explicitly.
if(POLICY CMP0169)
    cmake_policy(SET CMP0169 OLD)
endif()
# Match the outer 4-space-indented `version:` line, not the inner one nested
# under `dependencies:` (which is the ESP-IDF version range, not cJSON's).
execute_process(
    COMMAND awk "/espressif\\/cjson:/{f=1; next} f && /^[^ ]/{exit} f && /^    version:/{print $2; exit}"
            ${ROOT}/dependencies.lock
    OUTPUT_VARIABLE CJSON_VERSION_RAW
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT CJSON_VERSION_RAW)
    message(FATAL_ERROR "Could not parse cJSON version from ${ROOT}/dependencies.lock")
endif()
string(REGEX REPLACE "~.*$" "" CJSON_VERSION "${CJSON_VERSION_RAW}")
message(STATUS "Fetching cJSON v${CJSON_VERSION} (from dependencies.lock: ${CJSON_VERSION_RAW})")
FetchContent_Declare(
    cjson_src
    GIT_REPOSITORY https://github.com/DaveGamble/cJSON.git
    GIT_TAG v${CJSON_VERSION}
    GIT_SHALLOW TRUE
)
FetchContent_GetProperties(cjson_src)
if(NOT cjson_src_POPULATED)
    FetchContent_Populate(cjson_src)
endif()
# Skip cJSON's own CMakeLists (it would build shared/static libs and run its
# tests). We only want cJSON.c / cJSON.h compiled into our own static lib.
add_library(cjson STATIC ${cjson_src_SOURCE_DIR}/cJSON.c)
target_include_directories(cjson PUBLIC ${cjson_src_SOURCE_DIR})
target_compile_options(cjson PRIVATE -Wno-unused-but-set-variable -Wno-unused-parameter)

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

# api_json — REST-API JSON builders extracted from api_handlers.c. Drives
# each builder with a fixture input, asserts the shape via cJSON, and (when
# BISQUE_FIXTURE_DIR is set) dumps the JSON for the cross-language
# contract validator in web_ui/.
add_host_test(test_api_json
    SOURCES test_api_json.c
            ${ROOT}/components/web_server/api_json.c
            ${ROOT}/components/cone_table/cone_table.c)
target_link_libraries(test_api_json PRIVATE cjson)
target_include_directories(test_api_json PRIVATE
    ${ROOT}/components/web_server/include
    ${ROOT}/components/history/include
    ${ROOT}/components/thermocouple/include
    stubs)

# Generated-fixture target: runs test_api_json with BISQUE_FIXTURE_DIR set so
# its dump_fixture() calls land in ${CMAKE_CURRENT_BINARY_DIR}/fixtures/api.
# Used by the web_ui contract test (web_ui/test/contracts/firmwareContract.test.ts).
add_custom_target(api_fixtures
    COMMAND ${CMAKE_COMMAND} -E env BISQUE_FIXTURE_DIR=${CMAKE_CURRENT_BINARY_DIR}/fixtures/api
            $<TARGET_FILE:test_api_json>
    DEPENDS test_api_json
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/fixtures/api
    COMMENT "Generating API JSON fixtures for web_ui contract test")
