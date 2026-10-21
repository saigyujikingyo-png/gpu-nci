! SPDX-License-Identifier: MIT
!> Private P1 timing record and monotonic clock (src/benchmark/core/README.md).
!> Compiled only into the NCI_BUILD_BENCHMARKS object collections
!> nci_cpu_bench_objects and nci_openacc_bench_objects, never into nci_cpu or
!> nci_openacc. No module variable, no I/O, no STOP: each record is stored in
!> its own API context and written only by that context's evaluate call.
module nci_bench_types
  use, intrinsic :: iso_c_binding, only: c_int32_t, c_int64_t, c_double
  implicit none
  private

  !> Timing of the latest evaluate call past the errbuf/live-context entry
  !> guards of one context. An earlier refusal can retain an older record.
  !> Callers must also establish sample eligibility. state: 0 not
  !> observed, 1 valid, -1 timing failure; timing_error is the first failure
  !> code and is zero unless state is -1. CPU: observed_threads is the actual
  !> field team, kernel_count 1, event counts/queue/stream 0. GPU:
  !> observed_threads 0, actual field launches, events created/destroyed,
  !> the fixed async queue and its CUDA stream handle. reserved is 0.
  type, bind(C), public :: nci_bench_record
    integer(c_int32_t) :: state, timing_error, observed_threads, kernel_count
    integer(c_int32_t) :: events_created, events_destroyed, async_queue, reserved
    integer(c_int64_t) :: stream_handle
    real(c_double) :: kernel_seconds, device_seconds
  end type nci_bench_record

  integer(c_int32_t), parameter, public :: NCI_BENCH_NOT_OBSERVED = 0
  integer(c_int32_t), parameter, public :: NCI_BENCH_VALID = 1
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAILED = -1

  !> timing_error codes (first failure of one evaluate call).
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_CLOCK = 1
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_CLOCK_ORDER = 2
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_TEAM = 3
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_EVENT_CREATE = 4
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_STREAM_NULL = 5
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_RECORD_START = 6
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_RECORD_STOP = 7
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_STREAM_CHANGED = 8
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_EVENT_INCOMPLETE = 9
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_EVENT_QUERY = 10
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_ELAPSED = 11
  integer(c_int32_t), parameter, public :: NCI_BENCH_ERR_EVENT_DESTROY = 12

  !> Test-only CUDA event faults armed by nci_capi:nci_bench_test_event_fault
  !> for the next OpenACC backend evaluation of one context.
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_NONE = 0
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_CREATE_START = 1
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_CREATE_STOP = 2
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_RECORD_START = 3
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_RECORD_STOP = 4
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_NULL_STREAM = 5
  integer(c_int32_t), parameter, public :: NCI_BENCH_FAULT_MAX = 5

  public :: nci_bench_clock_ns, nci_bench_reset, nci_bench_fail, nci_bench_interval
  public :: nci_bench_finish_cpu

  interface
    !> nci_bench_clock.c: checked CLOCK_MONOTONIC nanoseconds, -1 on failure.
    function c_monotonic_ns() bind(C, name='nci_bench_monotonic_ns') result(ns)
      import :: c_int64_t
      integer(c_int64_t) :: ns
    end function c_monotonic_ns
  end interface

contains

  !> CLOCK_MONOTONIC in nanoseconds, or -1 when the clock call failed or its
  !> value is not representable.
  function nci_bench_clock_ns() result(ns)
    integer(c_int64_t) :: ns
    ns = c_monotonic_ns()
    if (ns < 0) ns = -1
  end function nci_bench_clock_ns

  !> Not observed: every member zero.
  pure subroutine nci_bench_reset(record)
    type(nci_bench_record), intent(out) :: record
    record%state = NCI_BENCH_NOT_OBSERVED
    record%timing_error = 0
    record%observed_threads = 0
    record%kernel_count = 0
    record%events_created = 0
    record%events_destroyed = 0
    record%async_queue = 0
    record%reserved = 0
    record%stream_handle = 0
    record%kernel_seconds = 0.0_c_double
    record%device_seconds = 0.0_c_double
  end subroutine nci_bench_reset

  !> Timing failure; the first code is kept.
  pure subroutine nci_bench_fail(record, code)
    type(nci_bench_record), intent(inout) :: record
    integer(c_int32_t), intent(in) :: code
    if (record%timing_error == 0) record%timing_error = code
    record%state = NCI_BENCH_FAILED
  end subroutine nci_bench_fail

  !> seconds = (t1 - t0)/1e9 for two clock readings and code 0; otherwise
  !> seconds 0 and code CLOCK (a failed reading) or CLOCK_ORDER (t1 < t0).
  pure subroutine nci_bench_interval(t0, t1, seconds, code)
    integer(c_int64_t), intent(in) :: t0, t1
    real(c_double), intent(out) :: seconds
    integer(c_int32_t), intent(out) :: code
    seconds = 0.0_c_double
    if (t0 < 0 .or. t1 < 0) then
      code = NCI_BENCH_ERR_CLOCK
    else if (t1 < t0) then
      code = NCI_BENCH_ERR_CLOCK_ORDER
    else
      code = 0
      seconds = real(t1 - t0, c_double)/1.0e9_c_double
    end if
  end subroutine nci_bench_interval

  !> CPU record of one evaluate_grid call that ran its field loop: t0/t1 are
  !> the clock readings around the parallel construct and team the
  !> omp_get_num_threads value observed inside it. device_seconds is the same
  !> host-resident interval (the CPU field region has no transfers).
  pure subroutine nci_bench_finish_cpu(record, t0, t1, team)
    type(nci_bench_record), intent(inout) :: record
    integer(c_int64_t), intent(in) :: t0, t1
    integer, intent(in) :: team
    real(c_double) :: seconds
    integer(c_int32_t) :: code
    record%observed_threads = int(team, c_int32_t)
    record%kernel_count = 1
    call nci_bench_interval(t0, t1, seconds, code)
    if (code /= 0) then
      call nci_bench_fail(record, code)
    else
      record%kernel_seconds = seconds
      record%device_seconds = seconds
    end if
    if (team < 1) call nci_bench_fail(record, NCI_BENCH_ERR_TEAM)
    if (record%timing_error == 0) record%state = NCI_BENCH_VALID
  end subroutine nci_bench_finish_cpu

end module nci_bench_types
