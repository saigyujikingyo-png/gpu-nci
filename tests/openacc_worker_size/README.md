# Compiled storage fixture

Configure with `NCI_ENABLE_OPENACC=ON`, `BUILD_TESTING=ON` and
`NCI_BUILD_OPENACC_WORKER_SIZE=ON` to build `nci_openacc_worker_size`.
Configuration and compilation do not execute it; it is not registered with
CTest, linked by a worker, or exported by a production library. It links the
same `nci_openacc_objects` and compiler-built CUBE reader as the optional worker.

Execution belongs to the independently reviewed, frozen, finite Sol-managed
package. The JSON reports compiled workspace, contained ledger/descriptors,
explicit launch scalars, the mirrored private context wrapper, and the positive
`reader_atom_size_bytes = storage_size(cube_atom)/8`. The package binds the
executable, backend objects, reader, source and compiler receipts before passing
that independent atom size as `NCI_CUBE_ATOM_BYTES` to the end-to-end tests.
The tests must not infer the expected atom size from a production native receipt.

The fixture rejects an exceeded fixed allowance. The ledger and descriptors
are already inside the workspace, and the wrapper belongs to F_common. Actual
kernel metadata must independently confirm the 272-byte aligned launch region
and the two 144-byte static copies; the helper's explicit scalar size alone
cannot establish those values. Runtime load constructors may occur even though
the fixture makes no backend device calls. This is storage evidence, not
offload, scientific, RSS or physical VRAM acceptance.
