# SPDX-License-Identifier: MIT
# CPU backend (ABI v1): Fortran 2008 + ISO_C_BINDING, optional OpenMP.

# The roundoff bound behind LAMBDA_NUM_UNCERTAIN assumes IEEE binary64
# semantics with explicit operation order; refuse value-changing flags.
set(_nci_flag_vars CMAKE_Fortran_FLAGS)
if(CMAKE_BUILD_TYPE)
  string(TOUPPER "${CMAKE_BUILD_TYPE}" _nci_cfg)
  list(APPEND _nci_flag_vars CMAKE_Fortran_FLAGS_${_nci_cfg})
endif()
foreach(_v IN LISTS _nci_flag_vars)
  if("${${_v}}" MATCHES "(-ffast-math|-Ofast|-funsafe-math-optimizations|-fassociative-math|-freciprocal-math|-ffp-contract=fast)")
    message(FATAL_ERROR "nci_cpu: ${_v} contains '${CMAKE_MATCH_1}', which voids the documented rounding bounds")
  endif()
endforeach()

set(NCI_CPU_SOURCES
  nci_kinds.f90
  nci_abi.f90
  nci_numerics.f90
  nci_validate.f90
  nci_kernel.f90
  nci_capi.f90)

# Object library shared by the production shared library and white-box tests.
add_library(nci_cpu_objects OBJECT ${NCI_CPU_SOURCES})
if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
  # Root already sets -ffp-contract=off for Fortran; repeated here so the
  # backend keeps it if the scaffold changes.  -frecursive keeps every local
  # on the stack (re-entrant calls on distinct contexts).
  target_compile_options(nci_cpu_objects PRIVATE -ffp-contract=off -frecursive)
endif()
if(NCI_ENABLE_OPENMP)
  target_link_libraries(nci_cpu_objects PUBLIC OpenMP::OpenMP_Fortran)
endif()

add_library(nci_cpu SHARED $<TARGET_OBJECTS:nci_cpu_objects>)
set_target_properties(nci_cpu PROPERTIES LINKER_LANGUAGE Fortran)
target_link_libraries(nci_cpu PUBLIC nci_contract)
if(NCI_ENABLE_OPENMP)
  target_link_libraries(nci_cpu PRIVATE OpenMP::OpenMP_Fortran)
endif()
if(UNIX AND NOT APPLE)
  set(_nci_map "${CMAKE_CURRENT_SOURCE_DIR}/nci_cpu.map")
  target_link_options(nci_cpu PRIVATE "LINKER:--version-script=${_nci_map}" "LINKER:--no-undefined")
  set_property(TARGET nci_cpu APPEND PROPERTY LINK_DEPENDS "${_nci_map}")
endif()

if(BUILD_TESTING)
  add_subdirectory("${PROJECT_SOURCE_DIR}/tests/core" "${CMAKE_CURRENT_BINARY_DIR}/tests_core")
endif()
