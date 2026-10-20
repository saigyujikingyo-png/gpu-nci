find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_test(NAME cli_end_to_end
  COMMAND "${CMAKE_COMMAND}" -E env
    "NCI_DRIVER=$<TARGET_FILE:nci_driver>"
    "NCI_CLI=${NCI_CLI_DIR}/nci_cli.py"
    "${Python3_EXECUTABLE}" -m pytest -q -ra "${CMAKE_CURRENT_SOURCE_DIR}")
set_tests_properties(cli_end_to_end PROPERTIES TIMEOUT 180)
