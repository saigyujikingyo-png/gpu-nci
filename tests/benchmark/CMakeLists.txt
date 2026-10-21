# Pure controls may be registered in CTest; native probes are built only and
# executed only by a separate reviewed finite qualification package.
find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_test(NAME private_benchmark_control_selfchecks
  COMMAND "${Python3_EXECUTABLE}" -B -m unittest discover
    -s "${CMAKE_CURRENT_SOURCE_DIR}" -p test_control.py -v)
set_tests_properties(private_benchmark_control_selfchecks PROPERTIES TIMEOUT 30)
if(NCI_BUILD_BENCHMARKS)
  foreach(_backend IN ITEMS nci_cpu nci_openacc)
    if(TARGET ${_backend}_bench_objects)
      set(_target "${_backend}_benchmark_test_bridge")
      add_library(${_target} SHARED bridge.f90
        "${CMAKE_CURRENT_SOURCE_DIR}/../../benchmarks/nci_benchmark_support.f90"
        "${CMAKE_CURRENT_SOURCE_DIR}/../../benchmarks/nci_benchmark_io.c")
      if(_backend STREQUAL "nci_openacc")
        target_sources(${_target} PRIVATE fault_bridge.f90)
      endif()
      target_link_libraries(${_target} PRIVATE ${_backend}_bench_objects nci_contract)
      set_target_properties(${_target} PROPERTIES
        Fortran_MODULE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/${_target}_modules")
      if(CMAKE_Fortran_COMPILER_ID STREQUAL "GNU")
        target_compile_options(${_target} PRIVATE "$<$<COMPILE_LANGUAGE:Fortran>:-ffp-contract=off;-frecursive>")
      elseif(CMAKE_Fortran_COMPILER_ID STREQUAL "NVHPC")
        target_compile_options(${_target} PRIVATE "$<$<COMPILE_LANGUAGE:Fortran>:-Kieee;-Mnofma;-Mrecursive;-Mreentrant>")
      endif()
    endif()
  endforeach()
endif()
