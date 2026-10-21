# Optional OpenACC library `nci_openacc` (M3B1)

Contract: [openacc-public-contract.md](../../docs/openacc-public-contract.md).
Status: **implemented and compile/link-checked only.** No test, library,
device kernel, benchmark or real-density case has been run from this code:
GPU offload, test acceptance, scientific acceptance and performance are all
`NOT_RUN`. The numerical specification, formulas, ABI v1 layouts, statuses,
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
preprocessing is off and `compile_commands.json` lists these objects.

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
preflight and calls the backend.

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

1. Select NVIDIA device 0 (below). Acquire host arrays 1..9, then for each
   id 1..9 `acc_malloc` (null-checked), `acc_map_data`, `acc_is_present`.
2. Copy rho, build the tables, upload 1..4; poison and upload 5..9 (fields
   quiet NaN `7FF8000000000BAD`, flags -1, status/nrot/marker INT32_MIN).
3. One `parallel loop collapse(3) default(none)` with `present` arrays and
   scalar launch values (no implicit data movement in the compiler report).
   Every point writes `acc_on_device(acc_device_nvidia)` as its marker in
   that region, runs production `classify_point` and, when the flags are 0,
   `point_eval`: classified-invalid points get status -1, nrot 0 and the
   canonical NaN `7FF8000000000000`; evaluated points get their status 0..6
   and nrot, and fields (status 0) or canonical NaN.
4. Poison the host copies again, download 5..9, validate every point:
   marker 1 and either status -1 with flags 1..15, nrot 0, NaN fields; or
   status 0 with flags 64/96, nrot 0..30, finite fields; or status 1..6 with
   flags 16, nrot 0..30, NaN fields. Counts come from the downloaded flags;
   the first numeric failure is its downloaded status, nrot and global index
   (`diagnose_point` is never called on this path).
5. Unmap (absence queried while the host array is live) and free devices
   9..1, free host 9,8,7,4,3,2,1, move fields and flags to call-local
   staging, restore the caller's device selection, scatter into the caller
   arrays with explicit loops, then free the staging. The C API writes the
   stats afterwards; completed statuses 0/3/4 keep their ABI meaning.

| Case | Status | Caller outputs/stats | Context |
|---|---|---|---|
| Plan overflow / object too large | 1 / 2 | untouched, rho unread | reusable |
| No NVIDIA device, device 0 not selectable | 6 | untouched | reusable |
| Allocation failure (real or injected) | 5 | untouched, clean unwind | reusable |
| Downloaded result rejected | 6 | untouched, clean unwind | reusable |
| Presence contradiction, host deallocation failure | 6 | untouched | broken |
| Staging release failure after the scatter | 6 | already written | broken |
| Completed | 0 / 3 / 4 | fields, flags, stats | reusable |

A broken context keeps everything it still owns and refuses every later
evaluation and destroy with 6; process/worker teardown is the boundary.
Fatal runtime errors are not contained (no error callback); there is no CPU
fallback or recomputation. Create returns 6 without an NVIDIA device and 5
if the workspace cannot be allocated.

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
  `failure_at` 0 or 1..18 (host 1..9, device 1..9) and `corruption` 0, 1
  (marker of the first output point set to 0) or 2 (its status: 0 becomes
  -1, anything else 0) are both consumed by the next backend evaluation.
  rc 0, 1 for an invalid handle or value, 6 for a broken context.
- `acc_test_observe(handle, values(24), events(6,256), n_events, rc)`: no
  device call; rc 0, or 1 with zero outputs for an invalid handle.
  The stub returns 6 and zeros from both.

The observation is reset at the start of every evaluation call on a live,
non-broken context; a broken context keeps the observation of the call that
broke it.

| # | Value | # | Value |
|---:|---|---:|---|
| 1 | schema_version = 1 | 13 | output_points (Nout; 0 before planning) |
| 2 | call_ordinal of this context | 14 | kernels |
| 3, 4 | planned host/device bytes (0 after overflow) | 15, 16 | upload count, bytes |
| 5, 6 | peak live host/device bytes | 17, 18 | download count, bytes |
| 7, 8 | live host/device bytes when the backend returned | 19 | first numeric failure global index, -1 if none |
| 9, 10 | peak / final live mappings | 20, 21 | its downloaded status and nrot (0 if none) |
| 11 | acquisition attempts 0..18 | 22 | downloaded markers equal to 1 |
| 12 | backend evaluation status; -1 if the call ended before it | 23, 24 | broken (0/1), events recorded |

Event columns: sequence, action, buffer id, bytes, live host bytes and live
device bytes after the event. Host bytes include call-local staging; moving
to staging is not a free. Actions: host acquire 1, device acquire 2, map 3,
upload 4, kernel 5 (id 0, bytes 0), download 6, unmap 7, device free 8,
host free 9, move to call 10, call-local free 11. A failed acquisition has
no event (see value 11). Events beyond 256 are counted in value 24, never
silently dropped. Sequences:

- Completed (71 events): host acquire 1..9; device acquire, map for 1..9;
  upload 1..9; kernel; download 5..9; unmap, device free for 9..1; host free
  9,8,7,4,3,2,1; move 5, 6; call-local free 5, 6.
- Acquisition f = 1..9 fails: host acquire 1..f-1, host free f-1..1.
- Acquisition 9+k fails (k = 1..9): host acquire 1..9; device acquire, map
  for 1..k-1; unmap, device free for k-1..1; host free 9..1.
- Rejected device result (69 events): the first 42 completed events, then
  unmap, device free for 9..1 and host free 9..1.

`acc_fixed_storage(bytes(4))` (supplementary, not part of the frozen
interface) reports from compiled sizes: one workspace, its observation
arrays (12480 bytes), its nine array descriptors and the kernel launch
scalars. The C API context wrapper is 56 bytes (int64 magic, 40-byte
options, pointer). Driver pools, allocation rounding, compiler scratch and
process RSS are outside this accounting; ABI v1 has no memory budget.

## Not established

Everything at run time: device execution, marker/transfer behaviour, actual
`acc_malloc` failure (the runtime may terminate instead of returning null),
thread-safety of the NVHPC runtime for concurrent contexts, effects of the
library's load-time constructors, device stack requirements, and numerical
agreement with the CPU library. FP64 division and square root on the device
are correctly rounded ptxas expansions that use DFMA internally, and the
vendor `cbrt` uses FMA internally (as in M3A); production arithmetic itself
is emitted as non-contractible `mul.rn`/`add.rn`.
