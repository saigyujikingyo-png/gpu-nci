# Thin executable adapters; both targets compile the same worker source.
if(NOT TARGET nci_cpu OR NOT TARGET nci_cube_input)
  message(FATAL_ERROR "nci_driver needs nci_cpu and nci_cube_input targets")
endif()
if(NOT DEFINED NCI_BUILD_REVISION)
  set(NCI_BUILD_REVISION "UNKNOWN")
endif()

include("${CMAKE_CURRENT_SOURCE_DIR}/build-string.cmake")

function(nci_add_worker target backend)
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
  file(GENERATE OUTPUT "${_generated}/backend-path.txt" CONTENT "$<TARGET_FILE:${backend}>")
  add_custom_command(OUTPUT "${_generated}/nci_driver_backend.f90"
    COMMAND "${CMAKE_COMMAND}"
      "-DINPUT_FILE=${_generated}/backend-path.txt"
      "-DOUTPUT_FILE=${_generated}/nci_driver_backend.f90"
      -P "${CMAKE_CURRENT_SOURCE_DIR}/backend-metadata.cmake"
    DEPENDS "${_generated}/backend-path.txt"
      "${CMAKE_CURRENT_SOURCE_DIR}/backend-metadata.cmake" "${CMAKE_CURRENT_SOURCE_DIR}/build-string.cmake"
    VERBATIM)
  add_executable(${target} "${_generated}/nci_driver_build.f90"
    "${_generated}/nci_driver_backend.f90" nci_driver.f90)
  set_target_properties(${target} PROPERTIES Fortran_MODULE_DIRECTORY "${_modules}")
  target_include_directories(${target} PRIVATE "${_modules}")
  # Link exactly one public ABI library. nci_cube_input is built by the same
  # project compiler and contributes only the strict input reader.
  target_link_libraries(${target} PRIVATE ${backend} nci_cube_input)
  add_dependencies(${target} ${backend}_objects nci_cube_input)
  if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
    target_compile_options(${target} PRIVATE -ffp-contract=off -fimplicit-none)
  elseif(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
    target_compile_options(${target} PRIVATE -Kieee -Mnofma -Mrecursive -Mreentrant)
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
    target_link_options(${target} PRIVATE "LINKER:--disable-new-dtags")
  endif()
endfunction()

nci_add_worker(nci_driver nci_cpu)
if(NCI_ENABLE_OPENACC)
  nci_add_worker(nci_driver_openacc nci_openacc)
endif()
if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(NAME native_driver_protocol COMMAND "${CMAKE_COMMAND}" -E env
    "NCI_DRIVER=$<TARGET_FILE:nci_driver>" "${Python3_EXECUTABLE}" -m pytest -q -ra
    "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/driver")
  set_tests_properties(native_driver_protocol PROPERTIES TIMEOUT 120)
endif()
