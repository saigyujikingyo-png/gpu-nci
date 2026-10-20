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
