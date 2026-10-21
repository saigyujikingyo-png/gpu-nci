# M3B2: optional OpenACC offline CLI contract

Status: contract preparation; implementation and native acceptance pending.
Base: accepted M3B1 source `e751417`, merged through PR #19. This extends the
existing offline CLI/worker, not the scientific method. Preserve ABI v1,
numerical formulas, tolerances, masks, uncertainty flags, CUBE conventions and
the [canonical X-slab contract](slab-contract.md).

## Selection, builds and compatibility

Reuse the Python CLI, one Fortran worker source, strict CUBE reader and existing
full-grid/slab scheduler. No alternative parser, field kernel or slab evaluator.
Default builds keep `nci_driver` linked only to `nci_cpu`. With
`NCI_ENABLE_OPENACC=ON`, also build `nci_driver_openacc` linked only to
`nci_openacc`. Each executable links exactly one library exporting the public
three-function ABI. The NCI_CUDA selector remains unavailable; there is no CPU fallback.

One CMake helper parameterized by target and linked library generates separate
metadata sources and Fortran module directories for each worker. Reuse the
reader built with that same compiler. Preserve strict compiler controls and
build-info encoding of exact paths/revisions. Keep default CPU builds free of
GPU dependencies. A build probe is not evidence of GPU execution.
The CLI continues to remove LD_PRELOAD and LD_LIBRARY_PATH from child environments.
Bind and inspect the optional worker's RPATH/RUNPATH and DT_NEEDED closure so it
resolves the exact backend/SDK libraries under that sanitized environment;
do not weaken the sanitizer or rely on a surrounding package's search path.

Card schema and worker protocol stay at version 1. `compute.backend` accepts
`cpu` and `openacc`. Existing CPU cards and their generated namelist bytes stay
unchanged. Add an optional namelist integer `backend`, default 0; OpenACC cards
explicitly supply 1. Reject other selectors. Worker capability checking occurs
before opening CUBE input or creating a context. The CLI requires an explicit
worker path and rejects a card/worker capability mismatch before evaluation.

New build information adds `supported_backends`: exactly `["cpu"]` for the CPU
worker or `["cpu", "openacc"]` for the optional worker. Existing seven fields
keep their meanings. An absent capability field means legacy CPU-only;
present values must equal one of those two arrays, including order and types.
Reject empty, duplicate, unknown, reordered or non-string capability entries.
Both new workers support CPU cards. A CPU selection in the optional library
retains the M3B1 distinction between no backend device calls and the shared
library's load-time runtime constructors.

## Checked host and device accounting

`memory_budget_bytes` remains a tracked **host** reservation limit. Keep the CPU
formula and behavior unchanged. For OpenACC, let:

- `G=Nx*Ny*Nz`, `P=Ny*Nz`, and `D=0` for full output or 1 for diagnostic output.
- `B=Nx` for full-grid layout; otherwise B is the declared slab width.
- `M=G` for full grids or `B*P` for slabs, and `Q=25+72*D` caller output bytes.
- `S=0` for full grids or `8*(B+4)*P` for the retained caller slab allocation,
  including finite boundaries where that allocation exceeds actual input size.
- `R=8*G+reader_atom_bytes+8192` for density, compiler-sized atoms and reader buffer.
- `F_common=65536+4096*T`, where T is the existing validated host thread count.
- `F_acc=65536` for separate fixed OpenACC host storage.

For each actual tile, use output width b, supplied input count Nin and
`Nout=b*P`. The accepted M3B1 backend arrays occupy, on **each** host/device side:

`W=8*Nin+40*(b+Ny+Nz)+(37+72*D)*Nout`.

`W_peak` is the maximum over canonical tiles. The complete host reservation is

`H_gpu=R+Q*M+S+W_peak+F_common+F_acc`.

Pass `Q*M+S+W_peak+F_common+F_acc` to the reader as its fixed reservation, with
per-point/per-axis additions zero; the reader adds R exactly once. The CLI
uses the same lower bound before atom storage is known. Derive atom bytes in
the worker with the reader's checked `natoms*storage_size(cube_atom)/8` rule.
Do not assume a platform-independent atom size or parse atoms again in Python.

Check every addition/product and the existing global count limits. Check all
nine mapped-object maxima against INT32_MAX: `8*Nin`, `40*b`, `40*Ny`, `40*Nz`,
`(24+72*D)*Nout`, `Nout`, and three objects of `4*Nout`. Refuse an unsupported
plan before CUBE allocation/evaluation; do not shrink slabs or retry.

Compute W and per-object maxima in constant time, without enumerating Nx/B:

- Full grids have `Nin=G`, including periodic X; there is no caller halo.
- A slab starting at s has `Nin=(b+4)*P` for periodic X. For finite X it has
  `Nin=[b+min(2,s)+min(2,Nx-s-b)]*P`.
