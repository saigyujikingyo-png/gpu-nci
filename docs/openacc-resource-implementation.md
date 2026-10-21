# M3B0 OpenACC resource gate implementation

Status: **implemented; first native attempt failed independent verification;
device-diagnostic fix NOT_YET_EXECUTED / NOT_YET_ACCEPTED.**
This is the candidate for the frozen [M3B0 contract](openacc-resource-contract.md).
It is not the public GPU backend. There is no accepted M3B0 pass,
real-data acceptance or performance claim.
Production CPU code, ABI, CLI, M3A sources/fixtures, root CMake and the
contract are unchanged.

## Source layout

`experiments/openacc_resources/` is a standalone CMake project, default OFF:

- `src/m3b_ledger.f90`: bounded per-instance event ledger. 64 events, about
  2 KiB, far below the 65536-byte cap. An event beyond the capacity is
  counted as dropped (never reset) instead of being stored.
- `src/m3b_workspace.f90`: the private workspace (`resource_workspace`).
  It owns the three host arrays, their `acc_malloc` allocations and
  mappings, the transfers and the fixture kernel.
- `src/m3b_resources.f90`: the fixed no-argument developer harness. It is
  the only code that writes anything.

Neither module has module variables, pools, caches, resizing, retries or I/O,
contains STOP, calls `acc_shutdown` or installs an error callback. Every
module procedure is `recursive`: the frozen flags omit `-Mrecursive`, under
which NVHPC kept an address-taken local in `.bss` in a feasibility object.
The built workspace object has no `.bss`. Its `.data` sections contain only
compiler-generated OpenACC/CUDA descriptors passed to the runtime.

## Runtime interfaces actually used

These were read from the installed NVHPC 26.9 `openacc.mod` and
`nvf_acc_common.mod`, then confirmed in compile-only object code:

| Fortran call | Runtime entry and argument passing |
|---|---|
| `acc_malloc(bytes)` → `type(c_devptr)` | `acc_malloc_`: hidden result pointer, `bytes` integer(8) by value |
| `acc_map_data(host, devptr, bytes)` | `acc_map_data_`: host address, address of the `c_devptr`, bytes by value |
| `acc_is_present(host, bytes)` | C `acc_is_present`: host address, bytes by value; logical result |
| `acc_unmap_data(host)` | C `acc_unmap_data`: host address |
| `acc_free(devptr)` | `acc_free_`: address of the `c_devptr` |
| `devptr == c_null_devptr` | `nvf_acc_common_compare_eq_cdevptrs_` |

For allocatable components, the host argument was the array data address,
not its descriptor. The compiler also accepted default-integer byte counts
by value conversion. The code still passes `integer(c_size_t)` everywhere.
No `c_devptr` component is accessed and no device pointer is converted to
a host pointer.

The compiled code tests the low bit of the `acc_is_present` result. A static
disassembly of the installed `libacchost.so` showed the following, so that
test is sound here:

- `acc_is_present` returns only 0 or 1.
- It reads the byte count as a 32-bit value. Here the count is at most 248.
- In separate-memory mode it searches the present table. It skips that only
  for unified mode or CUDA-managed pointers.

The workspace uses only ordinary `ALLOCATE`d host arrays.

## Workspace behavior

`m3b_prepare(ws, points, status)` accepts 1..1024 points on a labelled
instance that owns nothing. Each accepted call starts a new generation. It
acquires, in order, the host input, output and marker arrays (`ALLOCATE`
with `STAT`). Then, for input, output and marker in turn, it calls
`acc_malloc` with a null check, `acc_map_data` on the private host array, and
an actual `acc_is_present` query. Tracked bytes are 8N, 8N and 4N
(20N <= 20480 per side). Caller arrays are never mapped.

Failed acquisitions and `m3b_release` use one `unwind` routine. It touches
only acquired resources in reverse order. For marker, output and input, it
unmaps a live mapping and queries absence while the host array is still
allocated, then frees the device allocation. It then deallocates the host
marker, output and input arrays. Releasing an empty instance records nothing
and returns 0.

`m3b_inject_failure(ws, index)` accepts 0..6 and rejects other values.
The next accepted prepare consumes it. An injected host failure leaves
`stat` nonzero without allocating. An injected device failure keeps the
null `c_devptr`. Each takes the same branch and unwind as a real failure.
This models allocation failure; it does not exercise device OOM.

| Status | Meaning |
|---|---|
| 0 | success |
| 1 | invalid request; nothing changed and nothing recorded |
| 4 | device result rejected: a marker /= 1 or staging still poisoned |
| 5 | allocation failure, unwound to empty |
| 7 | presence query contradicted a completed map/unmap, or deallocation failed |

