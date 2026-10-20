# SPDX-License-Identifier: MIT
# Standalone M3A OpenACC numerical portability probe: contract in
# docs/openacc-probe-contract.md, usage in docs/openacc-probe-implementation.md.
# Not part of the root build; nothing is executed by configure or build except
# the source adapter. Does nothing unless -DNCI_ENABLE_OPENACC_PROBE=ON.
cmake_minimum_required(VERSION 3.28)
project(nci_openacc_probe LANGUAGES Fortran)

option(NCI_ENABLE_OPENACC_PROBE "Build the isolated M3A OpenACC probe (NVHPC 26.9 only)" OFF)
if(NOT NCI_ENABLE_OPENACC_PROBE)
  message(STATUS "M3A OpenACC probe: OFF (use -DNCI_ENABLE_OPENACC_PROBE=ON with NVHPC 26.9)")
  return()
endif()

if(NOT CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC" OR NOT CMAKE_Fortran_COMPILER_VERSION VERSION_EQUAL "26.9")
  message(FATAL_ERROR "M3A probe: requires NVHPC nvfortran 26.9, found "
    "${CMAKE_Fortran_COMPILER_ID} ${CMAKE_Fortran_COMPILER_VERSION}")
endif()
get_property(_m3a_multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(_m3a_multi_config OR CMAKE_BUILD_TYPE)
  message(FATAL_ERROR "M3A probe: use a single-configuration generator and leave "
    "CMAKE_BUILD_TYPE empty (CMake's NVHPC Release flags include -fast)")
endif()
foreach(_m3a_var IN ITEMS CMAKE_Fortran_FLAGS CMAKE_EXE_LINKER_FLAGS)
  string(STRIP "${${_m3a_var}}" _m3a_value)
  if(NOT _m3a_value STREQUAL "")
    message(FATAL_ERROR "M3A probe: ${_m3a_var} must be empty; only the frozen flags are applied")
  endif()
endforeach()
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Frozen device flags; a compiler rejecting any of them fails the build.
set(NCI_PROBE_DEVICE_FLAGS -acc=gpu -Kieee -Mnofma -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc)
# Device-generation report; it does not change code generation.
set(NCI_PROBE_DEVICE_REPORT -Minfo=accel)
# Host reference: the production NVHPC CPU options (IEEE, no FMA, reentrant locals).
set(NCI_PROBE_HOST_FLAGS -Kieee -Mnofma -Mrecursive -Mreentrant)

get_filename_component(_m3a_default_root "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(NCI_PROBE_PRODUCTION_ROOT "${_m3a_default_root}" CACHE PATH
  "Checkout whose src/backend_cpu/nci_kinds.f90 and nci_numerics.f90 are probed")
set(_m3a_cpu "${NCI_PROBE_PRODUCTION_ROOT}/src/backend_cpu")
foreach(_m3a_file IN ITEMS nci_kinds.f90 nci_numerics.f90)
  if(NOT EXISTS "${_m3a_cpu}/${_m3a_file}")
    message(FATAL_ERROR "M3A probe: ${_m3a_cpu}/${_m3a_file} not found")
  endif()
endforeach()
find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
message(STATUS "M3A probe: production sources ${_m3a_cpu}")

# Deterministic adaptation into the build directory (fails on anchor drift).
set(_m3a_gen "${CMAKE_CURRENT_BINARY_DIR}/generated")
add_custom_command(
  OUTPUT "${_m3a_gen}/host/nci_numerics.f90" "${_m3a_gen}/device/nci_kinds.f90"
         "${_m3a_gen}/device/nci_numerics.f90" "${_m3a_gen}/host/nci_numerics.f90.diff"
         "${_m3a_gen}/device/nci_kinds.f90.diff" "${_m3a_gen}/device/nci_numerics.f90.diff"
         "${_m3a_gen}/SHA256SUMS" "${_m3a_gen}/manifest.json"
  COMMAND "${Python3_EXECUTABLE}" -I "${CMAKE_CURRENT_SOURCE_DIR}/generate_sources.py"
          --production-root "${NCI_PROBE_PRODUCTION_ROOT}" --output-dir "${_m3a_gen}"
  DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/generate_sources.py"
          "${_m3a_cpu}/nci_kinds.f90" "${_m3a_cpu}/nci_numerics.f90"
  COMMENT "M3A: adapting production sources into ${_m3a_gen}"
  VERBATIM)

set(_m3a_src "${CMAKE_CURRENT_SOURCE_DIR}/src")
# No source needs preprocessing: compile the hashed files themselves instead of
# CMake's intermediate -Mpreprocess copies.
set(CMAKE_Fortran_PREPROCESS OFF)

# Host reference: production nci_kinds.f90 in place, nci_numerics.f90 with only
# the test-only visibility of c_cbrt; no OpenACC.
add_executable(m3a_host
  "${_m3a_cpu}/nci_kinds.f90"
  "${_m3a_gen}/host/nci_numerics.f90"
  "${_m3a_src}/m3a_records.f90"
  "${_m3a_src}/m3a_io.f90"
  "${_m3a_src}/m3a_host.f90")
target_compile_options(m3a_host PRIVATE ${NCI_PROBE_HOST_FLAGS})
target_link_options(m3a_host PRIVATE -Kieee -Mnofma)
set_target_properties(m3a_host PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/modules/host"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/host")

# Device driver: production sources plus device routine declarations only,
# relocatable device code, explicit NVIDIA selection, no host fallback.
add_executable(m3a_device
  "${_m3a_gen}/device/nci_kinds.f90"
  "${_m3a_gen}/device/nci_numerics.f90"
  "${_m3a_src}/m3a_records.f90"
  "${_m3a_src}/m3a_io.f90"
  "${_m3a_src}/m3a_device.f90")
target_compile_options(m3a_device PRIVATE ${NCI_PROBE_DEVICE_FLAGS} ${NCI_PROBE_DEVICE_REPORT})
target_link_options(m3a_device PRIVATE ${NCI_PROBE_DEVICE_FLAGS})
set_target_properties(m3a_device PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/modules/device"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/device")
