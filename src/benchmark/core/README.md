# Private P1 timing core

Contract: root `P1_TIMING_INTERFACE.md` revision 1 and its additive
`P1_TIMING_INTERFACE_REVISION2.md` (coordination directory).
Status: **source implementation only**. Its author has not compiled, built,
run or qualified it; build, qualification and every timing claim belong to
the reviewed Sol-managed packages.

## Build

`NCI_BUILD_BENCHMARKS` (root option, default OFF; requires
`NCI_ENABLE_OPENMP`) adds private OBJECT targets:

| Target | Sources | Modules |
|---|---|---|
| `nci_cpu_bench_objects` | `nci_bench_clock.c`, `nci_bench_types.f90`, the `nci_cpu_objects` list | `<build>/cpu/bench_modules` |
| `nci_openacc_bench_objects` (also `NCI_ENABLE_OPENACC`) | the same two, the `nci_openacc_objects` list | `<build>/openacc/bench_modules` |

Each compiles the unchanged production sources again with the PUBLIC
definition `NCI_BENCHMARK`. Propagated to a consumer: the module directory,
`NCI_BENCHMARK`, Fortran-only options (GNU `-ffp-contract=off`; NVHPC CPU
`-Kieee -Mnofma`; OpenACC the frozen device/host options), OpenMP, and for
OpenACC the device-link options and the SDK's `cuda/13.3` libcudart (full
path). Not propagated: the OpenACC executable's runtime search path; set it as
`nci_driver_openacc` does. A benchmark executable links exactly one of these
targets plus `nci_cube_input`, never also `nci_cpu`/`nci_openacc`.

`nci_kernel.f90`, `nci_capi.f90`, `nci_acc_backend.f90` and
`nci_acc_backend_stub.f90` are always preprocessed (`Fortran_PREPROCESS ON`).
Without `NCI_BENCHMARK` (all production libraries, tests and workers, and
every OFF build) their conditionals select exactly the original statements:
synchronous kernel, no record, no getter, no CUDA runtime reference. The
device-source generator still finds every anchor (its procedure list and the
public line are unchanged; the conditional lines in the evaluate_grid header
are outside every insertion point). A benchmark context wrapper is 120 bytes
instead of 56 (record and pending fault).

## Interfaces (Fortran only, not BIND(C), benchmark objects only)

`module nci_bench_types`:

```fortran
type, bind(C) :: nci_bench_record
  integer(c_int32_t) :: state, timing_error, observed_threads, kernel_count
  integer(c_int32_t) :: events_created, events_destroyed, async_queue, reserved
  integer(c_int64_t) :: stream_handle
  real(c_double) :: kernel_seconds, device_seconds
end type
integer(c_int64_t) function nci_bench_clock_ns()  ! CLOCK_MONOTONIC ns, -1 on error
```

`state` 0 not observed, 1 valid, -1 timing failure. `timing_error` is the
first failure, 0 unless state is -1: 1 clock, 2 clock order, 3 CPU team not
observed, 4 event create, 5 null queue stream, 6 start record, 7 stop record,
8 queue stream changed, 9 event incomplete after the queue wait, 10 event
query error, 11 elapsed failed/non-finite/negative, 12 event destroy.
`reserved` is 0. Also public: the `NCI_BENCH_*` constants and the helpers
`nci_bench_reset`, `nci_bench_fail`, `nci_bench_interval`,
`nci_bench_finish_cpu`. No I/O, STOP or module variable.

`module nci_capi`:

```fortran
subroutine nci_bench_get_timing(context, record, ok)
  type(c_ptr), intent(in) :: context
  type(nci_bench_record), intent(out) :: record
  logical, intent(out) :: ok          ! live context; not "measurement passed"
end subroutine
subroutine nci_bench_test_event_fault(context, mode, ok)   ! TEST ONLY
  type(c_ptr), intent(in) :: context
  integer(c_int32_t), intent(in) :: mode
  logical, intent(out) :: ok
end subroutine
```