- Let `f=Nx//B`. Evaluate full-width starts `0`,
  `min(ceil(2/B),f-1)*B` and `(f-1)*B`, removing duplicates, and the tail
  at `f*B` if `Nx % B != 0`. There are at most four candidates.
  Compute `ceil(2/B)` without overflowing arithmetic.

All full-width terms except the finite-X halo are constant. The halo maximum
is reached by the first tile with a complete left halo or the last full tile
if none exists; the tail is checked separately. Periodic full-width terms are
constant and tail terms cannot exceed them. Independent arithmetic fixtures
must compare this bounded calculation to explicit small-grid enumeration.

The common C context wrapper is included once in F_common (currently 56 bytes).
The separate F_acc covers workspace 14,352 bytes, one aligned launch-parameter
region 272 bytes and two static host copies totaling 288 bytes: 14,912 bytes.
The 12,480-byte ledger and 1560-byte descriptors are already inside the workspace;
172 explicit scalar bytes are already inside the aligned launch region.
Do not add those contained sizes again.

A small opt-in test fixture may link the same production objects and call the
existing private size helper. Independently bind actual compiled sizes and
static/kernel metadata, rejecting an exceeded fixed allowance before native
acceptance. This fixture is never a production-worker dependency or new public
C export. Its execution belongs to the reviewed Sol-managed package. Do not
introduce build-time candidate execution or a production private-hook API.

These are conservative tracked reservations, not bounds on RSS, driver pools,
allocation rounding, runtime scratch or physical VRAM. External process/cgroup
limits remain necessary in the finite package.

## Receipts and failure behavior

Preserve stream layout, provenance manifests, hashes, complete-density preflight,
statistics aggregation and SUCCESS-last publication. Preserve existing CPU
native receipt shape. On successful OpenACC runs, native.json additionally has
`backend="openacc"` and an exact-key `memory_plan` object:

| Field | Meaning |
|---|---|
| `host_bytes` | H_gpu, including the parsed atom reservation |
| `reader_atom_bytes` | Worker-certified nonnegative atom storage bytes |
| `device_array_bytes` | W_peak; planned arrays, not measured VRAM |
| `host_fixed_common_bytes` | F_common |
| `host_fixed_openacc_bytes` | 65536 |
| `device_static_bytes` | 288, independently bound to the compiled library |
| `launch_parameter_bytes` | 272, independently bound to compiler metadata |

All values are exact nonnegative JSON integers, never booleans or floats; their
arithmetic must fit signed int64. CLI validation recomputes card-derived terms,
checks every fixed/device term, requires `host_bytes == host_lower_bound +
reader_atom_bytes <= memory_budget_bytes`, and validates the selected backend.
Atom accounting is certified by the source-bound worker, not independently
parsed by the CLI. Nonzero-atom and exact-budget fixtures must independently
check the compiled atom size and charged bytes.

Absence of these additions is accepted only for CPU cards. For a CPU card,
reject a contradictory explicit backend or GPU memory plan. A GPU card with
missing, malformed, mismatched or underreported metadata never receives SUCCESS.
A failed native receipt may omit a plan not yet established. Fatal runtime or
worker errors preserve failure/logs and never cause fallback or accepted success.

Actual offload acceptance must bind the chosen worker and linked library to
original runtime notices and field outputs. A receipt's backend string alone
does not establish GPU execution. Preserve captured stderr without silently
ignoring unknown runtime events.
Each CLI invocation starts a fresh worker; its runtime notices are in that
output directory's `stderr.log`, not the outer pytest stderr. Freeze a new
per-worker trace policy with each process's initialization prefix and original
log receipts. The M3B1 single-Python-process/pthread policy is not reusable as-is.

## Independent validation and ownership

Keep all CPU regression and GNU binary128 gates. Adapt exact build-info key and
all-values-string assertions for the new capability array, and retain a legacy
seven-field CPU fixture.
Cover both output modes, finite/periodic/mixed boundaries, full grids, B=1 and
tail slabs, analytic/LAPACK fixtures, unchanged invalid-input outputs, checked
overflow/per-object limits, memory-bound refusal, malformed receipt/capability
metadata, worker mismatch and worker failure without SUCCESS. Full/slab equality
and CPU/GPU numerical tolerances retain their existing distinct contracts.

Root owns this contract/integration. Claude Opus 5.5 max owns worker/build and
checked host-memory adaptation in one separate worktree. GPT-6.1 Sol owns CLI
validation/receipt integration in another; an independent Sol test author owns
end-to-end fixtures. Authors do not edit each other's checkouts. Read-only
cross-review precedes integration; complete-source validation and current-head
CI precede main. GPT-6.1 Sol prepares/manages each independently reviewed frozen
finite package under [AGENTS.md](../AGENTS.md), with no replay or live expansion.

M4 real-density provenance, scientific comparisons and performance follow M3B2
acceptance. Generate RESEARCH_HANDOFF.md only after the first accepted real
end-to-end scientific case. No ML, topology or Monte Carlo feature is introduced.
