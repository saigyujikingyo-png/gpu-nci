# Private P1 native timing workflow

Implementation/preparation only. This directory does not authorize a build,
input generation, native qualification or a performance run. The independently
reviewed frozen package and Sol execution-manager GO remain required.

`NCI_BUILD_BENCHMARKS=OFF` is the default. Root declares that option before the
backend directories and requires OpenMP. When ON, the private executables link
exactly `nci_cpu_bench_objects` or `nci_openacc_bench_objects`, plus the same-compiler strict
reader. They never link the matching backend DSO too. Their build-info
`backend_library` explicitly reads `private-object-link:..._bench_objects`; it is not
a claimed DSO path. Production workers retain their original DSO metadata and
three-argument protocol. The backend's hidden Fortran timing getter is not a
new public C ABI symbol. All variants have separate driver module directories.
The ordinary production object collections and DSOs remain uninstrumented even
with benchmarks ON; dedicated benchmark collections have their own core module
directories, include paths and NCI_BENCHMARK definitions (interface revision2).

The private executable protocol is:

```
nci_benchmark_cpu INPUT.cube SETTINGS.nml EXISTING_NEW_CONFIG_DIR N THREADS 0
nci_benchmark_openacc INPUT.cube SETTINGS.nml EXISTING_NEW_CONFIG_DIR N 1 1
```

The parent exclusively creates the empty configuration directory. The executable
exclusively creates ten directories in fixed order:
`fresh_process_first_run`, `warmup1`, `warmup2`, `formal1` through `formal7`.
Every invocation of the shared `execute_run` rereads the same frozen input and
settings and creates/destroys its own context. There is no cross-run field cache.
The reader, metadata checks, scheduler, output serializer and scientific ABI
status handling are shared with the production worker.

Formal settings must match the expected cubic N and actual CPU team, or GPU
host team 1, backend, FULL four-field mode, finite boundaries, common X slab B=4,
rho_min=1e-8 and zero negative tolerance. The source, geometry, memory budget,
binary, immutable input and exact settings hashes must be bound by the external
frozen package. Formal grid/team arguments allow only 128/256/384 and CPU
1/4/8/16 or GPU host 1. A seventh `--qualification` flag permits N=5..384 for
separate bounded native qualification cards, including tail slabs. The formal
Python runner never adds these qualification sizes to the matrix.

`run_config.py` is one configuration adapter for the existing frozen package
controller. Its required options are `--executable`, `--input`, `--settings`,
`--output`, `--n`, `--threads`, `--backend cpu|openacc`; all paths must be absolute,
and output must not exist. It executes one process and enforces 120 seconds for
all ten calls together. It sends termination only to its owned child process
group if needed and retains partial files. The outer controller owns the serial
15-stage matrix, cgroup/affinity, disk/byte/file caps, STOP, exact frozen hashes,
2100-second whole-package deadline and 10-second package cleanup grace. Its
deadline takes precedence over this adapter's maximum child cleanup wait.
There is no retry, deletion, variable slab size, extended timeout or adaptive
matrix. A nonzero adapter exit must stop later stages.

The matrix has 15 configurations and retains 150 repetitions and all 600 FULL
raw files (`rdg.f64`, `lambda2.f64`, `signedrho.f64`, `flags.u8`), including first
run and warmups. Complete four-field payload is 94,371,840,000 bytes. Inputs,
logs, JSON and other frozen package material require their own additional cap.
GNU strict Release CPU versus NVHPC 26.9 strict Release OpenACC is a compiler
difference to disclose with any eventual accepted performance comparison.

Each `timing.json` contains every actual per-slab observation: ABI status,
monotonic evaluate timestamps, getter validity, timing state/error, team size,
launch count, event create/destroy counts, queue, stream and kernel/device times.
The driver immediately rejects bad timing, a wrong actual team, bad GPU event
cleanup or a GPU field launch above 500 ms and stops future calls. The <100 ms
launch target and B4 largest-plane safety still need separate qualification.
The CPU device interval equals its actual host field region exactly; the GPU
device interval spans first upload through last completed download. CPU field
fork/join/barrier/count bookkeeping and GPU event-enqueue gaps differ. Teval and
Te2e retain those outer workflow costs and are the fair comparison metrics.
The private observer runs after the shared completed-statistics/status checks.
Each raw row records sample_eligible: only a proven successful call or the
original fully validated all-invalid-slab continuation is eligible. Status3 alone
is insufficient. Failed/ineligible records are retained, trigger fail-stop and
never enter valid kernel/device/Teval totals. Successful reports require every
row's sample_eligible=true; a historical valid getter record cannot bypass it.

Te2e starts immediately before the shared reader opens CUBE input. It includes
evaluation, serialization, all native field/reader storage release, context
cleanup, native metadata close, fsync of four raw files and native.json, and
directory fsync. New repetition directory entries are synchronized in their
parent. It excludes frozen CLI snapshot/hash staging and the later timing.json
emission/fsync, explicitly recorded to avoid self-referential timing. Fortran
close alone is never treated as persistence. Persistence failures invalidate the
configuration even if already-closed native.json says numerical completion;
timing.json/configuration.json are authoritative for benchmark completion.

Only after the first durable complete workflow, cleanup and timing report does
native stdout emit exactly `NCI_BENCHMARK_FIRST_RESULT_ACK_V1` plus newline.
Python measures parent monotonic Popen launch to receipt of that complete line,
separately from configuration wall and outer controller/staging wall. It never
infers first-result time from process exit. Cache state is `uncontrolled`; this
is a fresh process first run and makes no cold filesystem/compiler-cache claim.
Formal profiling variables must be off. stderr/profiler traces are never parsed
for timing; separate attribution qualification cannot become a formal sample.

