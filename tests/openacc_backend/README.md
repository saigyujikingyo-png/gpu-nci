# Independent M3B1 public backend tests

Preparation only. No native library evaluation or GPU program was run while
authoring these tests. Mathematical fixtures come from the unchanged independent
analytic/Fourier/LAPACK and rational/high-precision references, never candidate
outputs. The public ABI remains 40/280/88 bytes and three C entry points.

`corpus.json` freezes **148 native pytest cases, 350 Python evaluations and six
pthread evaluations = 356 total**, at most two simultaneous contexts and actual
grids at most 17^3. `case_ids.json` freezes every required native pytest ID.
The complete successful run has 278 GPU field regions: public 238, bridge 34,
pthread six. One additional optional-library CPU-selector evaluation is a CPU
reference check. Preflight rejection and allocation injection add no field
region. These counts concern field-region calls, not GPU performance.

The public suite covers every periodic combination, both output modes, full/B=1/
B=3 and short tails, Nx=5 duplicate halos, threshold and 61-point stencil masks,
handed skew geometry, repeated/near-zero roots, subnormals and true overflow,
all-invalid completion, whole-halo preflight, alias/capacity/null/geometry/overflow
rejection, per-object INT32_MAX planning and huge global X backed by tiny slabs.
Rejections snapshot rho, tile, all fields and all 88 stats bytes. Ordinary
buffers and stats carry canaries. Completed invalid fields must contain exact
canonical QNAN, distinguishing them from the frozen staging poison.

The bridge uses only the frozen non-BIND(C) module interfaces. It links the same
production objects, adds test-only C wrappers and is **not** a production SO.
All 18 acquisition failures each have exactly one scheduled recovery call;
marker/status corruption each has one scheduled recovery. Other cases cover
preflight preserving pending controls and observations, invalid controls/handles,
per-context isolation, no retained capacity in both modes, completed errors and
device failure indices on huge global X. The independent ledger state machine
checks ownership, immediate mapping, reverse failure unwind, moved staging,
actual cleanup, bytes, peaks, transfers and final zero. A normal ledger has
71 events, well below the frozen 256-column capacity. The largest actual backend
array plan is 576861 bytes on each host/device side (17^3 diagnostic full grid).
Fixed context/descriptor/ledger/runtime overhead is outside that array figure;
it must be reported separately by the implementation and manual package.

The C program links the actual `nci_openacc` shared library. Two real pthreads
perform two barrier-coordinated calls each; one context then moves to a new
pthread and back to main. Every result is checked against independent dyadic
quadratic/constant mathematics and includes raw output IEEE bits. Ready/begin/end
events retain Linux thread identities, sequence and monotonic timestamps.
The barriers establish concurrent requests, without claiming overlapping device
execution. A separate small Fortran standard-runtime helper selects concrete
HOST state and checks restoration after create/evaluate/destroy and migration.
It does not link another copy of production objects or change the public ABI.

## Pure preparation checks

Only this file is safe to run without a native package:

```text
python -m pytest -q -p no:cacheprovider tests/openacc_backend/test_selfchecks.py
```

Pure checks use invented callbacks, explicit placeholder non-executable files,
invented ledgers and independent analytic JSON. They do not load a candidate
library or execute a compiler, native evaluator, GPU or subprocess. Their PASS
is parser/fixture preparation evidence only. Collect-only of the four native
files may additionally verify the 148 frozen IDs without loading a library.

`CMakeLists.txt` is an opt-in child supplied for root integration. It expects
`nci_openacc_objects` and `nci_openacc`, with object-target module include paths
provided by that target. It adds `nci_openacc_test_bridge` and
`nci_openacc_test_threads`; it registers no native CTest. Default CPU CI may run
the pure selfchecks only. Same-object bridge integration must be compiled again
against the actual backend; syntax compilation against interface declarations
does not prove that integration.

## Later user-launched finite package

The execution manager must freeze exact source/build/binary/input hashes,
compiler flags, deadlines, output caps, stop controls and owned process handling
before launch. No automatic invocation is provided by importing or building
these files. Do not run these commands from an agent during preparation.

The manually launched controller sets absolute actual paths:
`NCI_CPU_LIBRARY`, `NCI_OPENACC_LIBRARY`, `NCI_OPENACC_BRIDGE`, and a fresh
`NCI_OPENACC_RECEIPTS` directory. It selects `ACC_DEVICE_TYPE=nvidia`,
`ACC_DEVICE_NUM=0`, `NVCOMPILER_ACC_NOTIFY=31`, and removes
`NVCOMPILER_ACC_SYNCHRONOUS`, `PGI_ACC_SYNCHRONOUS`, `CUDA_LAUNCH_BLOCKING`.
Then it invokes the native suite exactly once, failure-stop enabled:

```text
python -m pytest -q -x -p no:cacheprovider --junitxml=/absolute/new/native.xml tests/openacc_backend/test_cpu_only.py tests/openacc_backend/test_public.py tests/openacc_backend/test_rejections.py tests/openacc_backend/test_private.py
```

It separately invokes `nci_openacc_test_threads` exactly once with no arguments.
Its `--describe` entry is an empty-control description that does no runtime or
device initialization. Raw stdout/stderr and actual exit codes are retained.
Missing inventory before any candidate attempt is NOT_TESTED; an attempted
nonzero, timeout, incomplete XML or missing testcase is FAILED. No test skips.
The receipt root/subdirectories and report files are exclusive; old attempts
and failures must not be reused or overwritten.

Every Python call writes a JSON record before assertions, with actual resolved
library identity/hash, context token, case ID/status and separate hashed binary
input/descriptor/output/stats/error artifacts. Field data use native binary64
storage; shapes and layout are recorded. Private observations retain all 24
values and 256 event columns including unused zeros. A 128 MiB compare-only cap
covers receipt artifacts; it is not a process RSS/VRAM cap.

Compare-only entry points (never launch a candidate):

```text
python tests/openacc_backend/verify_receipts.py --root /absolute/receipts --junit /absolute/native.xml --library /absolute/libnci_openacc.so --bridge /absolute/libnci_openacc_test_bridge.so --cpu-library /absolute/libnci_cpu.so --report /absolute/new/receipt-check.json
python tests/openacc_backend/verify_threads.py --stdout /absolute/threads.stdout --stderr /absolute/threads.stderr --binary /absolute/nci_openacc_test_threads --library /absolute/libnci_openacc.so --report /absolute/new/thread-check.json
```

The first binds mandatory native test IDs, exact evaluation counts and rehashes
all raw receipts; the second independently checks six thread-result payloads,
causal/thread identity events and output hashes. Their PASS scopes are limited
to those checks. **Neither parses or accepts OpenACC runtime notices.** An
independent source/compiler/controller/runtime review must bind the original
notices to actual builds and the 278 field regions. Nine uploads/five downloads
per completed workspace are the explicit array ledger; compiler-generated
fixed metadata transfers may add raw notices. Those must be reviewed from the
final source/compile report and frozen explicitly before execution, never
ignored as unknown or fitted to candidate output. Source completeness, actual
loader provenance, no fallback/recomputation, timeouts and true process exits
remain controller/reviewer responsibilities. Raw bound/tau and all eigenvalues
are not exposed by the frozen B1 hook; M3A evidence and source review retain
their narrower role. No real-density scientific acceptance or speedup claim.