An invalid context gives `ok = .false.` and a zero record. The record lives in
the context: reset at create and after the errbuf and live-context entry
guards of an evaluate call, then written only by that call. An earlier
refusal (such as NULL errbuf with positive length) leaves the previous
record unchanged. Query after each evaluate and before destroy. `state`
describes timing only: a sample is eligible only when the driver proves
completed output and either ABI success or its existing validated
completed-invalid-slab continuation. An ineligible call retains its raw
record for diagnostics but contributes nothing to valid timing totals.
No timing failure changes a status, an output, the stats, a commit, resource
handling or the broken state.

## Timed boundaries

CPU (`evaluate_grid`): readings immediately before `!$omp parallel do` and
after `!$omp end parallel do` (fork/join, loop, barrier, count reduction);
the axis tables, density preflight and everything else are outside.
`observed_threads` is `omp_get_num_threads()` from inside the unique
`(ix=0, iy=0)` iteration, read after the construct. `kernel_count` 1;
`device_seconds = kernel_seconds` (no transfers). Written only when the loop
ran (not after a table allocation failure or an earlier rejection).

OpenACC (`acc_backend_evaluate`, after the 18 acquisitions succeeded):

1. Create start/stop events (`cudaEventCreateWithFlags`, default flags) in
   the current context; partial creation is destroyed at once.
2. Clock reading immediately before the first upload.
3. After all nine uploads: `stream = acc_get_cuda_stream(1)`; a null handle
   is failure 5 and is never replaced by a default stream; start event on it.
4. The unchanged kernel with `async(1)`; stop event on the same stream;
   `kernel_count` +1, `async_queue` 1.
5. `!$acc wait(1)` immediately, also after any timing failure.
6. The queue must still map to the same stream; both events must already be
   complete (`cudaEventQuery`, no further wait); then
   `cudaEventElapsedTime` gives `kernel_seconds`.
7. Clock reading immediately after the last download, then the events are
   destroyed (counted); `device_seconds` spans the two readings.

Every CUDA return is checked. Nothing between steps 1 and 7 returns, so no
handle survives the evaluation. The event interval may include host enqueue
or scheduling gaps. `device_seconds` includes the existing intervening host
work (ledger, poisoning) and the step 3-6 calls; event creation/destruction,
`fill_inputs`, validation, release and commit are outside it but inside the
caller's whole-call Teval. No estimated overhead is subtracted.

## Test-only event faults

`nci_bench_test_event_fault` accepts only a live OpenACC context and mode
0..5 (0 clears). The next OpenACC backend evaluation of that context consumes
the mode when the C API calls the backend (after admission, descriptors, plan
and density preflight passed); earlier rejections leave it armed. An
injected failure skips that CUDA call and takes its real failure branch
(result 999). Expected record of an otherwise completed evaluation:

| Mode | Injected | error | created / destroyed | Other |
|---:|---|---:|---|---|
| 1 | first event creation | 4 | 0 / 0 | |
| 2 | second event creation | 4 | 1 / 1 | first destroyed at once |
| 3 | start record | 6 | 2 / 2 | |
| 4 | stop record | 7 | 2 / 2 | start recorded |
| 5 | queue stream reported null | 5 | 2 / 2 | stream_handle 0, no record |

In every mode: state -1, kernel_count 1, async_queue 1, kernel_seconds 0,
and the ABI status, outputs, stats and `acc_test_observe` values (call
ordinal aside) are those of the unfaulted evaluation. A backend allocation
failure consumes the mode before any event exists (record stays state 0).

## Not established

Everything at build and run time: compilation of every conditional variant,
CMake generation, the NVHPC 26.9 first-use behavior of queue 1 and its stream
handle, that libcudart events share the OpenACC runtime's context (a mismatch
must surface as a checked record failure), cudart initialization cost in the
first evaluation, queue sharing between concurrently evaluating contexts
(timing is meaningful with one evaluating context at a time), actual
stream/event/kernel attribution, clock and event overheads, and default
versus instrumented numerical equality.
