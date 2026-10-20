# SPDX-License-Identifier: MIT
# CPU-core tests (added by src/backend_cpu/CMakeLists.txt when BUILD_TESTING).
# Every grid is synthetic and at most 17^3 points; nothing here is a
# scientific run or a benchmark.

add_library(nci_core_test_util STATIC core_test_util.c)
target_link_libraries(nci_core_test_util PUBLIC nci_contract)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(nci_core_test_util PUBLIC -Wall -Wextra -std=c11)
endif()

find_library(NCI_LIBM m)

function(nci_core_c_test name)
  add_executable(nci_core_${name} ${name}.c)
  target_link_libraries(nci_core_${name} PRIVATE nci_core_test_util nci_cpu)
  if(NCI_LIBM)
    target_link_libraries(nci_core_${name} PRIVATE ${NCI_LIBM})
  endif()
  add_test(NAME core_${name} COMMAND nci_core_${name})
  set_tests_properties(core_${name} PROPERTIES LABELS "core" TIMEOUT 300)
endfunction()

# Black-box tests through the public C ABI of the production shared library.
nci_core_c_test(test_contract)
nci_core_c_test(test_fields)
find_package(Threads)
if(Threads_FOUND)
  nci_core_c_test(test_concurrency)
  target_link_libraries(nci_core_test_concurrency PRIVATE Threads::Threads)
endif()

# C/Fortran layout cross-check against the library's own BIND(C) types.
add_executable(nci_core_test_layout test_layout.c layout_probe.f90)
target_link_libraries(nci_core_test_layout PRIVATE nci_contract nci_cpu_objects)
set_target_properties(nci_core_test_layout PROPERTIES LINKER_LANGUAGE Fortran)
if(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
  # The layout probe has a C main; suppress the driver's Fortran main stub.
  target_link_options(nci_core_test_layout PRIVATE -Mnomain)
endif()
add_test(NAME core_test_layout COMMAND nci_core_test_layout)
set_tests_properties(core_test_layout PROPERTIES LABELS "core")

# Exported symbols, FMA-free code, no STOP/I-O references.
if(CMAKE_NM AND CMAKE_OBJDUMP AND UNIX AND NOT APPLE)
  add_test(NAME core_library_inspection
           COMMAND ${CMAKE_COMMAND} -DLIB=$<TARGET_FILE:nci_cpu> -DNM=${CMAKE_NM}
                   -DOBJDUMP=${CMAKE_OBJDUMP} -DCONFIG=$<CONFIG>
                   -P ${CMAKE_CURRENT_SOURCE_DIR}/check_library.cmake)
  set_tests_properties(core_library_inspection PROPERTIES LABELS "core")
endif()

# White-box numerical tests need the test-only hooks (never part of nci_cpu).
if(NCI_BUILD_TEST_HOOKS)
  add_library(nci_cpu_test_hooks STATIC hooks/nci_test_hooks.f90)
  target_link_libraries(nci_cpu_test_hooks PUBLIC nci_cpu_objects)
  if(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
    target_compile_options(nci_cpu_test_hooks PRIVATE -Kieee -Mnofma -Mrecursive -Mreentrant)
  endif()
  add_executable(nci_core_test_eigen_portable test_eigen_portable.f90)
  target_link_libraries(nci_core_test_eigen_portable PRIVATE nci_cpu_test_hooks)
  if(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
    target_compile_options(nci_core_test_eigen_portable PRIVATE -Kieee -Mnofma)
  endif()
  add_test(NAME core_test_eigen_portable COMMAND nci_core_test_eigen_portable)
  set_tests_properties(core_test_eigen_portable PROPERTIES LABELS "core;hooks" TIMEOUT 60)

  # selected_real_kind(30) may be unsupported; only build the unchanged quad
  # reference/tests after verifying a real IEEE binary128-capable kind compiles.
  include(CheckFortranSourceCompiles)
  check_fortran_source_compiles("
program binary128_probe
  implicit none
  integer, parameter :: qp = selected_real_kind(30)
  integer, parameter :: confirmed = 1 / merge(1, 0, &
    radix(1.0_qp) == 2 .and. digits(1.0_qp) == 113 .and. &
    maxexponent(1.0_qp) == 16384 .and. storage_size(1.0_qp) == 128)
  real(qp) :: value
  value = sqrt(2.0_qp)
  if (value <= 1.0_qp .or. confirmed /= 1) stop 1
end program binary128_probe
" NCI_CORE_HAS_BINARY128 SRC_EXT F90)
  if(NCI_CORE_HAS_BINARY128)
    message(STATUS "nci_cpu: binary128 available; building original quad reference tests")
    target_sources(nci_cpu_test_hooks PRIVATE nci_ref_quad.f90)
    foreach(t IN ITEMS test_eigen test_numerics)
      add_executable(nci_core_${t} ${t}.f90)
      target_link_libraries(nci_core_${t} PRIVATE nci_cpu_test_hooks)
      if(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
        target_compile_options(nci_core_${t} PRIVATE -Kieee -Mnofma)
      endif()
      add_test(NAME core_${t} COMMAND nci_core_${t})
      set_tests_properties(core_${t} PROPERTIES LABELS "core;hooks" TIMEOUT 600)
    endforeach()
  else()
    message(STATUS "nci_cpu: binary128 UNAVAILABLE; original quad tests NOT BUILT (not passed); FP64 hooks remain")
    add_test(NAME core_binary128_unavailable COMMAND ${CMAKE_COMMAND} -E echo
      "UNAVAILABLE: binary128 quad reference tests were not built; FP64 hooks remain")
    set_tests_properties(core_binary128_unavailable PROPERTIES LABELS "core;hooks"
      SKIP_REGULAR_EXPRESSION "UNAVAILABLE: binary128")
  endif()
else()
  message(STATUS "nci_cpu: white-box Jacobi/bound tests need -DNCI_BUILD_TEST_HOOKS=ON")
endif()