Status 7 marks the instance broken. It stops at once and keeps whatever it
still owns, so it never frees memory the runtime may still reference. Later
requests are refused. The harness then exits nonzero. Every event carries
the instance label (T, A or B) and generation, so address reuse cannot merge
two owners. PRESENT stores the actual query result.

## Execution path

`m3b_upload_input` performs one synchronous `update device`. `m3b_execute`
then does the following:

1. Fills host staging with quiet NaN `7FF8000000000BAD` and markers with 0.
2. Uploads both arrays with separate `update device` directives.
3. Runs one `parallel loop present(input, staging, marker)`. Each iteration
   writes `staging(i) = input(i) + 1` and the int32
   `acc_on_device(acc_device_nvidia)` marker.
4. Poisons the host copies again.
5. Downloads staging and markers with separate `update self` directives.

The transfer helpers and kernel take explicit-shape dummies, so no
descriptor is transferred. No construct has `async`, so each returns after
completion without environment forcing. `m3b_copy_result` writes a
distinct caller array only after those downloads, and only when every
marker is 1 and no value has the poison bits. The host never computes or
replaces an output value.

The compiler report shows `present(marker(:),staging(:),input(:))`, an
implicit firstprivate `points`, NVIDIA GPU code and one `update` per helper.
The sm_120 SASS of the kernel is `LDG.64`, `DADD +1`, a 64-bit store of the
value and a 32-bit store of the marker. It contains no FMA.

## Harness

The program takes no arguments. Before any device call, silent host assertions
check the device-property prefix helper with NUL padding, a full 256-character
buffer without NUL, leading and embedded NUL, content after the first NUL,
blank and zero-length strings, and ordinary space padding. A failed assertion
uses the existing CHECK_FAILED exit path. Successful assertions add no I/O,
device calls, transfers or protocol counts.

The program then selects NVIDIA device 0. Without such a
device it exits 3 with `M3B0_NOT_TESTED` on stderr and nothing on stdout.
It then runs exactly the contract sequence:

1. Six FAIL/RECOVER pairs on instance T at N=5 (generations 2k-1 and 2k).
2. The two caller arrays (17 and 31 binary64, 384 bytes), then A and B
   prepared and their inputs (i-9)/8 and -(i+3)/16 uploaded.
3. Cases A and B, each poisoning its caller array before execution.
4. Release A while B stays live, then B_AFTER_A_FREE from the unchanged
   device input.
5. Release B, the empty release of A, then deallocation of the caller arrays.

stdout has only the 96 protocol lines. Each record shows the observed values
and is checked after it is written, so a failure appears in the record.
INPUT_BITS comes from the uploaded host input. OUTPUT_BITS comes from the
caller copy. DEVICE is the downloaded marker.

stderr lines use these prefixes:

- `M3B0_RESOURCE`: the frozen event grammar. Events are drained after every
  prepare and release (240 expected).
- `M3B0_DEVICE`: device count, the selected index and the name, vendor and
  driver strings. Each property uses only the bounded prefix before its first
  NUL, blank-padding the remainder before applying Fortran TRIM. A property
  without NUL retains its full buffer contents before TRIM. No other diagnostic
  or runtime output is rewritten.
- `M3B0_LEDGER`: ledger bytes and dropped events per instance.
- `M3B0_TOTALS`: event, upload, download and kernel totals and bytes, peak
  objects and bytes, caller bytes and live caller arrays.
- `M3B0_REJECTED`: per-element markers of a rejected result.
- `M3B0_CHECK_FAILED`, `M3B0_NOT_ON_DEVICE`, `M3B0_NOT_TESTED`: the reason
  before a nonzero exit.

Runtime notification output (`NVCOMPILER_ACC_NOTIFY`) is interleaved on the
same stream. Each harness line is flushed when written.

The harness stops at the first unexpected result. It compares every drained
event with the expected sequence. It also checks statuses, generations, live
counts, the 6/6/6 objects and 960/960 bytes peak, and at most two live
instances. A must be empty while B still owns 3/3/3 objects and 620/620
bytes. It requires zero dropped events, ledgers of at most 65536 bytes, 8
uploads of 1332 bytes, 6 downloads of 948 bytes, 3 kernels, 79 values, 96
lines and final zero ownership. Exit status is 0 when all checks pass, 2 for
a failed check or any argument, 3 for NOT_TESTED, and 4 for a rejected
device result. Exit 0 is not acceptance: the independent verifier, runtime
trace and the execution record decide that.

## Build interface

