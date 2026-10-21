# M3B public OpenACC backend: implementation sequence

Base: merged M3A `34b387016e57ba4d820d2046ba8c29278f2e5784`.
This is implementation planning, not a claim that the public GPU backend exists.
The standalone M3B0 prerequisite has now passed its
[finite resource checks](openacc-resource-results.md). M3B1 implementation is in
progress under the reviewed [public-library contract](openacc-public-contract.md);
M3B2 remains unimplemented. Neither has native acceptance yet.
The science in `numerics.md`, ABI v1, CUBE conventions, masks, tolerances and
canonical X-slab contract remain unchanged.

## 1. Bounded resource gate (M3B0)

Before public dispatch, establish checked explicit host/device allocation,
private mappings, partial-failure unwind, two-context isolation and synchronous
staging on the installed NVHPC 26.9 toolchain. The standalone developer fixture
is specified in [the resource contract](openacc-resource-contract.md). This
implements the resource prerequisite already identified by M3A. It is not a
density calculation, performance benchmark or substitute for public ABI tests.

## 2. Public context and field execution (M3B1)

Keep the existing three C symbols and struct sizes (40/280/88 bytes). Use the
existing `NCI_OPENACC=1` selector; CUDA remains unavailable. Preserve default
CPU-only GNU builds and caller-owned host buffers. Common descriptor, capacity,
alias, geometry and density preflight must run before any output changes.

The opaque context owns its backend state. No shared scratch arrays, global
OpenMP policy changes, process-wide device shutdown or implicit CPU fallback.
The frozen M3B1 build adds a separate optional `nci_openacc` library alongside
the default CPU library, with isolated Fortran modules. The optional library
supports CPU/OpenACC selectors; a consumer links only one library. Worker
integration remains M3B2.

Reuse the actual production point evaluator with exact source adaptation or
reviewed device directives, rather than maintaining copied formulas. GPU
classification must preserve global boundaries, accepted negative stencils,
raw numerical fields, status and flags. Failure diagnostics must identify the
device result; host evaluation must not replace it. Stage results privately,
complete transfer/synchronization and validation, then commit caller fields
and stats. Completed numeric/all-invalid results keep their existing ABI
semantics; detectable resource/configuration failures leave caller data intact.

Freeze checked host/device workspace accounting before implementing this path.
ABI v1 has no budget field: do not repurpose reserved fields or silently change
layout. Runtime reservations must include new staging, device buffers and any
retained capacity; tracked bytes are not total process RSS or driver VRAM.
Do not reuse another project's memory limit or resize/retry automatically.

## 3. Existing CLI and X-slab integration (M3B2)

Forward an explicit `openacc` card selection through the private worker
protocol to the ABI; preserve existing CPU cards and defaults. Retain the
existing full-grid/X-slab scheduler, complete-density preflight, Z-fastest
outputs, manifest hashes and SUCCESS-last behavior. Bind receipts to the
actual selected library and GPU execution; linking alone is not offload.

Independent tests must exercise the public GPU selector, analytic/LAPACK
expectations, finite/periodic/mixed boundaries, B=1 and tail slabs, invalid
inputs, allocation failures, interleaved and concurrent distinct contexts,
synchronous commits, and worker failure without SUCCESS. Reuse current oracle
fixtures and full/slab comparison rules. CPU/GPU tolerance agreement does not
certify all bit-5 threshold cases; bit 6 remains set on valid points.

## 4. Scientific and performance packages (M4)

After public-path correctness is accepted, freeze independently sourced real
density inputs, CPU reference settings, GPU settings, finite measurements,
resource/time caps and stop conditions. A newly created GPT-6.1 Sol execution
subagent prepares each finite package and checks returned receipts; the user
manually launches it under the latest execution instruction. Report results and error
only from actual execution. Generate `RESEARCH_HANDOFF.md` after the first
accepted end-to-end scientific case. No ML, topology or Monte Carlo work is
included.

## Runtime failure boundary and roles

Keep the existing M3A distinction: NCI-detectable validation, work-allocation
and numerical failures use status/errbuf paths. Fatal third-party runtime or
platform errors may terminate the worker and must never produce accepted
success or CPU fallback. Error callbacks are not a recovery mechanism. This
does not excuse reproducible crashes on supported inputs.

Root Astra owns architecture/contracts/integration. Claude Opus 5.5 max owns
the resource implementation; GPT-6.1 Sol owns independent fixtures, verification
and bounded execution. Code authors use separate worktrees; reviews are
read-only. Standing merge authorization retains review, source-tree checks
and CI gates.
