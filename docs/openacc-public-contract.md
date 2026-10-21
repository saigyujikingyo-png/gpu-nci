# M3B1: optional public OpenACC backend contract

Status: DESIGN REVIEWED; implementation compiled, native acceptance pending.
See the [preparation report](openacc-public-preparation.md) for the exact
compiled revision and outstanding diagnostic/acceptance work.
This adds a library execution path, not a new scientific method. The numerical
specification, finite-difference stencil, Jacobi limit, uncertainty meanings,
units, flags and CPU reference remain unchanged. CLI/worker selection is M3B2;
real density and performance claims require later measured acceptance.

## Build and public boundary

- Preserve the three C ABI v1 exports, structures of 40/280/88 bytes, status
  values 0..6 and backend selectors CPU=0, OpenACC=1, CUDA=2.
- Default builds retain `nci_cpu` and the existing CPU driver. Default-OFF
  `NCI_ENABLE_OPENACC` adds a separate `nci_openacc` shared library with the
  same exports, supporting CPU and OpenACC. A consumer links only one library.
- Isolate Fortran module output and include paths for the two variants.
  Compile common CAPI/validation with a build-selected `nci_acc_backend` stub
  or real implementation. CUDA stays unavailable. CPU-only option validation
  preserves its existing rejection order; any capability argument defaults
  to false. CPU selector in the optional library performs no device calls.
- Initial supported toolchain: Linux x86_64, NVHPC 26.9, CUDA 13.3, cc120.
  Use `-acc=gpu -Kieee -Mnofma`,
  `-gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc`, and compilation reports.
  All host routines must be reentrant (`-Mrecursive -Mreentrant`). Reject
  unsafe effective flags, including configuration-specific `-fast` defaults.
- Generate device annotations from actual production kinds/numerics/kernel
  sources using an insertion-only adapter outside `experiments/`. Do not copy
  formulas or change frozen M3A/M3B0 evidence. Annotate the accepted 6 kinds
  and 17 numerics procedures and pure C bindings; expose host `axis_table`
  and device `classify_point`, annotating the latter and `on_boundary`.
  Handle continued procedure declarations before inserting directives.
- GPU numeric errors use downloaded device status, rotation count and global
  point index. Never call the CPU `diagnose_point` from the OpenACC branch.

## Context and preflight

The opaque C-interoperable wrapper stores validated options and a private
workspace handle. A private scalar Fortran workspace owns all resources;
compile-check the NVHPC same-type scalar `C_LOC`/`C_F_POINTER` round trip.
No global registry, shared scratch, workspace copying or `acc_shutdown`.
Different contexts may run concurrently; one context remains caller-serialized.

Reuse common descriptor, geometry, capacity, alias, J-inverse and whole-input
density preflight. The OpenACC checked workspace plan precedes rho dereference.
No output or stats writes occur on rejected input, planning, allocation,
device-presence or downloaded-result validation failures. Errbuf retains the
existing bounded and alias-safe semantics.

The context records NVIDIA device ordinal 0. On every runtime entry (including
create, evaluation and destroy), save the calling thread's concrete device
state, reselect the recorded device, and restore the prior concrete state
before returning/committing. A previous NONE state has no valid restoration
operation; first use may leave NVIDIA 0 initialized. No global shutdown is used.
This is essential for contexts migrating sequentially between host threads.

## Checked storage

Let `B` be output X width, `Nin` supplied input points, `Nout=B*Ny*Nz`, and
`D=0` for FULL or `1` for DIAGNOSTIC. No capacity is retained between calls.
Nine host arrays have nine matching explicit device allocations and mappings:

| ID | Array | Bytes on each side |
|---|---|---:|
| 1 | copied rho | `8*Nin` |
| 2..4 | X/Y/Z neighbour tables | `40*B`, `40*Ny`, `40*Nz` |
| 5 | packed fields (3 or 12 FP64 values per point) | `(24+72*D)*Nout` |
| 6 | flags | `Nout` |
| 7..9 | point status, nrot, device marker (int32 each) | `4*Nout` each |

