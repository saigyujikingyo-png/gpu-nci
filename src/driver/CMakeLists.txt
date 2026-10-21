# Thin executable adapters; both targets compile the same worker source.
if(NOT TARGET nci_cpu OR NOT TARGET nci_cube_input)
  message(FATAL_ERROR "nci_driver needs nci_cpu and nci_cube_input targets")
endif()
if(NOT DEFINED NCI_BUILD_REVISION)
  set(NCI_BUILD_REVISION "UNKNOWN")
endif()

include("${CMAKE_CURRENT_SOURCE_DIR}/build-string.cmake")

function(nci_add_worker target backend)
  set(_benchmark FALSE)
  if(ARGC GREATER 2 AND ARGV2 STREQUAL "BENCHMARK")
    set(_benchmark TRUE)
  endif()
  if(backend STREQUAL "nci_cpu")
    set(_has_openacc .false.)
    set(_backends "[\"cpu\"]")
  elseif(backend STREQUAL "nci_openacc")
    set(_has_openacc .true.)
    set(_backends "[\"cpu\",\"openacc\"]")
  else()
    message(FATAL_ERROR "Unsupported worker library: ${backend}")
  endif()
  set(_generated "${CMAKE_CURRENT_BINARY_DIR}/generated/${target}")
  set(_modules "${_generated}/modules")
  file(MAKE_DIRECTORY "${_modules}")

  # Separate metadata and module directories prevent the two workers from
  # sharing a compiler's .mod files. ACHAR encoding preserves exact bytes.
  set(_nci_metadata "module nci_driver_build\nimplicit none\nlogical, parameter :: build_has_openacc = ${_has_openacc}\ncontains\n")
  nci_build_string(build_revision "${NCI_BUILD_REVISION}")
  nci_build_string(build_compiler_id "${CMAKE_Fortran_COMPILER_ID}")
  nci_build_string(build_compiler_version "${CMAKE_Fortran_COMPILER_VERSION}")
  nci_build_string(build_type "${CMAKE_BUILD_TYPE}")
  nci_build_string(build_fp_policy "IEEE binary64; round-to-nearest; gradual underflow; no FMA contraction")
  nci_build_string(build_supported_backends "${_backends}")
  string(APPEND _nci_metadata "end module\n")
  file(GENERATE OUTPUT "${_generated}/nci_driver_build.f90" CONTENT "${_nci_metadata}")

  # Resolve TARGET_FILE first, then byte-encode it at build time. Never inject
  # a backend path as a Fortran literal, including quotes or control bytes.
  if(_benchmark)
    # Private object linkage has no used backend DSO to identify. Do not emit
    # the production library path as though it were a runtime dependency.
    set(_nci_metadata "module nci_driver_backend\nimplicit none\ncontains\n")
    nci_build_string(build_backend_library "private-object-link:${backend}_bench_objects")
    string(APPEND _nci_metadata "end module\n")
    file(GENERATE OUTPUT "${_generated}/nci_driver_backend.f90" CONTENT "${_nci_metadata}")
  else()
    file(GENERATE OUTPUT "${_generated}/backend-path.txt" CONTENT "$<TARGET_FILE:${backend}>")
    add_custom_command(OUTPUT "${_generated}/nci_driver_backend.f90"
    COMMAND "${CMAKE_COMMAND}"
      "-DINPUT_FILE=${_generated}/backend-path.txt"
      "-DOUTPUT_FILE=${_generated}/nci_driver_backend.f90"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/backend-metadata.cmake"
    DEPENDS "${_generated}/backend-path.txt"
      "${CMAKE_CURRENT_SOURCE_DIR}/backend-metadata.cmake" "${CMAKE_CURRENT_SOURCE_DIR}/build-string.cmake"
      VERBATIM)
  endif()
  if(_benchmark)
    set(_benchmark_dir "${CMAKE_CURRENT_SOURCE_DIR}/../../benchmarks")
    add_executable(${target} "${_generated}/nci_driver_build.f90"
      "${_generated}/nci_driver_backend.f90" nci_driver_support.f90
      "${_benchmark_dir}/nci_benchmark_support.f90" "${_benchmark_dir}/nci_benchmark.f90"
      "${_benchmark_dir}/nci_benchmark_io.c")
    target_link_libraries(${target} PRIVATE ${backend}_bench_objects nci_cube_input)
    target_compile_definitions(${target} PRIVATE NCI_BENCHMARK)
  else()
    add_executable(${target} "${_generated}/nci_driver_build.f90"
      "${_generated}/nci_driver_backend.f90" nci_driver_support.f90 nci_driver.f90)
    target_link_libraries(${target} PRIVATE ${backend} nci_cube_input)
  endif()
  set_target_properties(${target} PROPERTIES Fortran_MODULE_DIRECTORY "${_modules}" Fortran_PREPROCESS ON)
  target_include_directories(${target} PRIVATE "${_modules}")
  # Production uses one public ABI library; private benchmarks use dedicated
  # instrumented objects. nci_cube_input is the same-compiler strict reader.
  if(_benchmark)
    add_dependencies(${target} ${backend}_bench_objects nci_cube_input)
  else()
    add_dependencies(${target} ${backend}_objects nci_cube_input)
  endif()
  if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    target_compile_options(${target} PRIVATE "$<$<COMPILE_LANGUAGE:Fortran>:-ffp-contract=off;-fimplicit-none>")
  elseif(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
    target_compile_options(${target} PRIVATE "$<$<COMPILE_LANGUAGE:Fortran>:-Kieee;-Mnofma;-Mrecursive;-Mreentrant>")
  endif()

  if(backend STREQUAL "nci_openacc")
    if(CMAKE_SKIP_RPATH OR CMAKE_SKIP_BUILD_RPATH)
      message(FATAL_ERROR "nci_driver_openacc requires an embedded runtime search path")
    endif()
    get_filename_component(_compiler_bin "${CMAKE_Fortran_COMPILER}" DIRECTORY)
    get_filename_component(_compilers "${_compiler_bin}/.." REALPATH)
    get_filename_component(_sdk "${_compilers}/.." REALPATH)
    set(_runtime_dirs "${_compilers}/lib" "${_sdk}/cuda/13.3/lib64")
    foreach(_runtime_dir IN LISTS _runtime_dirs)
      if(NOT IS_DIRECTORY "${_runtime_dir}")
        message(FATAL_ERROR "nci_driver_openacc runtime directory missing: ${_runtime_dir}")
      endif()
    endforeach()
    # DT_RPATH also resolves the selected backend's indirect SDK dependencies
    # after the CLI removes LD_LIBRARY_PATH and LD_PRELOAD. This is deliberately
    # local to the optional worker; the default CPU build gets no GPU paths.
    set_target_properties(${target} PROPERTIES
      BUILD_RPATH "$<TARGET_FILE_DIR:${backend}>;${_runtime_dirs}"
      BUILD_RPATH_USE_ORIGIN FALSE)
    # Link the GPU OpenACC runtime directly before NVHPC's host-only API stubs.
    # Keep the backend's frozen architecture/toolkit explicit at this link too.
    target_link_options(${target} PRIVATE -acc=gpu -gpu=cc120,cuda13.3
      "LINKER:--disable-new-dtags")
  endif()
endfunction()

nci_add_worker(nci_driver nci_cpu)
if(NCI_ENABLE_OPENACC)
  nci_add_worker(nci_driver_openacc nci_openacc)
endif()
if(NCI_BUILD_BENCHMARKS)
  if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT NCI_ENABLE_OPENMP)
    message(FATAL_ERROR "Private benchmarks require Linux durable file/directory fsync and OpenMP")
  endif()
  nci_add_worker(nci_benchmark_cpu nci_cpu BENCHMARK)
  if(NCI_ENABLE_OPENACC)
    nci_add_worker(nci_benchmark_openacc nci_openacc BENCHMARK)
  endif()
endif()
if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(NAME native_driver_protocol COMMAND "${CMAKE_COMMAND}" -E env
    "NCI_DRIVER=$<TARGET_FILE:nci_driver>" "${Python3_EXECUTABLE}" -m pytest -q -ra
    "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/driver")
  set_tests_properties(native_driver_protocol PROPERTIES TIMEOUT 120)
  add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../../tests/benchmark" "${CMAKE_CURRENT_BINARY_DIR}/benchmark_tests")
endif()
