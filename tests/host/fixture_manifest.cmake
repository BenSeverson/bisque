# Emit fixtures/api/_manifest.json alongside the generated API fixtures.
#
# Run in script mode as part of the `api_fixtures` target:
#
#   cmake -D ROOT=<repo root> -D OUT=<fixture dir>/_manifest.json \
#         -D SOURCE_LIST=<tests/host/fixture_sources.txt> \
#         -P fixture_manifest.cmake
#
# The manifest records a SHA256 for every path in SOURCE_LIST as it stood when
# the fixtures were generated. web_ui/test/contracts/firmwareContract.test.ts
# re-hashes those same paths and fails when a digest has moved, so editing a
# serializer without re-running `make fixtures` is a test failure rather than a
# silent pass against stale JSON.
#
# Hashing happens here — at build time, in a script invocation — rather than at
# configure time, so an edit made after the last `cmake -S/-B` still registers.

foreach(var ROOT OUT SOURCE_LIST)
    if(NOT DEFINED ${var})
        message(FATAL_ERROR "fixture_manifest.cmake: -D ${var}=... is required")
    endif()
endforeach()

if(NOT EXISTS "${SOURCE_LIST}")
    message(FATAL_ERROR "fixture_manifest.cmake: source list not found: ${SOURCE_LIST}")
endif()

file(STRINGS "${SOURCE_LIST}" lines ENCODING UTF-8)

set(entries "")
foreach(line IN LISTS lines)
    string(STRIP "${line}" rel)
    if(rel STREQUAL "" OR rel MATCHES "^#")
        continue()
    endif()
    set(abs "${ROOT}/${rel}")
    if(NOT EXISTS "${abs}")
        message(FATAL_ERROR
            "fixture_manifest.cmake: ${rel} is listed in fixture_sources.txt but does not exist. "
            "Update the list if the file moved or was removed.")
    endif()
    file(SHA256 "${abs}" digest)
    list(APPEND entries "    \"${rel}\": \"${digest}\"")
endforeach()

if(entries STREQUAL "")
    message(FATAL_ERROR "fixture_manifest.cmake: ${SOURCE_LIST} lists no sources")
endif()

string(JOIN ",\n" sources_json ${entries})
string(TIMESTAMP generated_at "%Y-%m-%dT%H:%M:%SZ" UTC)

file(WRITE "${OUT}" "{\n  \"generatedAt\": \"${generated_at}\",\n  \"sources\": {\n${sources_json}\n  }\n}\n")
message(STATUS "Wrote fixture manifest: ${OUT}")
