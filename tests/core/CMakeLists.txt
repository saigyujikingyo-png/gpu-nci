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
  add_library(nci_cpu_test_hooks STATIC hooks/nci_test_hooks.f90 nci_ref_quad.f90)
  target_link_libraries(nci_cpu_test_hooks PUBLIC nci_cpu_objects)
  foreach(t IN ITEMS test_eigen test_numerics)
    add_executable(nci_core_${t} ${t}.f90)
    target_link_libraries(nci_core_${t} PRIVATE nci_cpu_test_hooks)
    add_test(NAME core_${t} COMMAND nci_core_${t})
    set_tests_properties(core_${t} PROPERTIES LABELS "core;hooks" TIMEOUT 600)
  endforeach()
else()
  message(STATUS "nci_cpu: white-box Jacobi/bound tests need -DNCI_BUILD_TEST_HOOKS=ON")
endif()