Use a fresh single-configuration build directory. Leave `CMAKE_BUILD_TYPE`,
`CMAKE_Fortran_FLAGS` and `CMAKE_EXE_LINKER_FLAGS` empty, and enforce a
600-second limit on configure and on build:

```sh
cmake -S experiments/openacc_resources -B /path/to/new-build -G Ninja \
  -DNCI_ENABLE_OPENACC_RESOURCES=ON \
  -DCMAKE_Fortran_COMPILER=/path/to/nvhpc-26.9/nvfortran
cmake --build /path/to/new-build --parallel 2 --verbose
```

The output is `/path/to/new-build/m3b_resources`, with modules in
`modules/` and `compile_commands.json` exported. The frozen options are
`-acc=gpu -Kieee -Mnofma -gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc`,
with `-Minfo=accel` for compilation only. Preprocessing is off. Configure
and build never run the program. The bounded runner owns its single
invocation, with `NVCOMPILER_ACC_NOTIFY=31` and the three synchronization
variables removed.

## Compile-only evidence

Evidence root:
`/opt/gpu-nci-development-builds-20261020/m3b0-compile-20261021T024535Z`.
Each step has `command.json` (argv, cwd, timeout, exit status) and its
stdout/stderr. `tools/` holds the scripts that ran them.

- `feasibility/`: interface sources compiled with the frozen flags, plus
  `nm` and `objdump` of the objects (the table above).
- `runtime-inspection/`: library hashes and static disassembly of
  `acc_is_present` and its shared-memory checks.
- `attempt-01`: **failed and preserved**. NVFORTRAN-S-0083/0446 errors came
  from a case-insensitive clash between harness arrays `buffers(:)` and the
  imported constant `BUFFERS`. The arrays were renamed.
- `attempt-02`: configure and build exit 0 with no warnings. Inspections
  cover undefined symbols, sections, disassembly, SASS, dynamic
  dependencies and hashes.
- `attempt-03`: a later snapshot; configure and build exit 0 with no
  warnings.
- `config-check/`: default OFF with NVHPC and with GNU adds no target. ON
  with GNU, a `Release` build type, extra Fortran or linker flags, or
  Ninja Multi-Config fails at configure.

- `commit-1b2ac596aa74a72b4eb927670bb8d0548d907b3a/`: a clean `git archive`
  export of source commit `1b2ac596aa74a72b4eb927670bb8d0548d907b3a`, built
  as `attempt-04`. Configure and build exit 0 with no warnings. Neither
  module object has `.bss`. The binary contains the kernel
  `m3b_workspace_add_one_582_gpu` with no FMA instruction and no
  `acc_shutdown` or error-routine symbol. Binary SHA-256:
  `ed399c2bec56e788fc58ef5f2bb362d7eb8373ddf2fdb9971becd5b4a7a51dca`.
  The later documentation-only commits through `ae89ee9` do not change these
  source files; the diagnostic fix described below is outside this receipt.

During the compile-only evidence phase, no candidate, test binary, solver or
benchmark was executed and `nvidia-smi` was not used.

## First native attempt and diagnostic fix

On 2026-10-21, source commit
`ae89ee99717b7d5eac0218f5ba19354946f63f03` exited 0 in its first native
attempt, but the unchanged strict verifier exited 1 with
`stderr: control character`. The first device diagnostic contained 723 NUL
bytes: NVHPC's property strings used C NUL padding, which Fortran TRIM does
not remove. The attempt remains **FAILED / NOT_ACCEPTED**; the candidate's
exit status does not override the verifier.

The producer now terminates each property at the first NUL using a pure,
bounded helper and the host assertions described above. The resource contract,
fixtures, verifier and device/resource sequence are unchanged. This fix has
not yet been compiled or executed in a native rerun, and no new acceptance is
claimed. Its build, host assertions and device sequence require a separately
reviewed finite execution package.

## Not established

- Accepted behaviour on an actual NVIDIA device after the diagnostic fix,
  which requires a new bounded execution owned by the Sol manager.
- What the runtime does when a real `acc_malloc` fails. It may terminate
  instead of returning `C_NULL_DEVPTR`; that would be a fatal runtime
  failure, not a recoverable status.
- Concurrent use of instances. Locals are automatic, but M3B0 is
  single-threaded and makes no thread-safety claim.
- Copying a `resource_workspace`, which would duplicate device ownership
  and is unsupported.
- Public ABI budgets, contexts, NCI fields, science and performance, which
  belong to M3B1 and later.

AI assistance: Claude Opus 5.5 max wrote this experiment and document.
The contract is GPT-6 Astra's; fixtures, verification and execution belong
to GPT-6.1 Sol, which also added the diagnostic prefix fix and host assertions.
Only synthetic data is involved.
