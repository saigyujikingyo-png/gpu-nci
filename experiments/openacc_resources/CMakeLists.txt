# SPDX-License-Identifier: MIT
# Standalone M3B0 OpenACC resource gate: contract in
# docs/openacc-resource-contract.md, usage in docs/openacc-resource-implementation.md.
# Not part of the root build; configure and build never execute the candidate.
# Does nothing unless -DNCI_ENABLE_OPENACC_RESOURCES=ON.
cmake_minimum_required(VERSION 3.28)
project(nci_openacc_resources LANGUAGES Fortran)

option(NCI_ENABLE_OPENACC_RESOURCES "Build the isolated M3B0 OpenACC resource gate (NVHPC 26.9 only)" OFF)
if(NOT NCI_ENABLE_OPENACC_RESOURCES)
  message(STATUS "M3B0 OpenACC resource gate: OFF (use -DNCI_ENABLE_OPENACC_RESOURCES=ON with NVHPC 26.9)")
  return()
endif()

if(NOT CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC" OR NOT CMAKE_Fortran_COMPILER_VERSION VERSION_EQUAL "26.9")
  message(FATAL_ERROR "M3B0 resource gate: requires NVHPC nvfortran 26.9, found "
    "${CMAKE_Fortran_COMPILER_ID} ${CMAKE_Fortran_COMPILER_VERSION}")
endif()
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$")
  message(FATAL_ERROR "M3B0 resource gate: requires Linux x86_64, the frozen NVHPC 26.9 target")
endif()
get_property(_m3b0_multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(_m3b0_multi_config OR CMAKE_BUILD_TYPE)
  message(FATAL_ERROR "M3B0 resource gate: use a single-configuration generator and leave "
    "CMAKE_BUILD_TYPE empty (CMake's NVHPC Release flags include -fast)")
endif()
foreach(_m3b0_var IN ITEMS CMAKE_Fortran_FLAGS CMAKE_EXE_LINKER_FLAGS)
  string(STRIP "${${_m3b0_var}}" _m3b0_value)
  if(NOT _m3b0_value STREQUAL "")
    message(FATAL_ERROR "M3B0 resource gate: ${_m3b0_var} must be empty; only the frozen flags are applied")
  endif()
endforeach()
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
# Compile the reviewed files themselves rather than -Mpreprocess copies.
set(CMAKE_Fortran_PREPROCESS OFF)

# Frozen device flags; a compiler rejecting any of them fails the build.
set(NCI_RESOURCE_DEVICE_FLAGS -acc=gpu -Kieee -Mnofma -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc)
# Device-generation report; it does not change code generation.
set(NCI_RESOURCE_DEVICE_REPORT -Minfo=accel)

set(_m3b0_src "${CMAKE_CURRENT_SOURCE_DIR}/src")
# The bounded ledger, the private workspace and the fixed harness. The
# executable takes no arguments and is never run by configure or build.
add_executable(m3b_resources
  "${_m3b0_src}/m3b_ledger.f90"
  "${_m3b0_src}/m3b_workspace.f90"
  "${_m3b0_src}/m3b_resources.f90")
target_compile_options(m3b_resources PRIVATE ${NCI_RESOURCE_DEVICE_FLAGS} ${NCI_RESOURCE_DEVICE_REPORT})
target_link_options(m3b_resources PRIVATE ${NCI_RESOURCE_DEVICE_FLAGS})
set_target_properties(m3b_resources PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/modules"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
