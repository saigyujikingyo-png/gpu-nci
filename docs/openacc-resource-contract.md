# M3B0 finite OpenACC resource gate

Freeze this contract and independent expectations before candidate execution.
Scope: standalone `experiments/openacc_resources`, default OFF and absent from
public ABI/CLI dispatch. No production formula, CPU implementation, old M3A
fixture or numerical tolerance is changed. Only tiny exact binary64 resource
and transport fixtures are executed; no scientific or speedup conclusion.
Its opt-in CMake option is `NCI_ENABLE_OPENACC_RESOURCES=ON`, target and
build-root executable name `m3b_resources`. Interface/source variants require
an explicit reviewed contract change before execution.

## Resource behavior

Use explicitly selected NVIDIA device 0 under NVHPC 26.9/Linux x86-64, with the
already accepted flags `-acc=gpu -Kieee -Mnofma` and
`-gpu=cc120,cuda13.3,mem:separate,nofma,noflushz,rdc`. Preserve generated compile
commands and `-Minfo=accel` reports. Reject unsafe flags/configurations. No
configuration or build step executes the candidate.

A private Fortran workspace owns exactly three host arrays (binary64 input,
binary64 staging output, int32 device markers) and their explicit device
allocations/mappings. Use checked host allocation, `acc_malloc` null detection,
paired `acc_free`, and explicit map/unmap operations. Public/user pointers are
not mapped. A failed preparation unwinds only successfully acquired resources
in reverse order. Release removes mappings before freeing their storage and
is safe on an empty workspace. Do not use global `acc_shutdown`, modify other
processes, or retain shared scratch. The resource module contains no STOP or
external I/O; the developer harness may report and exit.

Workspace state is per instance. No resizing, retries, pools or caching in
this gate. Sizes are positive and at most 1024 points; checked tracked bytes
are 20*N on host and 20*N on device, each capped at 20480 bytes per workspace.
At most two live workspaces are permitted by the harness. Runtime, descriptors,
compiler-generated temporary storage and driver overhead are excluded from
these tracked-array caps; they are not RSS or total VRAM limits.
The harness additionally owns two distinct binary64 caller-copy destinations
of 17 and 31 elements (384 host bytes in total), allocated with status checks.
These are not aliases of staging. Bounded test-ledger storage is at most
65536 host bytes per workspace instance and is reported separately.

Only the test harness injects allocation failures. An instance-local failure
index selects one of its six acquisitions in order: host input, host output,
host marker, device input, device output, device marker. Reject other indices
except 0 (normal). Each failure is deterministic and must unwind to no live
owned buffers/mappings. It models allocation failure; it does not establish
actual hardware OOM behavior. Never exhaust physical memory to test OOM.
Map each host array immediately after its matching device allocation succeeds;
check that it is present. Injection enters the same failure branch as an actual
null/failed allocation. Release in reverse acquisition order: for marker,
output, input, unmap an acquired mapping, check absence while host storage is
still valid, then free its device allocation; finally free host marker,
output, input. Only operations actually acquired may be unwound.
After each injected failure, prepare and release that same instance once with
failure disabled; verify recovery without executing an extra field kernel.
These seams remain experimental/test-only and cannot enter a public library.

## Frozen finite harness

One no-argument executable completes this fixed sequence, stopping on its
first unexpected failure:

1. For fail index 1..6 at N=5: inject once, require allocation-failure status 5 and
   zero remaining ownership; then prepare/release N=5 with injection disabled,
   require status 0 and zero remaining ownership. No kernels in these cases.
2. Prepare A (N=17) and B (N=31), each with distinct private arrays. Initialize
   input A[i]=(i-9)/8, B[i]=-(i+3)/16, where i=1..N. Transfer exact input.
3. Before EACH of the three kernels, set the private output staging to quiet
   NaN and markers to zero and upload both poison arrays. Execute A, then B,
   each once: in the same OpenACC compute region, write
   staging[i]=input[i]+1 and marker[i]=acc_on_device(nvidia). Copy staging and
   markers back synchronously, first re-poisoning host staging/markers before
   download. Verify all markers before copying into the distinct harness
   caller destination, and emit its raw IEEE bits. No host recomputation
   supplies the result. Poisoning also applies to B_AFTER_A_FREE, so stale
   device or host results cannot satisfy the repeated fixture.
4. Release A, preserving B. Execute B once more from unchanged input, emit its
   raw output, then release B. All ownership returns to zero. A release on an
   already empty instance is a defined no-op for this private resource type.

This gives exactly three kernel executions, eight uploads (1332 bytes: two
input uploads plus six poison uploads), and six downloads (948 bytes). Arrays
are transferred individually; allocation/recovery cases have no kernels or
transfers. Record runtime notification counts and byte totals, in addition to
the structured resource ledger. No missing-device or runtime-failure result is a PASS:
no NVIDIA device -> exit 3/NOT_TESTED; any unexpected check failure -> nonzero.
Use ordinary paired release for owned resources. An unrecoverable platform
runtime error may terminate the process; returning from an OpenACC fatal-error
callback is not permitted as a recovery strategy.

