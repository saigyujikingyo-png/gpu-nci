# Native CPU worker

`nci_driver INPUT.cube SETTINGS.nml OUTPUT_DIRECTORY` is the private worker behind
the offline Python CLI. The output directory must already exist. It reuses
`nci_cube_input` and calls only the three exported public C ABI entry points for
context creation, tile evaluation and destruction. `nci_abi` supplies the frozen
interoperable types; the worker explicitly packs inverse J by rows. Density and
output buffers stay alive through the synchronous call. Each created context is
destroyed once, including after a failed evaluation.

The authoritative protocols are [cli-contract.md](cli-contract.md) and the
[X-slab extension](slab-contract.md). The worker
checks parsed binary64 geometry equality, metadata and tracked allocation
reservations before output allocation. Full-grid layout retains 33*N bytes in full mode or 105*N in
diagnostic mode, 40*sum(shape), 8192 scanner bytes, atom storage, and
65536+4096*threads fixed allowance. These are tracked-array reservations, not a
whole-process RSS limit. Allocation, stream writes and closes are checked.

Old namelists default to layout_mode=0 and slab_planes=0. Slab mode requires
layout_mode=1 and 1..Nx planes. With P=Ny*Nz, B=requested planes, Q=25 for full
output or 97 for diagnostic, and T=threads, its tracked reservation is:

`8*N + 8*(B+4)*P + Q*B*P + 40*(B+Ny+Nz) + 8192 + atom_bytes + 65536 + 4096*T`.

Each addition/product is checked before the reader allocates density or atoms.
The extra slab/table/fixed allowance is passed through reserve_fixed_bytes;
per-point/per-axis reader reservations are zero for this layout. Complete rho
is read and metadata-validated before the first slab evaluation or raw-field creation.
One slab input is packed from that immutable array, wrapping global X planes for
periodic halos or clipping at finite boundaries. Field arrays hold only B*P
points; the tail writes only its actual output extent.

Little-endian IEEE binary64 fields and byte flags are created exclusively.
Real arrays are transferred through fixed 4096-byte blocks to one-byte stream
elements, preserving NaN bits even if a compiler runtime requests endian
conversion for multi-byte unformatted values. No extra whole-field copy is made.
Diagnostics are `(3,Nout)` and `(6,Nout)`, which give point-major component order
on disk. Streams are opened exclusively once and slabs append in increasing
global X order. NaNs and full flag bytes are retained. Each call starts with zero
stats. A completed invalid ABI3 slab may continue only after its counts and flags
are checked; arbitrary preflight failures cannot reuse earlier stats. A wholly
invalid global result still fails with ABI3. ABI4 stops immediately after retaining
the computed slab's stats and available raw diagnostics. Failure stats count
completed computation and do not certify how many bytes were written. Counts
are added with checked arithmetic, and successful totals must cover global N
with at least one valid point and no numerical failures. The receipt schema is
unchanged. Cleanup or output errors retain the original
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
