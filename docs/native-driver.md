# Native CPU worker

`nci_driver INPUT.cube SETTINGS.nml OUTPUT_DIRECTORY` is the private worker behind
the offline Python CLI. The output directory must already exist. It reuses
`nci_cube_input` and calls only the three exported public C ABI entry points for
context creation, tile evaluation and destruction. `nci_abi` supplies the frozen
interoperable types; the worker explicitly packs inverse J by rows. Density and
output buffers stay alive through the synchronous call. Each created context is
destroyed once, including after a failed evaluation.

The authoritative protocol is [cli-contract.md](cli-contract.md). The worker
checks parsed binary64 geometry equality, metadata and tracked allocation
reservations before output allocation: 33*N bytes in full mode or 105*N in
diagnostic mode, 40*sum(shape), 8192 scanner bytes, atom storage, and
65536+4096*threads fixed allowance. These are tracked-array reservations, not a
whole-process RSS limit. Allocation, stream writes and closes are checked.

Little-endian IEEE binary64 fields and byte flags are created exclusively.
Real arrays are transferred through fixed 4096-byte blocks to one-byte stream
elements, preserving NaN bits even if a compiler runtime requests endian
conversion for multi-byte unformatted values. No extra whole-field copy is made.
Diagnostics are `(3,N)` and `(6,N)`, which give point-major component order on
disk. NaNs and full flag bytes are retained. The native receipt records ABI
status and union statistics without reclassifying zero-valid ABI status 3 or
numeric-failure status 4 as success. Cleanup or output errors retain the original
evaluation error. The worker never creates `SUCCESS`; Python owns final hashes,
snapshot checks and publication.

`nci_driver --build-info` emits one JSON object with compiled CMake declarations,
including the complete `NCI_BUILD_REVISION` (default `UNKNOWN`), compiler, build
type, FP assumptions and the absolute built backend path. It is a declaration,
not build authentication. Runtime assumptions remain round-to-nearest, gradual
underflow and no FMA contraction; little-endian binary64 storage is checked.

The subtree CMake target supports the root external-source build variables and
depends on the reader and CPU module-producing targets. `native_driver_protocol`
runs only tiny synthetic tests from `tests/driver` against the actual executable.
Central [status.md](status.md) owns joint acceptance. These tests do not establish
real-density accuracy, GPU execution or performance and do not create a
RESEARCH_HANDOFF.md.
