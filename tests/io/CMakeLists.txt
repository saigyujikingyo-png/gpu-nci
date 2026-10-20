find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_executable(nci_cube_probe cube_probe.f90)
target_link_libraries(nci_cube_probe PRIVATE nci_cube_input)
add_executable(nci_cube_lifecycle cube_lifecycle.f90)
target_link_libraries(nci_cube_lifecycle PRIVATE nci_cube_input)
add_test(NAME cube_input_native_lifecycle
  COMMAND nci_cube_lifecycle "${CMAKE_CURRENT_BINARY_DIR}/lifecycle_synthetic.cube")
add_test(NAME cube_input_synthetic
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_cube_input.py"
    "$<TARGET_FILE:nci_cube_probe>" "${CMAKE_CURRENT_BINARY_DIR}/synthetic")