Thus tracked array bytes on **each** host/device side are
`8*Nin + 40*(B+Ny+Nz) + (37+72*D)*Nout`.
Check every multiply/add. Arithmetic overflow returns INVALID_ARGUMENT (1).
Each mapped object must be at most INT32_MAX bytes, because the accepted M3B0
installed runtime inspection found a 32-bit byte count in presence checking.
A larger object returns UNSUPPORTED (2) before allocation or rho dereference.
This is a supported-runtime restriction, not an invented scientific threshold.

There is no memory-budget field in ABI v1. Do not repurpose reserved fields or
borrow another project's limits. Enumerate fixed context, descriptor, ledger
and launch-scalar storage separately using actual compiled sizes. Driver pools,
allocation rounding, compiler-local scratch and process RSS are not capped by
this accounting. Later driver reservations must add caller density/outputs and
host staging, with device bytes reported separately.

## Device calculation and commit

Use explicit-shape array kernel arguments and scalar layout metadata. Every
point executes the actual production classifier and, when eligible, point_eval.
Poison staging every call with FP64 bits `7FF800000000DEAD` (distinct from
canonical QNAN_BITS `7FF8000000000000`), flags `A5`, status/nrot INT32_MIN,
and marker -1. Every output point, including
classified-invalid points, writes `acc_on_device(acc_device_nvidia)` in that
same GPU region. Classified-invalid status is -1/nrot 0; actual numerical
status is PT_OK=0 or PT failures 1..6 with nrot in 0..30.

Transfers and completion are synchronous without force-sync environment
variables. Download and validate every marker, status, nrot, flag and requested
field. Verify valid fields finite, every invalid field exactly QNAN_BITS,
no field retains poison, flags/status consistent, and marker 1. This includes
all nine diagnostic values. Derive integer stats and first failing global point from these
downloaded values. FULL does not allocate diagnostic outputs.

Before caller commit: unmap/free every device allocation and release host rho,
tables and metadata. Move remaining packed fields/flags to call-local staging,
restore the prior concrete device state, then scatter via explicit loops.
Ownership transfer is not a free: ledger tracks call-owned staging until its
actual release. Record event 11 and final zero bytes only after actual cleanup
has returned; a wrapper may observe final totals after backend return.
Completed numeric failure (4) and completed all-invalid (3) still commit fields
and stats exactly as in the existing ABI. No CPU fallback or recomputation.

Checked allocation failures return 5 after clean unwind, preserving reusable
context state. A detected marker/status mismatch returns 6 without commit after
clean unwind. Detected mapping/cleanup contradictions return 6, retain unsafe
ownership and mark the context broken. Broken handles must not be reused or
retried; destroy returns 6 rather than falsely reporting successful release.
Worker/process teardown is the boundary for these unrecoverable states and
third-party fatal runtime errors. Intrinsic/runtime failures after caller
commit cannot be promised rollback.

## Private observation interface

No additional symbols are exported from the production shared library. A
separate test executable/bridge links the **same production objects**. Private
Fortran module interfaces (not BIND(C)) are frozen for independent test authors:

- `nci_capi:test_backend_handle(context)` returns a c_ptr for a valid OpenACC
  context, otherwise null; it does not initialize a device.
- `nci_acc_backend:acc_test_configure(handle, failure_at, corruption, rc)`:
  c_ptr handle, input int32 failure_at/corruption, output int32 rc.
  failure_at=0 disables; 1..18 fails one real acquisition in documented order
  (host 1..9 then device 1..9). corruption=0 disables, 1 changes a downloaded
  marker at output index 1 to 0, 2 changes downloaded point status at output
  index 1 to INT32_MIN+1. Both controls nonzero, or an out-of-range value,
  returns rc=1 without changing controls/observations. Valid configuration
  replaces pending controls and returns rc=0. A null/non-OpenACC handle returns
  1; a broken context returns 6. Controls are consumed once when the next
  backend evaluation enters after all common preflight/plan checks. Preflight
  rejection does not consume controls. Never physical OOM or changed formulas.
