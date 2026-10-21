find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_test(NAME openacc_cli_fixture_selfchecks
  COMMAND "${CMAKE_COMMAND}" -E env
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1"
    "PYTHONDONTWRITEBYTECODE=1"
    "${Python3_EXECUTABLE}" -m pytest -q -ra -p no:cacheprovider
    "${CMAKE_CURRENT_SOURCE_DIR}/test_pure.py")
set_tests_properties(openacc_cli_fixture_selfchecks PROPERTIES TIMEOUT 120)
