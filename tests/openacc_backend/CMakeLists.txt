# SPDX-License-Identifier: MIT
# Parent opt-in integration only. Never register a native GPU test in CPU CI.
if(NOT TARGET nci_openacc_objects OR NOT TARGET nci_openacc)
  message(FATAL_ERROR "openacc_backend tests require the real optional library and its exact objects")
endif()
add_library(nci_openacc_test_bridge SHARED bridge.f90)
target_link_libraries(nci_openacc_test_bridge PRIVATE nci_openacc_objects nci_contract)
set_target_properties(nci_openacc_test_bridge PROPERTIES
  Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/bridge_modules")
if(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
  target_compile_options(nci_openacc_test_bridge PRIVATE -Kieee -Mnofma -Mrecursive -Mreentrant)
  target_link_options(nci_openacc_test_bridge PRIVATE -acc=gpu
    -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc)
endif()
find_package(Threads REQUIRED)
add_executable(nci_openacc_test_threads test_threads.c thread_runtime.f90)
target_link_libraries(nci_openacc_test_threads PRIVATE nci_openacc nci_contract Threads::Threads ${CMAKE_DL_LIBS})
set_target_properties(nci_openacc_test_threads PROPERTIES LINKER_LANGUAGE Fortran)
if(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
  target_compile_options(nci_openacc_test_threads PRIVATE
    "$<$<COMPILE_LANGUAGE:Fortran>:-acc=gpu;-Kieee;-Mnofma;-Mrecursive;-Mreentrant>")
  target_link_options(nci_openacc_test_threads PRIVATE -Mnomain -acc=gpu
    -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc)
endif()
if(UNIX)
  target_link_libraries(nci_openacc_test_threads PRIVATE m)
endif()
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(nci_openacc_test_threads PRIVATE
    "$<$<COMPILE_LANGUAGE:C>:-std=c11;-Wall;-Wextra;-Werror>")
endif()
# Runtime selection is a user-launched frozen package, not CTest discovery.