- `acc_test_observe(handle, values, events, n_events, rc)`: output int64
  values(24), events(6,256); output int32 n_events/rc. No device call.
  Values are schema_version=1, call_ordinal, planned_host, planned_device,
  peak_host, peak_device, final_host, final_device, peak_maps, final_maps,
  acquisition_attempts, backend_status, output_points, kernels, upload_count,
  upload_bytes, download_count, download_bytes, first_failure_global_index,
  first_failure_status, first_failure_nrot, verified_markers, broken, event_count.
  values(3:8), values(16) and values(18) are bytes; other entries are integer
  counts/statuses/indices/booleans. Absent first failure is index=-1,status=0,
  nrot=0. backend_status is the equivalent completed public status 0/3/4,
  or checked failure 5/6. verified_markers counts all downloaded marker==1,
  independently of the later status/field validation. All byte counts include
  moved live staging. Initially schema_version=1, first_failure_index=-1 and
  other values/events zero. observe returns rc=0 for a valid OpenACC context
  (including a broken one), rc=1 for null/non-OpenACC, with zero outputs on
  invalid handle. Unused event columns are zero. Observation calls do no I/O.
- Event columns are sequence, action, buffer_id, bytes, live_host, live_device.
  Actions: host acquire=1, device acquire=2, map=3, upload=4, kernel=5,
  download=6, unmap=7, device free=8, host free=9, move to call=10,
  call-local free=11. Kernel uses buffer_id=0 and bytes=0. Check bounds; never
  truncate a ledger silently. Maps and transfers refer to live owned buffers.
  `events(:,k)` is event k; live_host/live_device are bytes. call_ordinal
  increases once on backend evaluation entry after successful common preflight
  and planning, including later allocation failures. At that entry reset other
  observations. Preflight-only rejections leave the entire previous observation
  unchanged; tests compare ordinals to distinguish these from new invocations.

Keep fixed hook storage accounted even in the production object. No public
configuration enables injection. Public shared-library acceptance is required
in addition to this private observation path; neither substitutes for the other.

## Bounded acceptance and execution

The package will freeze exact cases/counts and source/binary hashes before any
native calculation. Proposed ceiling: 512 public evaluations, two simultaneous
contexts, actual grids at most 17^3 (huge-global-X tests use small real slabs).
Required coverage includes all periodic combinations and both modes, B=1/B=3
slabs and tails, independent mathematical cases and original tolerances,
threshold/mask/subnormal/numeric-failure cases, bytewise no-write rejection,
all 18 acquisitions, marker/status corruption, context isolation, two pthread
contexts and sequential thread migration. Same-build GPU full/slab is bitwise;
CPU/GPU uses the scientific tolerance contract, not a bitwise claim.

Retain default CPU regression/ABI gates and test CPU selector in the optional
library. No-device is NOT_TESTED; attempted nonzero/timeout is FAILED. Never
convert a GPU skip into acceptance. Bind raw runtime kernel/transfer notices,
resource events and receipts to actual source/binary; concurrency allows event
interleaving while preserving each context's causal order.

Current execution instruction (2026-10-21): a GPT-6.1 Sol execution-manager
subagent automatically launches and monitors independently reviewed finite
packages under [AGENTS.md](../AGENTS.md). Retain the standalone controller,
frozen inputs/provenance, limits, stop controls, logs, exit status and separate
receipt acceptance. Further packages need their own readiness gates; no
same-attempt replay or expansion of a live run. This authorization establishes
no research result or speedup claim.

References: [NVIDIA 26.9 OpenACC guide](https://docs.nvidia.com/hpc-sdk/archive/26.9/compilers/openacc-gs/index.html),
[OpenACC 3.0 specification](https://www.openacc.org/sites/default/files/inline-images/Specification/OpenACC.3.0.pdf).
