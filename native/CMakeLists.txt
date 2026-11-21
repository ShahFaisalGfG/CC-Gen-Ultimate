cmake_minimum_required(VERSION 3.25)

# The app version in pyproject.toml (`version = "x.y.z"`) is the shell extension's version.
set(_PYPROJECT "${CMAKE_CURRENT_SOURCE_DIR}/../pyproject.toml")
file(STRINGS "${_PYPROJECT}" _VERSION_LINES REGEX "^version = \"[0-9]+\\.[0-9]+\\.[0-9]+\"")
if(NOT _VERSION_LINES)
    message(FATAL_ERROR "No `version = \"x.y.z\"` line found in ${_PYPROJECT}")
endif()
list(GET _VERSION_LINES 0 _VERSION_LINE)
string(REGEX MATCH "[0-9]+\\.[0-9]+\\.[0-9]+" CCGEN_VERSION "${_VERSION_LINE}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_PYPROJECT}")

project(ccgen_native VERSION ${CCGEN_VERSION} LANGUAGES CXX RC)

if(NOT WIN32)
    message(FATAL_ERROR "ccgen_native is a Windows-only target")
endif()

# ── Shell extension COM DLL (Windows 11 first-level context menu) ─────────────
# No external dependencies — pure Win32/COM, so no vcpkg toolchain is needed.

# The version resource reads these from a generated header: CC-Gen-Ultimate's name and version,
# which code signing requires.
file(CONFIGURE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/generated/ccgen_version.h" CONTENT
"#pragma once
#define CCGEN_VERSION_BINARY ${PROJECT_VERSION_MAJOR},${PROJECT_VERSION_MINOR},${PROJECT_VERSION_PATCH},0
#define CCGEN_VERSION_TEXT \"${PROJECT_VERSION}\"
")

add_library(ccgen_shell SHARED src/shell_extension.cpp src/ccgen_shell.def src/ccgen_shell.rc)
target_include_directories(ccgen_shell PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/generated")

set_target_properties(ccgen_shell PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    PREFIX ""
    SUFFIX ".dll"
)

target_link_libraries(ccgen_shell PRIVATE ole32 shell32 uuid)

set(_SHELL_OUT_DIR "${PROJECT_SOURCE_DIR}/../build/shell")

foreach(_CONFIG Debug Release RelWithDebInfo MinSizeRel)
    set_target_properties(ccgen_shell PROPERTIES
        "RUNTIME_OUTPUT_DIRECTORY_${_CONFIG}" "${_SHELL_OUT_DIR}"
    )
endforeach()
set_target_properties(ccgen_shell PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${_SHELL_OUT_DIR}"
)

# VS multi-config generators still append the config sub-folder, so copy the
# final DLL to the flat _SHELL_OUT_DIR explicitly.
add_custom_command(TARGET ccgen_shell POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$<TARGET_FILE:ccgen_shell>"
        "${_SHELL_OUT_DIR}/ccgen_shell.dll"
)
