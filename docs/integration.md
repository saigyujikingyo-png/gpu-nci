# Testing independent branches

The root CMake can compile sources from independently owned worktrees without
merging or copying their changes. The test record must identify each branch
commit and any dirty files. A test pass does not authorize a branch merge.

Example (replace paths with the actual checkouts):

```sh
cmake -S gpu-nci -B build-integration -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DNCI_CPU_SOURCE_DIR=/path/to/core/src/backend_cpu \
  -DNCI_IO_SOURCE_DIR=/path/to/input/src/io \
  -DNCI_ORACLE_DIR=/path/to/oracle \
  -DPython3_EXECUTABLE=/path/to/venv/bin/python
cmake --build build-integration
ctest --test-dir build-integration --output-on-failure
```

When the CPU target and independent tests both exist, CTest passes the
compiled library path through `NCI_LIBRARY`. These tests must use only
small synthetic fixtures. Report any skipped cases explicitly.

Require an independent read-only review of the code and meaningful failure
tests before promoting the first CPU milestone. Do not convert this status
into scientific acceptance of a real density file.

For the adapter/CLI milestone the original CPU and oracle now reside in the
root checkout. Add the independently owned worker, CLI and tests as follows:

```sh
cmake -S /path/to/root -B build-cli-integration -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug -DNCI_BUILD_TEST_HOOKS=ON \
  -DNCI_IO_SOURCE_DIR=/path/to/adapter/src/io \
  -DNCI_DRIVER_SOURCE_DIR=/path/to/cli/src/driver \
  -DNCI_CLI_DIR=/path/to/cli/cli \
  -DNCI_CLI_TEST_DIR=/path/to/cli/tests/cli \
  -DNCI_E2E_DIR=/path/to/e2e/tests/e2e \
  -DNCI_BUILD_REVISION="explicit clean source revisions" \
  -DPython3_EXECUTABLE=/path/to/venv/bin/python
cmake --build build-cli-integration --parallel 2
ctest --test-dir build-cli-integration -V
```

Record clean, unchanged HEAD/status for all four checkouts before and after the
run. Require real `nci_driver` and CLI end-to-end tests in the CTest inventory;
stub-worker CLI tests alone are not integration evidence. Use a fresh build
directory per compiler/configuration and preserve failures. An omitted build
revision is reported as UNKNOWN. Build metadata is a declaration, not a signed
attestation of the source-to-binary relationship.

For M2 use the root's merged reader and additionally bind the separate core and
independent oracle. The exact accepted revisions are in [status](status.md):

```sh
cmake -S /path/to/root -B build-m2-debug -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug -DNCI_BUILD_TEST_HOOKS=ON \
  -DNCI_CPU_SOURCE_DIR=/path/to/core/src/backend_cpu \
  -DNCI_DRIVER_SOURCE_DIR=/path/to/runtime/src/driver \
  -DNCI_CLI_DIR=/path/to/runtime/cli \
  -DNCI_CLI_TEST_DIR=/path/to/runtime/tests/cli \
  -DNCI_ORACLE_DIR=/path/to/tests \
  -DNCI_E2E_DIR=/path/to/tests/tests/e2e \
  -DNCI_BUILD_REVISION="root:<SHA>;core:<SHA>;runtime:<SHA>;tests:<SHA>" \
  -DPython3_EXECUTABLE=/path/to/venv/bin/python
cmake --build build-m2-debug --parallel 2
ctest --test-dir build-m2-debug -V
```

Use separate fresh directories for GNU Release and NVHPC CPU Debug. Require
the new slab tests to be collected, all CLI/native/e2e checks to run without
skips, and only the documented unavailable public Jacobi-hook oracle skip.
NVHPC additionally records the unavailable binary128 CTest skip; GNU runs the
quad-reference checks. The current M2 tests require 46 CLI, 21 native-driver,
84 end-to-end and 285 oracle passes per configuration. These counts include
fixture checks and are not a count of independent scientific experiments.
