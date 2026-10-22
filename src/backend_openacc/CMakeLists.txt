# SPDX-License-Identifier: MIT
# Optional nci_openacc library (docs/openacc-public-contract.md, M3B1), added
# by the root build only with -DNCI_ENABLE_OPENACC=ON. It exports the same three
# ABI v1 functions as nci_cpu and supports the CPU and OpenACC selectors; a
# consumer links one of the two libraries. Configure and build never run it.

if(NOT CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC" OR NOT CMAKE_Fortran_COMPILER_VERSION VERSION_EQUAL "26.9")
  message(FATAL_ERROR "NCI_ENABLE_OPENACC: requires NVHPC nvfortran 26.9, found "
    "${CMAKE_Fortran_COMPILER_ID} ${CMAKE_Fortran_COMPILER_VERSION}")
endif()
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$")
  message(FATAL_ERROR "NCI_ENABLE_OPENACC: the supported target is Linux x86_64")
endif()
get_property(_nci_acc_multi GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(_nci_acc_multi)
  message(FATAL_ERROR "NCI_ENABLE_OPENACC: use a single-configuration generator so that the "
    "effective configuration flags can be checked")
endif()

# The effective user and configuration flags must keep IEEE binary64 with
# gradual underflow and no contraction, and must leave every OpenACC, GPU and
# OpenMP option to this file. CMake's NVHPC Release defaults contain -fast.
set(_nci_acc_flag_vars CMAKE_Fortran_FLAGS CMAKE_SHARED_LINKER_FLAGS CMAKE_EXE_LINKER_FLAGS)
if(CMAKE_BUILD_TYPE)
  string(TOUPPER "${CMAKE_BUILD_TYPE}" _nci_acc_cfg)
  list(APPEND _nci_acc_flag_vars CMAKE_Fortran_FLAGS_${_nci_acc_cfg}
    CMAKE_SHARED_LINKER_FLAGS_${_nci_acc_cfg} CMAKE_EXE_LINKER_FLAGS_${_nci_acc_cfg})
endif()
foreach(_nci_acc_var IN LISTS _nci_acc_flag_vars)
  separate_arguments(_nci_acc_tokens UNIX_COMMAND "${${_nci_acc_var}}")
  foreach(_nci_acc_token IN LISTS _nci_acc_tokens)
    string(TOLOWER "${_nci_acc_token}" _nci_acc_lower)
    if((_nci_acc_lower MATCHES "fast" AND NOT _nci_acc_lower MATCHES "/")
       OR _nci_acc_lower MATCHES "^-m(fma|fprelaxed|fpapprox|flushz|daz)([=,:]|$)"
       OR _nci_acc_lower MATCHES "^-knoieee$"
       OR _nci_acc_lower MATCHES "^-f(unsafe-math-optimizations|associative-math|reciprocal-math)$"
       OR _nci_acc_lower MATCHES "^-(acc|gpu|ta|cuda|mp|stdpar|mcuda|cudalib|mx|my)([=,:]|$)")
      message(FATAL_ERROR "NCI_ENABLE_OPENACC: ${_nci_acc_var} contains '${_nci_acc_token}'; "
        "value-changing floating-point, target and OpenMP options are not accepted "
        "(this file applies the frozen ones)")
    endif()
  endforeach()
endforeach()

find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
set(_nci_acc_cpu "${NCI_CPU_SOURCE_DIR}")
foreach(_nci_acc_file IN ITEMS nci_kinds.f90 nci_abi.f90 nci_numerics.f90 nci_validate.f90
                               nci_kernel.f90 nci_capi.f90)
  if(NOT EXISTS "${_nci_acc_cpu}/${_nci_acc_file}")
    message(FATAL_ERROR "NCI_ENABLE_OPENACC: ${_nci_acc_cpu}/${_nci_acc_file} not found")
  endif()
endforeach()
message(STATUS "nci_openacc: production sources ${_nci_acc_cpu}")

# Frozen device flags (a compiler rejecting one fails the build), the
# reentrant host flags of every NVHPC CPU object and the compilation report.
set(NCI_OPENACC_DEVICE_FLAGS -acc=gpu -Kieee -Mnofma
  -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc)
set(NCI_OPENACC_HOST_FLAGS -Mrecursive -Mreentrant)
set(NCI_OPENACC_REPORT -Minfo=accel)

# Insertion-only device adaptation of kinds, numerics and kernel into the
# build directory; any anchor drift fails the build and writes nothing.
set(_nci_acc_gen "${CMAKE_CURRENT_BINARY_DIR}/generated")
set(_nci_acc_generated "${_nci_acc_gen}/nci_kinds.f90" "${_nci_acc_gen}/nci_numerics.f90"
                       "${_nci_acc_gen}/nci_kernel.f90")
add_custom_command(
  OUTPUT ${_nci_acc_generated}
         "${_nci_acc_gen}/nci_kinds.f90.diff" "${_nci_acc_gen}/nci_numerics.f90.diff"
         "${_nci_acc_gen}/nci_kernel.f90.diff" "${_nci_acc_gen}/SHA256SUMS"
         "${_nci_acc_gen}/manifest.json"
  COMMAND "${Python3_EXECUTABLE}" -I "${CMAKE_CURRENT_SOURCE_DIR}/generate_device_sources.py"
          --production-dir "${_nci_acc_cpu}" --output-dir "${_nci_acc_gen}"
  DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/generate_device_sources.py"
          "${_nci_acc_cpu}/nci_kinds.f90" "${_nci_acc_cpu}/nci_numerics.f90"
          "${_nci_acc_cpu}/nci_kernel.f90"
  COMMENT "nci_openacc: insertion-only device adaptation of the production sources"
  VERBATIM)

# Only these three carry NCI_BENCHMARK conditionals (private P1 timing objects
# below), so only they are preprocessed. Without the definition, as in
# nci_openacc_objects, they compile exactly the original code.
set_source_files_properties("${_nci_acc_gen}/nci_kernel.f90"
  "${CMAKE_CURRENT_SOURCE_DIR}/nci_acc_backend.f90" "${_nci_acc_cpu}/nci_capi.f90"
  PROPERTIES Fortran_PREPROCESS ON)

# One object set for the shared library and for the private test bridge, which
# must link these same objects. The common C API and validation are the
# production files; nci_acc_backend.f90 replaces the CPU library's stub.
add_library(nci_openacc_objects OBJECT
  "${_nci_acc_gen}/nci_kinds.f90"
  "${_nci_acc_cpu}/nci_abi.f90"
  "${_nci_acc_gen}/nci_numerics.f90"
  "${_nci_acc_cpu}/nci_validate.f90"
  "${_nci_acc_gen}/nci_kernel.f90"
  "${CMAKE_CURRENT_SOURCE_DIR}/nci_acc_backend.f90"
  "${_nci_acc_cpu}/nci_capi.f90")
set(_nci_acc_moddir "${CMAKE_CURRENT_BINARY_DIR}/modules")
set_target_properties(nci_openacc_objects PROPERTIES
  Fortran_MODULE_DIRECTORY "${_nci_acc_moddir}"
  Fortran_PREPROCESS OFF
  EXPORT_COMPILE_COMMANDS ON)
target_include_directories(nci_openacc_objects PUBLIC "$<BUILD_INTERFACE:${_nci_acc_moddir}>")
target_compile_options(nci_openacc_objects PRIVATE
  ${NCI_OPENACC_DEVICE_FLAGS} ${NCI_OPENACC_HOST_FLAGS} ${NCI_OPENACC_REPORT})
# Fortran consumers of the objects compile and device-link with the same options.
target_compile_options(nci_openacc_objects INTERFACE
  "$<$<COMPILE_LANGUAGE:Fortran>:${NCI_OPENACC_DEVICE_FLAGS};${NCI_OPENACC_HOST_FLAGS}>")
target_link_options(nci_openacc_objects INTERFACE ${NCI_OPENACC_DEVICE_FLAGS})
if(NCI_ENABLE_OPENMP)
  target_link_libraries(nci_openacc_objects PUBLIC OpenMP::OpenMP_Fortran)
endif()

add_library(nci_openacc SHARED $<TARGET_OBJECTS:nci_openacc_objects>)
set_target_properties(nci_openacc PROPERTIES LINKER_LANGUAGE Fortran)
target_link_libraries(nci_openacc PUBLIC nci_contract)
target_include_directories(nci_openacc INTERFACE "$<BUILD_INTERFACE:${_nci_acc_moddir}>")
target_link_options(nci_openacc PRIVATE ${NCI_OPENACC_DEVICE_FLAGS})
if(NCI_ENABLE_OPENMP)
  target_link_libraries(nci_openacc PRIVATE OpenMP::OpenMP_Fortran)
endif()
set(_nci_acc_map "${CMAKE_CURRENT_SOURCE_DIR}/nci_openacc.map")
target_link_options(nci_openacc PRIVATE "LINKER:--version-script=${_nci_acc_map}"
  "LINKER:--no-undefined")
set_property(TARGET nci_openacc APPEND PROPERTY LINK_DEPENDS "${_nci_acc_map}")

# Private P1 benchmark objects (NCI_BUILD_BENCHMARKS, declared OFF by the root
# build; src/benchmark/core/README.md): the same object list compiled again
# with NCI_BENCHMARK into its own module directory, with the timing record and
# clock of src/benchmark/core. nci_openacc, its tests and the worker never use
# them. A benchmark executable links exactly this object target and the reader
# built by the same compiler, never nci_openacc as well; the definition, module
# path, Fortran device/host options, device link, OpenMP and the CUDA runtime
# propagate to it. Its runtime search path remains the executable's concern.
if(NCI_BUILD_BENCHMARKS)
  if(NOT NCI_ENABLE_OPENMP)
    message(FATAL_ERROR "NCI_BUILD_BENCHMARKS requires NCI_ENABLE_OPENMP")
  endif()
  # CUDA event API: the runtime library of this SDK's CUDA 13.3 toolkit (the
  # one the device flags select), located explicitly, never a system copy.
  get_filename_component(_nci_bench_bin "${CMAKE_Fortran_COMPILER}" DIRECTORY)
  get_filename_component(_nci_bench_compilers "${_nci_bench_bin}/.." REALPATH)
  get_filename_component(_nci_bench_sdk "${_nci_bench_compilers}/.." REALPATH)
  find_library(NCI_BENCH_CUDART NAMES cudart libcudart.so.13
    PATHS "${_nci_bench_sdk}/cuda/13.3/lib64" "${_nci_bench_sdk}/cuda/13.3/targets/x86_64-linux/lib"
    NO_DEFAULT_PATH)
  if(NOT NCI_BENCH_CUDART)
    message(FATAL_ERROR "NCI_BUILD_BENCHMARKS: libcudart of ${_nci_bench_sdk}/cuda/13.3 not found")
  endif()
  set(_nci_bench_core "${CMAKE_CURRENT_SOURCE_DIR}/../benchmark/core")
  add_library(nci_openacc_bench_objects OBJECT
    "${_nci_bench_core}/nci_bench_clock.c"
    "${_nci_bench_core}/nci_bench_types.f90"
    "${_nci_acc_gen}/nci_kinds.f90"
    "${_nci_acc_cpu}/nci_abi.f90"
    "${_nci_acc_gen}/nci_numerics.f90"
    "${_nci_acc_cpu}/nci_validate.f90"
    "${_nci_acc_gen}/nci_kernel.f90"
    "${CMAKE_CURRENT_SOURCE_DIR}/nci_acc_backend.f90"
    "${_nci_acc_cpu}/nci_capi.f90")
  set(_nci_acc_bench_moddir "${CMAKE_CURRENT_BINARY_DIR}/bench_modules")
  set_target_properties(nci_openacc_bench_objects PROPERTIES
    Fortran_MODULE_DIRECTORY "${_nci_acc_bench_moddir}"
    Fortran_PREPROCESS OFF
    EXPORT_COMPILE_COMMANDS ON)
  target_include_directories(nci_openacc_bench_objects PUBLIC "$<BUILD_INTERFACE:${_nci_acc_bench_moddir}>")
  target_compile_definitions(nci_openacc_bench_objects PUBLIC NCI_BENCHMARK)
  # Fortran only: the C clock helper keeps the C flags.
  target_compile_options(nci_openacc_bench_objects PRIVATE
    "$<$<COMPILE_LANGUAGE:Fortran>:${NCI_OPENACC_DEVICE_FLAGS};${NCI_OPENACC_HOST_FLAGS};${NCI_OPENACC_REPORT}>")
  target_compile_options(nci_openacc_bench_objects INTERFACE
    "$<$<COMPILE_LANGUAGE:Fortran>:${NCI_OPENACC_DEVICE_FLAGS};${NCI_OPENACC_HOST_FLAGS}>")
  target_link_options(nci_openacc_bench_objects INTERFACE ${NCI_OPENACC_DEVICE_FLAGS})
  target_link_libraries(nci_openacc_bench_objects PUBLIC OpenMP::OpenMP_Fortran "${NCI_BENCH_CUDART}")
  # Two object targets now compile the generated sources: one custom target
  # drives the generator, so a parallel build never runs it twice.
  add_custom_target(nci_openacc_device_sources DEPENDS ${_nci_acc_generated})
  add_dependencies(nci_openacc_objects nci_openacc_device_sources)
  add_dependencies(nci_openacc_bench_objects nci_openacc_device_sources)
endif()
