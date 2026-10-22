# Optional OpenACC library `nci_openacc` (M3B1)

Contract: [openacc-public-contract.md](../../docs/openacc-public-contract.md).
Status: **implemented; finite synthetic native validation independently accepted.**
The [M3B1 results](../../docs/openacc-public-results.md) bind the exact tested
source and actual GPU evidence. Offline CLI integration, real-density scientific
acceptance and performance measurements remain pending.
The numerical specification, formulas, ABI v1 layouts, statuses,
flags and CPU library behaviour are unchanged.

## Build

Default builds are unchanged and do not need NVHPC. `-DNCI_ENABLE_OPENACC=ON`
additionally builds `<build>/openacc/libnci_openacc.so`; it is accepted only
with NVHPC nvfortran 26.9 on Linux x86_64 and a single-configuration
generator. Configure rejects user or configuration flags containing `fast`
(CMake's NVHPC Release defaults), `-Mfma`, `-Mfprelaxed`, `-Mfpapprox`,
`-Mflushz`, `-Mdaz`, `-Knoieee` or any `-acc`, `-gpu`, `-ta`, `-cuda`, `-mp`,
`-stdpar`, `-Mcuda`, `-cudalib`, `-Mx`/`-My` option. The OpenACC objects use

```text
-acc=gpu -Kieee -Mnofma -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc
-Mrecursive -Mreentrant -Minfo=accel        (report: compilation only)
```

plus the root `-Kieee -Mnofma` and, with `NCI_ENABLE_OPENMP`, host OpenMP
(`-mp`) for the CPU selector and the common density preflight. Fortran
preprocessing is off except for the generated `nci_kernel.f90`,
`nci_acc_backend.f90` and `nci_capi.f90`, whose only conditionals are the
`NCI_BENCHMARK` blocks of the private P1 timing objects (undefined here, so
they compile the original statements). `compile_commands.json` lists these
objects.

```sh
cmake -S . -B /new/build -G Ninja -DNCI_ENABLE_OPENACC=ON \
  -DCMAKE_Fortran_COMPILER=/path/to/nvhpc-26.9/nvfortran \
  -DPython3_EXECUTABLE=/path/to/python
cmake --build /new/build --parallel 2
```

## Libraries, objects and modules

| Target | Sources | Modules |
|---|---|---|
| `nci_cpu` (default) | production CPU sources + `nci_acc_backend_stub.f90` | `<build>/cpu/modules` |
| `nci_openacc_objects` (OBJECT) | generated kinds/numerics/kernel, production abi/validate/capi, `nci_acc_backend.f90` | `<build>/openacc/modules` |
| `nci_openacc` (SHARED) | the objects above | same |
| `nci_openacc_bench_objects` (OBJECT, `NCI_BUILD_BENCHMARKS` only) | the same list with `NCI_BENCHMARK`, plus `src/benchmark/core` | `<build>/openacc/bench_modules` |

The private P1 timing variant is described in
[src/benchmark/core/README.md](../benchmark/core/README.md); `nci_openacc`,
its tests and the worker never use those objects.

Both libraries export exactly `nci_context_create_v1`,
`nci_eval_tile_f64_v1` and `nci_context_destroy_v1`; a consumer links one.
The NVHPC OpenACC link adds its own named version node
(`compilers/lib/nvhpcloc.ld`), so `nci_openacc.map` names its node
`NCI_ABI_V1`: the three functions are versioned `@@NCI_ABI_V1` and the
dynamic table also holds the version-definition entries `NCI_ABI_V1` and
`VERSION_1810`. Each object/library target propagates its module directory
as an include path. `nci_openacc_objects` keeps this fixed name for the
private test bridge, which must link these same objects; its interface also
carries the Fortran OpenACC compile options and the device-link options.

The stub sets `ACC_BACKEND_COMPILED = .false.`, so `check_options` rejects
`NCI_OPENACC` exactly as before (status 6, same order and message) and no
stub entry is reachable through the C ABI. In `nci_openacc`, CPU contexts never
call the backend module. NVHPC's own load-time constructors of the shared
library (link-mode and device-image registration) are outside this code.

## Device adaptation

`generate_device_sources.py` runs at build time on the production
`nci_kinds.f90`, `nci_numerics.f90` and `nci_kernel.f90` of
`NCI_CPU_SOURCE_DIR` and writes into `<build>/openacc/generated` only. It
inserts `!$acc routine seq` into the pure `scalbn` and `cbrt` binding
interfaces, the 6 kinds and 17 numerics procedures, `on_boundary` and
`classify_point` (after its complete continued header), and the line
`public :: axis_table, classify_point`: 7 + 18 + 3 lines. Exact anchors and
frozen procedure lists are required; deleting the inserted lines must give
back the original bytes. Each file has a unified diff; `SHA256SUMS` and
`manifest.json` record input, output and generator hashes. Any drift writes
nothing and fails the build. The frozen M3A adapter is not used or changed.

## OpenACC evaluation

The common C API keeps its validation order: context (a broken context is
refused here), tile header, pointers, mode rules, geometry/capacities,
J inverse and aliasing. For an OpenACC context it then plans the nine
objects **before rho is read**, runs the common whole-input density
preflight and calls the backend. None of these checks, nor a rejection by
any of them, changes the private observation, the call ordinal or pending
test controls; the backend evaluation entry is the first point that does.

| Id | Object (host array = device allocation, mapped) | Bytes on each side |
|---:|---|---|
| 1 | copied rho | `8*Nin` |
| 2-4 | X/Y/Z neighbour tables from production `axis_table` | `40*B`, `40*Ny`, `40*Nz` |
| 5 | packed fields per point: rdg, signed rho, lambda2 (+ grad xyz, hess xx,yy,zz,xy,xz,yz) | `24*Nout` FULL, `96*Nout` DIAGNOSTIC |
| 6 | flags (int8) | `Nout` |
| 7-9 | point status, nrot, device marker (int32) | `4*Nout` each |

Every product and sum is checked (overflow: status 1); an object above
2147483647 bytes, the 32-bit count found by M3B0 in the installed
`acc_is_present`, returns 2. Nothing is retained between calls.

0. Backend evaluation entry: call ordinal + 1, observation reset with the
   planned values, pending test controls consumed (see the private test
   interface below).
1. Select NVIDIA device 0 (below). Acquire host arrays 1..9, then for each
   id 1..9 `acc_malloc` (null-checked), `acc_map_data`, `acc_is_present`.
2. Copy rho, build the tables, upload 1..4; poison and upload 5..9 (fields
   quiet NaN bits `7FF800000000DEAD`, distinct from the canonical
   `QNAN_BITS` `7FF8000000000000`; flags bit pattern `A5`; status and nrot
   INT32_MIN; marker -1).
3. One `parallel loop collapse(3) default(none)` with `present` arrays and
   scalar launch values (no implicit data movement in the compiler report).
   Every point writes `acc_on_device(acc_device_nvidia)` as its marker in
   that region, runs production `classify_point` and, when the flags are 0,
   `point_eval`: classified-invalid points get status -1, nrot 0 and the
   canonical NaN `7FF8000000000000`; evaluated points get their status 0..6
   and nrot, and fields (status 0) or canonical NaN.
4. Poison the host copies again, download 5..9, validate every point:
   marker 1 and either status -1 with flags 1..15, nrot 0 and every
   requested field exactly `QNAN_BITS`; or status 0 with flags 64/96, nrot
   0..30 and every requested field finite; or status 1..6 with flags 16,
   nrot 0..30 and every requested field exactly `QNAN_BITS`. Requested
   fields are 3 (FULL) or all 12 (DIAGNOSTIC, including the nine gradient
   and Hessian values), so a retained poison value is always rejected.
   Counts come from the downloaded flags; the first numeric failure is its
   downloaded status, nrot and global index (`diagnose_point` is never
   called on this path).
5. Unmap and free devices 9..1 (a mapping counts as removed, and is
   recorded, only after `acc_is_present` confirmed its absence while the
   host array is still live), free host 9,8,7,4,3,2,1, move fields and flags
   to call-local staging, restore the caller's device selection and scatter
   into the caller arrays with explicit loops. The staging arrays are
   unsaved locals of the committing routine: they are released by its
   automatic deallocation on return (compiled as `pgf90_dealloc03a_i8`
   without STAT on its only exit), which has no returning failure; a
   failure there would be a fatal runtime error. Only after that routine has
   returned are the two call-local frees recorded and the final totals
   (zero) taken. The C API writes the stats afterwards; completed statuses
   0/3/4 keep their ABI meaning. No status 6 can follow the scatter.

| Case | Status | Caller outputs/stats | Context |
|---|---|---|---|
| Plan overflow / object too large | 1 / 2 | untouched, rho unread | reusable |
| No NVIDIA device, device 0 not selectable | 6 | untouched | reusable |
| Allocation failure (real or injected) | 5 | untouched, clean unwind | reusable |
| Downloaded result rejected | 6 | untouched, clean unwind | reusable |
| Presence contradiction, host deallocation failure | 6 | untouched | broken |
| Completed | 0 / 3 / 4 | fields, flags, stats | reusable |
| Destroy: workspace deallocation failure | 6 | - | broken, handle kept valid |

A broken context keeps everything it still owns and refuses every later
evaluation and destroy with 6; process/worker teardown is the boundary. A
presence contradiction keeps the contradicted mapping counted (a map whose
presence is not confirmed stays counted as mapped; an unmap whose absence is
not confirmed is not recorded) together with every allocation not yet
released. Destroy never clears the workspace magic before its deallocation:
if that deallocation fails, the C API keeps the context and its workspace
as a valid broken context. Fatal runtime errors are not contained (no error
callback); there is no CPU fallback or recomputation. Create returns 6
without an NVIDIA device and 5 if the workspace cannot be allocated.

**Device selection.** Create, every evaluation and destroy save the calling
thread's device type/number, select NVIDIA device 0 and check the selection,
and restore the saved state when it was concrete (not NONE, DEFAULT or
NOT_HOST) before returning or committing; a NONE state has no restoration
and may leave NVIDIA 0 selected. `acc_init`/`acc_shutdown` are never called.

**State.** No module variables; one private scalar workspace per context,
reached through `C_LOC`/`C_F_POINTER` of the same non-interoperable type.
Distinct contexts may run concurrently; one context is caller-serialized.
NVHPC's default-initialization template of the workspace type is static
zero storage that the code only reads.

## Private test interface (not BIND(C), not exported)

- `nci_capi:test_backend_handle(context)` returns the workspace `c_ptr` of a
  live OpenACC context (broken included), otherwise null; no device call.
- `nci_acc_backend:acc_test_configure(handle, failure_at, corruption, rc)`:
  `failure_at` 0 or 1..18 (host 1..9, device 1..9); `corruption` 0, 1 (the
  downloaded marker at output index 1, the first output point, set to 0)
  or 2 (the downloaded point status at output index 1 set to
  INT32_MIN+1). rc 1 for a null/non-OpenACC handle, rc 6 for a broken
  context, then rc 1 for an out-of-range value or for both controls nonzero;
  each of these changes nothing. Otherwise the pair replaces the pending
  controls (0, 0 clears them) and rc is 0.
- `acc_test_observe(handle, values(24), events(6,256), n_events, rc)`: no
  device call, no I/O; rc 0 for a valid OpenACC context, broken included;
  rc 1 with every output zero for a null/non-OpenACC handle. Unused event
  columns are zero.
- In `nci_cpu` the stub hooks return rc 1 with zero outputs (no handle can
  be an OpenACC context there).

**Observation lifetime.** A new workspace starts with schema_version 1,
call_ordinal 0, first failure index -1 and every other value (backend
status included) and every event zero. Only the backend evaluation entry,
reached after the common preflight and the checked plan have passed,
changes it: call_ordinal + 1, every other value and event reset, planned
bytes and output points set, pending controls consumed (once, whatever the
evaluation's outcome, allocation failures included). Every earlier rejection
(broken context, descriptors, pointers, geometry, J inverse, aliasing, plan
overflow or size, density) leaves the entire previous observation, the
ordinal and pending controls unchanged; tests distinguish these calls by
the ordinal. A broken context keeps the observation of the call that broke
it; value 23 always reports the current broken state.

| # | Value | # | Value |
|---:|---|---:|---|
| 1 | schema_version = 1 | 13 | output_points (Nout) |
| 2 | call_ordinal of this context | 14 | kernels |
| 3, 4 | planned host/device bytes | 15, 16 | upload count, bytes |
| 5, 6 | peak live host/device bytes | 17, 18 | download count, bytes |
| 7, 8 | live host/device bytes when the backend returned | 19 | first numeric failure global index, -1 if none |
| 9, 10 | peak / final live mappings | 20, 21 | its downloaded status and nrot (0 if none) |
| 11 | acquisition attempts 0..18 | 22 | downloaded markers equal to 1, counted over all points before validation |
| 12 | backend status: completed 0/3/4 or checked failure 5/6 | 23, 24 | broken (0/1), events recorded |

Values 3-8, 16 and 18 are bytes; the others are counts, statuses, indices
or booleans. Every byte count includes moved call-local staging until its
release has been confirmed.

Event columns: sequence, action, buffer id, bytes, live host bytes and live
device bytes after the event; `events(:,k)` is event k. Host bytes include
call-local staging; moving to staging is not a free. Actions: host acquire
1, device acquire 2, map 3, upload 4, kernel 5 (id 0, bytes 0), download 6,
unmap 7, device free 8, host free 9, move to call 10, call-local free 11. A
failed acquisition has no event (see value 11). An event beyond 256 would
not be stored but still counted in value 24, so the truncation would show
as value 24 > n_events; at most 71 events occur. Sequences:

- Completed (71 events): host acquire 1..9; device acquire, map for 1..9;
  upload 1..9; kernel; download 5..9; unmap, device free for 9..1; host free
  9,8,7,4,3,2,1; move 5, 6; call-local free 5, 6 (recorded after the
  committing routine has returned).
- Acquisition f = 1..9 fails: host acquire 1..f-1, host free f-1..1.
- Acquisition 9+k fails (k = 1..9): host acquire 1..9; device acquire, map
  for 1..k-1; unmap, device free for k-1..1; host free 9..1.
- Rejected device result (69 events): the first 42 completed events, then
  unmap, device free for 9..1 and host free 9..1.
- Presence contradiction (broken): the events up to the map of the
  unconfirmed object, or up to the last confirmed release; nothing after.

**Fixed storage and launch metadata** (outside the nine tracked objects).
`acc_fixed_storage(bytes(4))` (supplementary, not part of the frozen
interface) reports from compiled sizes: one workspace, its observation
arrays (12480 bytes), its nine array descriptors and the 172 bytes of kernel
launch scalars. The C API context wrapper is 56 bytes (int64 magic, 40-byte
options, pointer). The kernel receives all of its metadata by value in its
launch parameters (272 bytes, 36 parameters in the NVHPC 26.9 cc120
binary): the nine present device addresses; the launch scalars, i.e. the
layout (Nin, B, Ny, Nz, field count, Nout, Nx, x0 as int64), the nine
J-inverse matrix entries, the underflow floor and rho_min (FP64) and the
periodicity and mode flags (three periodic flags, has_negative, diagnostic
as 4-byte logicals); and three compiler-generated 8-byte values plus
alignment padding. The compilation report shows only `present` for the nine
arrays and implicit `private` loop indices: no implicit copy of metadata.
The stencil offsets are not transferred: every thread builds them with the
production `stencil61` from two constant tables in the device image
(`__staticinit_nci_numerics_stencil61_` 88 bytes and
`__staticinit_nci_numerics_mixed_` 16 bytes, `.nv.global.init`), loaded
with the module, not per evaluation. Compiler thread scratch is the device
stack of 3656 bytes per thread (142 registers) reported for that binary.
Driver pools and stack reservations, allocation rounding, compiler scratch
and process RSS are outside this accounting; ABI v1 has no memory budget.

## Not established

Everything at run time: device execution, marker/transfer behaviour, actual
`acc_malloc` failure (the runtime may terminate instead of returning null),
actual host deallocation failures (checked or automatic: only their code
paths are compiled), thread-safety of the NVHPC runtime for concurrent
contexts, effects of the library's load-time constructors, device stack
requirements, and numerical agreement with the CPU library. FP64 division
and square root on the device
are correctly rounded ptxas expansions that use DFMA internally, and the
vendor `cbrt` uses FMA internally (as in M3A); production arithmetic itself
is emitted as non-contractible `mul.rn`/`add.rn`.