The adapter preserves `invocation.json`, `stdout.log`, `stderr.log`, original
per-run reports and `configuration.json`. The latter references every raw timing
report and retains the complete-prefix metrics, formal median and inclusive IQR.
Fewer than seven formal records is explicitly `PARTIAL_BENCHMARK`. Completion
means timing/output completeness only; numerical validity, export/dependency and
offload evidence still require independent acceptance. No speedup is asserted.

Pure control checks (no build/native launch/scientific imports):

```
python -B -m unittest discover -s tests/benchmark -p test_control.py -v
```

With BUILD_TESTING and benchmarks ON, build-only private shared test bridges
`nci_cpu_benchmark_test_bridge` and optional `nci_openacc_benchmark_test_bridge`
link the exact backend objects. `tests/benchmark/qualify_probe.py` is an explicit
qualification entry, never a registered native CTest. Its N=9 fixture creates two
live contexts, checks untouched initial state, performs A/B evaluations, checks
record isolation, rejects an invalid reserved tile with reset timing, checks B
again, repeats A and checks both context cleanups. Actual team/event/stream
fields and the 500 ms limit are checked before any subsequent evaluation. N=384
GPU mode performs exactly one interior B4 evaluation (global X start4) with a
384x384 YZ plane, input X origin2 and eight density X planes, then destroys both
contexts. It reuses pinned mixed quadratic v1 coefficients from
tests/e2e/fixtures.py: offset4, linear=(1/8,-1/16,3/16), and
H=[[-1/4,1/16,-1/32],[1/16,1/8,3/64],[-1/32,3/64,3/8]]. Coordinates
q=(global_index-192)/256 and j_inv=256I retain exact dyadic inputs and nonzero
off-diagonal Hessian. On the entire domain |q|<=3/4; an absolute-term bound gives
rho>=4-(3/4)(3/8)-(1/2)(3/4)^2(33/32)>3, with no clipping. N9 keeps its original
constant density fixture. This is synthetic launch qualification; it does not
establish a worst-case bound for all stored-water slabs. Formal per-slab 500ms
enforcement remains required.

All raw observations and statuses are retained in probe.json. Nonfinite timing
values become JSON diagnostics with classification, sign, NaN kind where
applicable and exact original IEEE754 binary64 bits read from C storage. Native
state/error/status values remain unchanged and any nonfinite value forces FAIL;
finite values stay numeric. Thus a timing failure cannot prevent durable failure
diagnostics merely because strict JSON rejects NaN or Infinity. These synthetic
API fixtures are separate from real model input generation and formal samples.

An additional explicit entry `tests/benchmark/qualify_faults.py --library
/absolute/libnci_openacc_benchmark_test_bridge.so --output /absolute/NEW_DIRECTORY`
is source preparation for a separate frozen fault qualification card. It is never
registered as a native CTest or called by a default test. Modes0..5 are fixed:
clear; first/second event creation; start/stop record; null reported stream. The
Fortran-only core control is the exact nci_bench_test_event_fault interface in
revision2. The private test bridge is present only in the OpenACC test library.

Each mode uses fresh A/B contexts and the existing N9 constant-rho B4 fixture.
The fixed sequence has baseline A; arm A; reserved-tile early refusal A; sibling B;
admitted A; scheduled one-shot recovery A. Mode0 first arms1 then clears0. Mode0
also makes exactly one baderrbuf(NULL,len=1) call immediately after baseline.
Thus the added suite has at most31 ABI evaluations,24 field launches,12 contexts:
mode0 six evaluations/four launches; modes1..5 five evaluations/four launches
each. Cleanup/getter/control calls do not evaluate a field. These are additional
qualification calls only; the existing probe and formal matrix are unchanged.

The public errbuf guard runs before live-context entry. This special early
refusal preserves historical timing, unlike the later reserved-tile refusal
which resets state0 and leaves the fault armed. Its failed ABI status, unchanged
outputs and old record are retained with sample_eligible=false. A getter's old
valid record never makes that refused call a current timing sample.
The mode0 fixture also calls the actual private benchmark_observe helper with
that refused ABI status and sample_eligible=false, checks its raw ineligible row
is retained and all valid totals remain zero. This adds no ABI or field calls.

Expected admitted mode1..5 timing state is-1 with errors4/4/6/7/5 and created /
destroyed counts0/0,1/1,2/2,2/2,2/2. Mode0 stays valid1/error0/events2/2. In every
case science status/fields/flags/stats must match the baseline bit-for-bit and the
sibling's record must remain identical. The bridge checks expected timing state,
all cleanup counts, scientific output/state equality and sibling isolation before
the predeclared recovery. An unexpected failure stops later calls and modes;
recovery is neither a retry nor a formal sample. Raw per-call records (all bytes
and timing IEEE bits), full four-field snapshots, stats and statuses are retained
in fault_modeN.json. Nonfinite diagnostics remain serializable and force FAIL.
No fault qualification or cleanup acceptance is claimed by these source files;
native failure and first-use attribution cards remain required.

Unvalidated native obligations include default/instrumented equivalence, strict
actual Release flags, DSO exports/dependencies, analytic/near-zero/boundary/tail
and full-slab numerics, repeated/context-isolated measurements, timing-fault
cleanup, first-use CUDA stream/event/kernel attribution, fsync/ACK failure paths,
actual teams and the B4 largest YZ plane. The implementation's pure tests are
protocol evidence only.