## Stdout protocol M3B0 version 1

ASCII, no other stdout lines. Diagnostic/runtime evidence goes to stderr.
Start `M3B0 1`. Then exactly six pairs of records, ordered by k=1..6:

`FAIL k STATUS LIVE_HOST LIVE_DEVICE LIVE_MAPPINGS`

`RECOVER k STATUS LIVE_HOST LIVE_DEVICE LIVE_MAPPINGS`

Required values: FAIL STATUS=5; RECOVER STATUS=0; all LIVE values zero.
For tags `A`, `B`, `B_AFTER_A_FREE` in that order, emit N records:

`VALUE TAG INDEX INPUT_BITS OUTPUT_BITS DEVICE`

INDEX is 1..N; bits are exactly 16 hexadecimal digits; DEVICE must be 1.
Inputs and expected outputs are independently frozen by the test author;
addition is exactly representable, so require bitwise equality. Compare the
two B sequences bitwise. After each VALUE sequence emit:

`DONE TAG STATUS` (STATUS=0).

Finish `END 6 6 79 3 0 0 0`: failure cases, recovery cases, value records,
kernel cases, final live host/device/mappings. A valid-looking stdout alone
does not prove cleanup or device execution: inspect implementation/ledger,
per-object unmap checks, runtime traces, exit and bound artifact hashes too.
Do not change this protocol to fit candidate output.

### Resource event protocol on stderr

The resource module records bounded in-memory events; only the harness writes
them, in actual operation order, as exactly:

`M3B0_RESOURCE WORKSPACE GENERATION BUFFER ACTION BYTES RESULT`

WORKSPACE is T for the failure/recovery instance, or A/B; GENERATION is 2*k-1
for failure k and 2*k for its recovery, or 1 for A/B. BUFFER is IN, OUT or MARK;
BYTES is 8*N, 8*N or 4*N respectively. This identity prevents address reuse
from conflating owned allocations. ACTION is H_ALLOC, H_FAIL, D_ALLOC, D_FAIL,
MAP, PRESENT, UNMAP, D_FREE or H_FREE. Successful operation RESULT is 0;
injected H_FAIL/D_FAIL is 5; PRESENT records the actual query result 1 after
map and 0 after unmap. Fail events never count as successful ownership.

Require the exact acquisition prefix and reverse unwind for each generation.
Map and unmap PRESENT checks occur while its host buffer remains allocated.
Drain events after each failure/recovery, A/B prepare and A/B release; do not
fabricate a zero-only summary. Across the complete fixture expect 240 events:
36 H_ALLOC/H_FREE each, 27 D_ALLOC/D_FREE each, 27 MAP/UNMAP each, 54 PRESENT,
and six failures. Peak live host/device/mapping objects is six each; peak
tracked workspace bytes is 960 each on host/device. B's ownership must remain
live across A release and its own second execution. Final zero is sampled
after both releases and the defined empty A release. Harness caller arrays
are separate from this three-buffer ledger and freed before successful exit.

## Independent verifier and execution

`tests/openacc_resources` owns a strict parser, static frozen expected values,
malformed/duplicate/truncated/evidence-negative checks and a compare-only
verifier. Expected values must not import the resource implementation. Pure
selfchecks may run during preparation; source and fixture hashes are committed
before the one native attempt. No public GPU execution test enters default CPU
CI; only pure verifier selfchecks may be registered there.

A newly created GPT-6.1 Sol manager prepares a finite runner: configure/build
at most 600 seconds each and two build jobs; exactly one no-argument executable
invocation, at most 30 seconds; independent verification at most 60 seconds.
It binds exact clean source commits, runner/fixture/source/compiler/binary and
output hashes, argv/environment, device identity, allocation/map/transfer/kernel
trace, exit and terminal status. No auto retry, sweep or benchmark. Stop and
preserve on source drift, failed gates, timeout or interruption; terminate only
the spawned command's own process group. Run only after root read-only review.
Use `NVCOMPILER_ACC_NOTIFY=31`; explicitly remove and record the absence of
`NVCOMPILER_ACC_SYNCHRONOUS`, `PGI_ACC_SYNCHRONOUS` and `CUDA_LAUNCH_BLOCKING`.
The implementation must provide synchronization without environment forcing.

After success, root and an independent reviewer decide whether this resource
pattern is ready for M3B1. A PASS is restricted to this finite configuration;
it does not implement or accept public C ABI allocation budgets, concurrency,
tile classification, NCI fields, real-density science or performance.

References: [NVIDIA explicit allocation/mapping](https://docs.nvidia.com/hpc-sdk/archive/26.9/compilers/openacc-gs/index.html#acc-malloc)
and [fatal runtime errors](https://docs.nvidia.com/hpc-sdk/archive/26.9/compilers/openacc-gs/index.html#openacc-error-handling).
Actual installed compiler evidence, rather than a download-page default,
determines the frozen CUDA 13.3 toolchain used here.
