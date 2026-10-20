# Thin executable adapter; sources can come from a separate worktree.
if(NOT TARGET nci_cpu OR NOT TARGET nci_cube_input)
  message(FATAL_ERROR "nci_driver needs nci_cpu and nci_cube_input targets")
endif()
if(NOT DEFINED NCI_BUILD_REVISION)
  set(NCI_BUILD_REVISION "UNKNOWN")
endif()

# Encode metadata as byte-valued ACHAR expressions. This preserves quotes,
# control characters and long composite revision declarations without truncation.
include("${CMAKE_CURRENT_SOURCE_DIR}/build-string.cmake")
set(_nci_metadata "module nci_driver_build\nimplicit none\ncontains\n")
nci_build_string(build_revision "${NCI_BUILD_REVISION}")
nci_build_string(build_compiler_id "${CMAKE_Fortran_COMPILER_ID}")
nci_build_string(build_compiler_version "${CMAKE_Fortran_COMPILER_VERSION}")
nci_build_string(build_type "${CMAKE_BUILD_TYPE}")
nci_build_string(build_fp_policy "IEEE binary64; round-to-nearest; gradual underflow; no FMA contraction")
string(APPEND _nci_metadata "end module\n")
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/nci_driver_build.f90" CONTENT "${_nci_metadata}")
# Resolve TARGET_FILE first, then run the same byte encoder at build time.
# Never inject a path as a Fortran literal, even if it contains quotes/newlines.
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/backend-path.txt" CONTENT "$<TARGET_FILE:nci_cpu>")
add_custom_command(OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/nci_driver_backend.f90"
  COMMAND "${CMAKE_COMMAND}"
    "-DINPUT_FILE=${CMAKE_CURRENT_BINARY_DIR}/backend-path.txt"
    "-DOUTPUT_FILE=${CMAKE_CURRENT_BINARY_DIR}/nci_driver_backend.f90"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/backend-metadata.cmake"
  DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/backend-path.txt"
    "${CMAKE_CURRENT_SOURCE_DIR}/backend-metadata.cmake" "${CMAKE_CURRENT_SOURCE_DIR}/build-string.cmake"
  VERBATIM)
add_executable(nci_driver "${CMAKE_CURRENT_BINARY_DIR}/nci_driver_build.f90"
  "${CMAKE_CURRENT_BINARY_DIR}/nci_driver_backend.f90" nci_driver.f90)
target_link_libraries(nci_driver PRIVATE nci_cpu nci_cube_input)
target_include_directories(nci_driver PRIVATE "${CMAKE_Fortran_MODULE_DIRECTORY}")
add_dependencies(nci_driver nci_cpu_objects nci_cube_input)
if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
  target_compile_options(nci_driver PRIVATE -ffp-contract=off -fimplicit-none)
elseif(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
  target_compile_options(nci_driver PRIVATE -Kieee -Mnofma -Mrecursive -Mreentrant)
endif()
if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_test(NAME native_driver_protocol COMMAND "${CMAKE_COMMAND}" -E env
    "NCI_DRIVER=$<TARGET_FILE:nci_driver>" "${Python3_EXECUTABLE}" -m pytest -q -ra
    "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/driver")
  set_tests_properties(native_driver_protocol PROPERTIES TIMEOUT 120)
endif()
