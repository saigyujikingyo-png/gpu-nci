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
  if("${${_v}}" MATCHES "(^|[ \t;])(-fast|-Mfprelaxed|-Mflushz)([=, \t;]|$)")
    message(FATAL_ERROR "nci_cpu: ${_v} contains '${CMAKE_MATCH_2}', which violates the IEEE/gradual-underflow policy")
  endif()
endforeach()

# The common C API is compiled against the OpenACC backend stub here: NCI_OPENACC
# stays BACKEND_UNAVAILABLE and nothing references the OpenACC runtime. The stub
# lives beside this directory in the same checkout (docs/openacc-public-contract.md).
set(_nci_acc_stub "${CMAKE_CURRENT_SOURCE_DIR}/../backend_openacc/nci_acc_backend_stub.f90")
set(NCI_CPU_SOURCES
  nci_kinds.f90
  nci_abi.f90
  nci_numerics.f90
  nci_validate.f90
  nci_kernel.f90
  "${_nci_acc_stub}"
  nci_capi.f90)
# Only these three carry NCI_BENCHMARK conditionals (private P1 timing objects
# below), so they are always preprocessed. Without the definition, as in every
# target except nci_cpu_bench_objects, they compile exactly the original code.
set_source_files_properties(nci_kernel.f90 nci_capi.f90 "${_nci_acc_stub}"
  PROPERTIES Fortran_PREPROCESS ON)

# Object library shared by the production shared library and white-box tests.
# Its modules have their own directory, propagated to consumers as an include
# path, so they never mix with the modules of the optional nci_openacc variant.
add_library(nci_cpu_objects OBJECT ${NCI_CPU_SOURCES})
set(_nci_cpu_moddir "${CMAKE_CURRENT_BINARY_DIR}/modules")
set_target_properties(nci_cpu_objects PROPERTIES Fortran_MODULE_DIRECTORY "${_nci_cpu_moddir}")
target_include_directories(nci_cpu_objects PUBLIC "$<BUILD_INTERFACE:${_nci_cpu_moddir}>")
if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
  # Root already sets -ffp-contract=off for Fortran; repeated here so the
  # backend keeps it if the scaffold changes.  -frecursive keeps every local
  # on the stack (re-entrant calls on distinct contexts).
  target_compile_options(nci_cpu_objects PRIVATE -ffp-contract=off -frecursive)
  # The stub deliberately ignores its inputs.
  set_source_files_properties("${_nci_acc_stub}" PROPERTIES COMPILE_OPTIONS "-Wno-unused-dummy-argument")
elseif(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
  # Keep the IEEE/no-contraction contract in standalone and external builds;
  # automatic/reentrant locals are needed for distinct concurrent contexts.
  target_compile_options(nci_cpu_objects PRIVATE -Kieee -Mnofma -Mrecursive -Mreentrant)
endif()
if(NCI_ENABLE_OPENMP)
  target_link_libraries(nci_cpu_objects PUBLIC OpenMP::OpenMP_Fortran)
endif()

add_library(nci_cpu SHARED $<TARGET_OBJECTS:nci_cpu_objects>)
set_target_properties(nci_cpu PROPERTIES LINKER_LANGUAGE Fortran)
target_link_libraries(nci_cpu PUBLIC nci_contract)
# Fortran consumers of the library (the native driver uses nci_abi).
target_include_directories(nci_cpu INTERFACE "$<BUILD_INTERFACE:${_nci_cpu_moddir}>")
if(NCI_ENABLE_OPENMP)
  target_link_libraries(nci_cpu PRIVATE OpenMP::OpenMP_Fortran)
endif()
if(UNIX AND NOT APPLE)
  set(_nci_map "${CMAKE_CURRENT_SOURCE_DIR}/nci_cpu.map")
  target_link_options(nci_cpu PRIVATE "LINKER:--version-script=${_nci_map}" "LINKER:--no-undefined")
  set_property(TARGET nci_cpu APPEND PROPERTY LINK_DEPENDS "${_nci_map}")
endif()

# Private P1 benchmark objects (NCI_BUILD_BENCHMARKS, declared OFF by the root
# build; src/benchmark/core/README.md). The production sources are compiled a
# second time with NCI_BENCHMARK into their own module directory, with the
# timing record and clock of src/benchmark/core. nci_cpu, its tests and the
# worker never use them. A benchmark executable links exactly this object
# target and the reader built by the same compiler, never nci_cpu as well; the
# definition, module path, strict Fortran options and OpenMP propagate to it.
if(NCI_BUILD_BENCHMARKS)
  if(NOT NCI_ENABLE_OPENMP)
    message(FATAL_ERROR "NCI_BUILD_BENCHMARKS requires NCI_ENABLE_OPENMP: the CPU timing observes the actual field team")
  endif()
  set(_nci_bench_core "${CMAKE_CURRENT_SOURCE_DIR}/../benchmark/core")
  add_library(nci_cpu_bench_objects OBJECT
    "${_nci_bench_core}/nci_bench_clock.c"
    "${_nci_bench_core}/nci_bench_types.f90"
    ${NCI_CPU_SOURCES})
  set(_nci_cpu_bench_moddir "${CMAKE_CURRENT_BINARY_DIR}/bench_modules")
  set_target_properties(nci_cpu_bench_objects PROPERTIES Fortran_MODULE_DIRECTORY "${_nci_cpu_bench_moddir}")
  target_include_directories(nci_cpu_bench_objects PUBLIC "$<BUILD_INTERFACE:${_nci_cpu_bench_moddir}>")
  target_compile_definitions(nci_cpu_bench_objects PUBLIC NCI_BENCHMARK)
  # Fortran only (the C clock helper keeps the C flags): the production object
  # options, and the floating-point ones for Fortran consumers.
  if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    set(_nci_cpu_bench_private -ffp-contract=off -frecursive)
    set(_nci_cpu_bench_interface -ffp-contract=off)
  elseif(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
    set(_nci_cpu_bench_private -Kieee -Mnofma -Mrecursive -Mreentrant)
    set(_nci_cpu_bench_interface -Kieee -Mnofma)
  else()
    set(_nci_cpu_bench_private "")
    set(_nci_cpu_bench_interface "")
  endif()
  target_compile_options(nci_cpu_bench_objects
    PRIVATE "$<$<COMPILE_LANGUAGE:Fortran>:${_nci_cpu_bench_private}>"
    INTERFACE "$<$<COMPILE_LANGUAGE:Fortran>:${_nci_cpu_bench_interface}>")
  target_link_libraries(nci_cpu_bench_objects PUBLIC OpenMP::OpenMP_Fortran)
endif()

if(BUILD_TESTING)
  add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../../tests/core" "${CMAKE_CURRENT_BINARY_DIR}/tests_core")
endif()
