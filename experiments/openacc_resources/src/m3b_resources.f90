! SPDX-License-Identifier: MIT
!> M3B0 developer harness (docs/openacc-resource-contract.md): the fixed,
!> argument-free resource sequence on explicitly selected NVIDIA device 0.
!>
!> stdout carries only protocol M3B0 version 1. stderr carries the drained
!> resource events (M3B0_RESOURCE) in actual operation order, the device
!> identity and other M3B0_ diagnostics. Each record is written with the
!> values actually observed and then checked; the harness stops at the first
!> unexpected result. Device values are written as raw IEEE bits for the
!> independent verifier: the host never computes the expected outputs.
!>
!> Exit status: 0 every harness check passed (acceptance still needs the
!> independent verifier and the runtime evidence); 2 an unexpected check
!> failure, or command-line arguments; 3 NOT_TESTED: no NVIDIA device,
!> nothing on stdout and no host fallback; 4 a device result was rejected by
!> its marker or poison check. No OpenACC error callback is installed: a
!> fatal runtime error terminates the process with a nonzero status.
program m3b_resources
  use, intrinsic :: iso_fortran_env, only: output_unit, error_unit, real64, int64
  use openacc, only: acc_get_num_devices, acc_set_device_type, acc_set_device_num, acc_init, &
                     acc_get_device_num, acc_get_property_string, acc_device_nvidia, &
                     acc_property_name, acc_property_vendor, acc_property_driver
  use m3b_ledger, only: resource_event, buffer_name, action_name, BUFFERS, BUF_MARK, &
                        ACT_H_ALLOC, ACT_H_FAIL, ACT_D_ALLOC, ACT_D_FAIL, ACT_MAP, ACT_PRESENT, &
                        ACT_UNMAP, ACT_D_FREE, ACT_H_FREE
  use m3b_workspace, only: resource_workspace, m3b_label, m3b_inject_failure, m3b_prepare, &
                           m3b_release, m3b_set_input, m3b_upload_input, m3b_execute, &
                           m3b_copy_result, m3b_value_record, m3b_live, m3b_generation, &
                           m3b_transfers, m3b_event_count, m3b_event_at, m3b_clear_events, &
                           m3b_dropped_events, m3b_ledger_bytes, M3B_OK, M3B_RESULT_REJECTED, &
                           POISON_BITS
  implicit none

  integer, parameter :: EXIT_CHECK_FAILED = 2, EXIT_NOT_TESTED = 3, EXIT_RESULT_REJECTED = 4
  !> Workspace instances: T (failure and recovery cases), A and B.
  integer, parameter :: WS_T = 1, WS_A = 2, WS_B = 3, INSTANCES = 3
  character(len=1), parameter :: LABELS(INSTANCES) = ['T', 'A', 'B']
  !> Frozen fixture (docs/openacc-resource-contract.md).
  integer, parameter :: FAILURE_INDICES = 6, FAILURE_POINTS = 5, A_POINTS = 17, B_POINTS = 31
  integer, parameter :: ALLOCATION_FAILURE = 5, TOTAL_LINES = 96, TOTAL_EVENTS = 240, &
                        TOTAL_VALUES = 79, TOTAL_UPLOADS = 8, TOTAL_DOWNLOADS = 6, &
                        TOTAL_KERNELS = 3, PEAK_OBJECTS = 6, LIVE_LIMIT = 2
  integer(int64), parameter :: TOTAL_UPLOAD_BYTES = 1332, TOTAL_DOWNLOAD_BYTES = 948, &
                               PEAK_TRACKED_BYTES = 960, LEDGER_LIMIT = 65536, CALLER_LIMIT = 384
  !> Drain expectations other than a prepare with failure index 0..6.
  integer, parameter :: EXPECT_RELEASE = -1, EXPECT_NOTHING = -2, MAX_EXPECTED = 24

  type(resource_workspace) :: workspace(INSTANCES)
  !> Distinct caller destinations; never mapped and never aliases of staging.
  real(real64), allocatable :: caller_a(:), caller_b(:)
  !> Ownership summed over all instances at the last sample, and its peaks:
  !> host arrays, device allocations, mappings; host and device bytes.
  integer :: live(3) = 0, peak(3) = 0
  integer(int64) :: live_bytes(2) = 0, peak_bytes(2) = 0, caller_bytes = 0
  integer :: lines_written = 0, events_written = 0, value_records = 0
  integer :: failure_cases = 0, recovery_cases = 0
  !> Frozen event sequence expected from the operation being drained.
  integer :: want_count = 0
  integer :: want_buffer(MAX_EXPECTED) = 0, want_action(MAX_EXPECTED) = 0, want_result(MAX_EXPECTED) = 0
  integer :: k, i, status

  if (command_argument_count() /= 0) &
    call stop_with(EXIT_CHECK_FAILED, 'CHECK_FAILED the harness takes no arguments')
  call check_device_property_prefix()
  call select_nvidia_device()
  call emit('M3B0 1')
  do i = 1, INSTANCES
    call m3b_label(workspace(i), LABELS(i), status)
    call require(status == M3B_OK, 'label of workspace '//LABELS(i))
  end do

  ! 1. Six injected allocation failures at N=5, each followed by one recovery
  !    of the same instance. No kernels or transfers.
  do k = 1, FAILURE_INDICES
    call m3b_inject_failure(workspace(WS_T), k, status)
    call require(status == M3B_OK, 'failure index '//itoa(k))
    call m3b_prepare(workspace(WS_T), FAILURE_POINTS, status)
    call drain(WS_T, 2*k - 1, FAILURE_POINTS, k)
    call case_record('FAIL', k, status, ALLOCATION_FAILURE)
    failure_cases = failure_cases + 1

    call m3b_prepare(workspace(WS_T), FAILURE_POINTS, status)
    call drain(WS_T, 2*k, FAILURE_POINTS, 0)
    if (status == M3B_OK) then
      call m3b_release(workspace(WS_T), status)
      call drain(WS_T, 2*k, FAILURE_POINTS, EXPECT_RELEASE)
    end if
    call case_record('RECOVER', k, status, 0)
    recovery_cases = recovery_cases + 1
  end do

  ! 2. Distinct caller destinations, then A (N=17) and B (N=31) live
  !    together, each with its exact input uploaded.
  allocate(caller_a(A_POINTS), stat=status)
  call require(status == 0, 'allocation of caller array A')
  allocate(caller_b(B_POINTS), stat=status)
  call require(status == 0, 'allocation of caller array B')
  caller_bytes = (size(caller_a, kind=int64) + size(caller_b, kind=int64))*(storage_size(caller_a)/8)
  call require(caller_bytes == CALLER_LIMIT, 'caller array bytes')
  call m3b_prepare(workspace(WS_A), A_POINTS, status)
  call drain(WS_A, 1, A_POINTS, 0)
  call require(status == M3B_OK, 'prepare A')
  call m3b_prepare(workspace(WS_B), B_POINTS, status)
  call drain(WS_B, 1, B_POINTS, 0)
  call require(status == M3B_OK, 'prepare B')
  call require(all(live == PEAK_OBJECTS) .and. all(live_bytes == PEAK_TRACKED_BYTES), &
               'ownership while A and B are both live')
  do i = 1, A_POINTS
    call m3b_set_input(workspace(WS_A), i, real(i - 9, real64)/8.0_real64, status)
    call require(status == M3B_OK, 'input A')
  end do
  do i = 1, B_POINTS
    call m3b_set_input(workspace(WS_B), i, -real(i + 3, real64)/16.0_real64, status)
    call require(status == M3B_OK, 'input B')
  end do
  call m3b_upload_input(workspace(WS_A), status)
  call require(status == M3B_OK, 'upload of input A')
  call m3b_upload_input(workspace(WS_B), status)
  call require(status == M3B_OK, 'upload of input B')

  ! 3. One kernel each for A and B.
  call run_case(WS_A, 'A', caller_a)
  call run_case(WS_B, 'B', caller_b)

  ! 4. Release A while B stays live, run B once more from its unchanged
  !    input, release B, then the defined empty release of A.
  call m3b_release(workspace(WS_A), status)
  call drain(WS_A, 1, A_POINTS, EXPECT_RELEASE)
  call require(status == M3B_OK, 'release A')
  call require_owned(WS_A, 0, 0_int64)
  call require_owned(WS_B, BUFFERS, 20_int64*B_POINTS)
  call run_case(WS_B, 'B_AFTER_A_FREE', caller_b)
  call m3b_release(workspace(WS_B), status)
  call drain(WS_B, 1, B_POINTS, EXPECT_RELEASE)
  call require(status == M3B_OK, 'release B')
  call m3b_release(workspace(WS_A), status)
  call drain(WS_A, 1, A_POINTS, EXPECT_NOTHING)
  call require(status == M3B_OK, 'empty release of A')
  deallocate(caller_a, caller_b, stat=status)
  call require(status == 0, 'deallocation of the caller arrays')
  call finish()

contains

  !> Retain the bounded C string prefix; Fortran TRIM alone keeps NUL padding.
  !> A property with no NUL retains all its characters, including a full buffer.
  pure function device_property_prefix(raw) result(text)
    character(len=*), intent(in) :: raw
    character(len=len(raw)) :: text
    integer :: first_nul
    text = raw
    first_nul = index(raw, achar(0))
    if (first_nul > 0) text(first_nul:) = ' '
  end function device_property_prefix

  !> Silent host-only checks, before any device call; no protocol counters change.
  subroutine check_device_property_prefix()
    character(len=256) :: raw
    raw = 'NVIDIA'//repeat(achar(0), len(raw) - 6)
    call require(trim(device_property_prefix(raw)) == 'NVIDIA', 'NUL-padded device property')
    raw = repeat('X', len(raw))
    call require(len_trim(device_property_prefix(raw)) == len(raw) .and. &
                 device_property_prefix(raw) == raw, 'full-width device property without NUL')
    raw = achar(0)//'hidden'
    call require(len_trim(device_property_prefix(raw)) == 0, 'leading NUL device property')
    raw = 'NV'//achar(0)//'hidden'//achar(0)//'tail'
    call require(trim(device_property_prefix(raw)) == 'NV', 'first embedded NUL device property')
    raw = ' '
    call require(len_trim(device_property_prefix(raw)) == 0, 'blank device property')
    call require(len(device_property_prefix('')) == 0, 'empty device property')
    raw = '  vendor name  '
    call require(trim(device_property_prefix(raw)) == '  vendor name', 'space-padded device property')
  end subroutine check_device_property_prefix

  !> Explicit NVIDIA selection of device 0; its identity goes to stderr.
  subroutine select_nvidia_device()
    integer :: devices
    character(len=256) :: name, vendor, driver
    devices = acc_get_num_devices(acc_device_nvidia)
    if (devices < 1) call stop_with(EXIT_NOT_TESTED, &
      'NOT_TESTED acc_get_num_devices(acc_device_nvidia) < 1; no host fallback is used')
    call acc_set_device_type(acc_device_nvidia)
    call acc_set_device_num(0, acc_device_nvidia)
    call acc_init(acc_device_nvidia)
    call require(acc_get_device_num(acc_device_nvidia) == 0, 'selection of NVIDIA device 0')
    name = ' '
    vendor = ' '
    driver = ' '
    call acc_get_property_string(0, acc_device_nvidia, acc_property_name, name)
    call acc_get_property_string(0, acc_device_nvidia, acc_property_vendor, vendor)
    call acc_get_property_string(0, acc_device_nvidia, acc_property_driver, driver)
    call diag('M3B0_DEVICE nvidia_devices='//itoa(devices)//' selected='// &
              itoa(acc_get_device_num(acc_device_nvidia))//' name="'//trim(device_property_prefix(name))// &
              '" vendor="'//trim(device_property_prefix(vendor))//'" driver="'// &
              trim(device_property_prefix(driver))//'"')
  end subroutine select_nvidia_device

  !> One kernel case: poison the caller destination, execute, accept the
  !> device result only through m3b_copy_result, then write N VALUE records
  !> and DONE.
  subroutine run_case(instance, tag, caller)
    integer, intent(in) :: instance
    character(len=*), intent(in) :: tag
    real(real64), intent(inout) :: caller(:)
    real(real64) :: input
    integer :: j, marker, status, case_status
    caller = transfer(POISON_BITS, 0.0_real64)
    call m3b_execute(workspace(instance), case_status)
    call require(case_status == M3B_OK, 'execution '//tag)
    call m3b_copy_result(workspace(instance), caller, case_status)
    if (case_status == M3B_RESULT_REJECTED) then
      do j = 1, size(caller)
        call m3b_value_record(workspace(instance), j, input, marker, status)
        call diag('M3B0_REJECTED '//tag//' '//itoa(j)//' marker='//itoa(marker))
      end do
      call stop_with(EXIT_RESULT_REJECTED, 'NOT_ON_DEVICE '//tag// &
                     ': a marker was not 1 or a staging value kept the poison bits')
    end if
    call require(case_status == M3B_OK, 'result copy '//tag)
    do j = 1, size(caller)
      call m3b_value_record(workspace(instance), j, input, marker, status)
      call require(status == M3B_OK, 'value record '//tag)
      call emit('VALUE '//tag//' '//itoa(j)//' '//bits_text(input)//' '//bits_text(caller(j))// &
                ' '//itoa(marker))
      value_records = value_records + 1
    end do
    call emit('DONE '//tag//' '//itoa(case_status))
  end subroutine run_case

  !> Writes a FAIL or RECOVER record with the observed status and the
  !> ownership sampled at the last drain, then checks them.
  subroutine case_record(tag, case_index, status, expected_status)
    character(len=*), intent(in) :: tag
    integer, intent(in) :: case_index, status, expected_status
    call emit(tag//' '//itoa(case_index)//' '//itoa(status)//' '//itoa(live(1))//' '// &
              itoa(live(2))//' '//itoa(live(3)))
    call require(status == expected_status .and. all(live == 0) .and. all(live_bytes == 0), &
                 tag//' '//itoa(case_index))
  end subroutine case_record

  !> Writes the pending events of one instance to stderr in recorded order,
  !> requires exactly the frozen sequence of the operation just performed (a
  !> prepare with failure index 0..6, EXPECT_RELEASE or EXPECT_NOTHING),
  !> clears them and samples the ownership of all instances.
  subroutine drain(instance, generation, points, operation)
    integer, intent(in) :: instance, generation, points, operation
    integer :: pending, j
    type(resource_event) :: event
    pending = m3b_event_count(workspace(instance))
    do j = 1, pending
      event = m3b_event_at(workspace(instance), j)
      call diag('M3B0_RESOURCE '//event%workspace//' '//itoa(event%generation)//' '// &
                trim(buffer_name(event%buffer))//' '//trim(action_name(event%action))//' '// &
                itoa64(event%bytes)//' '//itoa(event%result))
    end do
    events_written = events_written + pending
    call expected_events(operation)
    call require(pending == want_count .and. m3b_dropped_events(workspace(instance)) == 0, &
                 'event count of workspace '//LABELS(instance))
    call require(m3b_generation(workspace(instance)) == generation, &
                 'generation of workspace '//LABELS(instance))
    do j = 1, pending
      event = m3b_event_at(workspace(instance), j)
      call require(event%workspace == LABELS(instance) .and. event%generation == generation .and. &
                   event%buffer == want_buffer(j) .and. event%action == want_action(j) .and. &
                   event%bytes == fixture_bytes(points, want_buffer(j)) .and. &
                   event%result == want_result(j), &
                   'event '//itoa(j)//' of workspace '//LABELS(instance))
    end do
    call m3b_clear_events(workspace(instance))
    call sample()
  end subroutine drain

  !> The frozen event sequence of one operation: the acquisition prefix up to
  !> an injected failure (host input, output, marker; then per device buffer
  !> D_ALLOC, MAP, PRESENT 1), followed by the reverse unwind of what was
  !> acquired (per device buffer UNMAP, PRESENT 0, D_FREE; then H_FREE).
  subroutine expected_events(operation)
    integer, intent(in) :: operation
    integer :: step, acquired
    want_count = 0
    if (operation == EXPECT_NOTHING) return
    acquired = 2*BUFFERS
    if (operation /= EXPECT_RELEASE) then
      do step = 1, 2*BUFFERS
        if (step == operation) then
          if (step <= BUFFERS) then
            call expect(step, ACT_H_FAIL, ALLOCATION_FAILURE)
          else
            call expect(step - BUFFERS, ACT_D_FAIL, ALLOCATION_FAILURE)
          end if
          acquired = step - 1
          exit
        end if
        if (step <= BUFFERS) then
          call expect(step, ACT_H_ALLOC, 0)
        else
          call expect(step - BUFFERS, ACT_D_ALLOC, 0)
          call expect(step - BUFFERS, ACT_MAP, 0)
          call expect(step - BUFFERS, ACT_PRESENT, 1)
        end if
      end do
      if (operation == 0) return
    end if
    do step = acquired, BUFFERS + 1, -1
      call expect(step - BUFFERS, ACT_UNMAP, 0)
      call expect(step - BUFFERS, ACT_PRESENT, 0)
      call expect(step - BUFFERS, ACT_D_FREE, 0)
    end do
    do step = min(acquired, BUFFERS), 1, -1
      call expect(step, ACT_H_FREE, 0)
    end do
  end subroutine expected_events

  subroutine expect(buffer, action, result)
    integer, intent(in) :: buffer, action, result
    call require(want_count < MAX_EXPECTED, 'capacity of the expected event list')
    want_count = want_count + 1
    want_buffer(want_count) = buffer
    want_action(want_count) = action
    want_result(want_count) = result
  end subroutine expect

  !> Ownership summed over all instances; updates the peaks and requires at
  !> most two live instances.
  subroutine sample()
    integer :: j, host, device, mappings, instances_live
    integer(int64) :: host_bytes, device_bytes
    live = 0
    live_bytes = 0
    instances_live = 0
    do j = 1, INSTANCES
      call m3b_live(workspace(j), host, device, mappings, host_bytes, device_bytes)
      live = live + [host, device, mappings]
      live_bytes = live_bytes + [host_bytes, device_bytes]
      if (host + device + mappings > 0) instances_live = instances_live + 1
    end do
    peak = max(peak, live)
    peak_bytes = max(peak_bytes, live_bytes)
    call require(instances_live <= LIVE_LIMIT, 'at most two live workspaces')
  end subroutine sample

  !> Requires one instance to own `objects` host arrays, device allocations
  !> and mappings, with `bytes` tracked bytes on each side.
  subroutine require_owned(instance, objects, bytes)
    integer, intent(in) :: instance, objects
    integer(int64), intent(in) :: bytes
    integer :: host, device, mappings
    integer(int64) :: host_bytes, device_bytes
    call m3b_live(workspace(instance), host, device, mappings, host_bytes, device_bytes)
    call require(host == objects .and. device == objects .and. mappings == objects .and. &
                 host_bytes == bytes .and. device_bytes == bytes, &
                 'ownership of workspace '//LABELS(instance))
  end subroutine require_owned

  !> Final accounting to stderr, the END record, then the remaining checks.
  subroutine finish()
    integer :: j, uploads, downloads, kernels, n_up, n_down, n_kernels, dropped
    integer(int64) :: upload_bytes, download_bytes, up_bytes, down_bytes, ledger_bytes
    logical :: ledgers_ok
    uploads = 0
    downloads = 0
    kernels = 0
    upload_bytes = 0
    download_bytes = 0
    ledgers_ok = .true.
    do j = 1, INSTANCES
      call m3b_transfers(workspace(j), n_up, up_bytes, n_down, down_bytes, n_kernels)
      uploads = uploads + n_up
      upload_bytes = upload_bytes + up_bytes
      downloads = downloads + n_down
      download_bytes = download_bytes + down_bytes
      kernels = kernels + n_kernels
      ledger_bytes = m3b_ledger_bytes(workspace(j))
      dropped = m3b_dropped_events(workspace(j))
      call diag('M3B0_LEDGER workspace='//LABELS(j)//' bytes='//itoa64(ledger_bytes)// &
                ' dropped='//itoa(dropped))
      ledgers_ok = ledgers_ok .and. ledger_bytes <= LEDGER_LIMIT .and. dropped == 0
    end do
    call sample()
    call diag('M3B0_TOTALS events='//itoa(events_written)//' uploads='//itoa(uploads)// &
              ' upload_bytes='//itoa64(upload_bytes)//' downloads='//itoa(downloads)// &
              ' download_bytes='//itoa64(download_bytes)//' kernels='//itoa(kernels)// &
              ' peak_host='//itoa(peak(1))//' peak_device='//itoa(peak(2))// &
              ' peak_mappings='//itoa(peak(3))//' peak_host_bytes='//itoa64(peak_bytes(1))// &
              ' peak_device_bytes='//itoa64(peak_bytes(2))//' caller_bytes='// &
              itoa64(caller_bytes)//' caller_arrays_allocated='// &
              itoa(count([allocated(caller_a), allocated(caller_b)])))
    call emit('END '//itoa(failure_cases)//' '//itoa(recovery_cases)//' '//itoa(value_records)// &
              ' '//itoa(kernels)//' '//itoa(live(1))//' '//itoa(live(2))//' '//itoa(live(3)))
    flush(output_unit)
    call require(lines_written == TOTAL_LINES, 'stdout records')
    call require(events_written == TOTAL_EVENTS, 'resource events')
    call require(failure_cases == FAILURE_INDICES .and. recovery_cases == FAILURE_INDICES, &
                 'failure and recovery cases')
    call require(value_records == TOTAL_VALUES, 'value records')
    call require(uploads == TOTAL_UPLOADS .and. upload_bytes == TOTAL_UPLOAD_BYTES, 'uploads')
    call require(downloads == TOTAL_DOWNLOADS .and. download_bytes == TOTAL_DOWNLOAD_BYTES, &
                 'downloads')
    call require(kernels == TOTAL_KERNELS, 'kernels')
    call require(all(peak == PEAK_OBJECTS) .and. all(peak_bytes == PEAK_TRACKED_BYTES), &
                 'peak ownership')
    call require(all(live == 0) .and. all(live_bytes == 0), 'final zero ownership')
    call require(.not. (allocated(caller_a) .or. allocated(caller_b)), 'caller arrays freed')
    call require(ledgers_ok, 'bounded and complete ledgers')
  end subroutine finish

  !> Contract BYTES of a buffer: 8*N for IN and OUT, 4*N for MARK.
  pure function fixture_bytes(points, buffer) result(bytes)
    integer, intent(in) :: points, buffer
    integer(int64) :: bytes
    bytes = int(points, int64)*merge(4_int64, 8_int64, buffer == BUF_MARK)
  end function fixture_bytes

  !> One protocol record on stdout. Arguments are evaluated before the
  !> WRITE, so no I/O happens inside another I/O statement.
  subroutine emit(line)
    character(len=*), intent(in) :: line
    write(output_unit, '(a)') line
    lines_written = lines_written + 1
  end subroutine emit

  !> One diagnostic line on stderr, flushed to keep runtime traces in order.
  subroutine diag(line)
    character(len=*), intent(in) :: line
    write(error_unit, '(a)') line
    flush(error_unit)
  end subroutine diag

  subroutine require(condition, what)
    logical, intent(in) :: condition
    character(len=*), intent(in) :: what
    if (.not. condition) call stop_with(EXIT_CHECK_FAILED, 'CHECK_FAILED '//what)
  end subroutine require

  !> Diagnostic on stderr, then error termination with exit status 2, 3 or 4.
  subroutine stop_with(code, message)
    integer, intent(in) :: code
    character(len=*), intent(in) :: message
    flush(output_unit)
    call diag('M3B0_'//message)
    select case (code)
    case (EXIT_NOT_TESTED)
      error stop 3
    case (EXIT_RESULT_REJECTED)
      error stop 4
    case default
      error stop 2
    end select
  end subroutine stop_with

  function itoa(value) result(text)
    integer, intent(in) :: value
    character(len=:), allocatable :: text
    character(len=24) :: buffer
    write(buffer, '(i0)') value
    text = trim(buffer)
  end function itoa

  function itoa64(value) result(text)
    integer(int64), intent(in) :: value
    character(len=:), allocatable :: text
    character(len=24) :: buffer
    write(buffer, '(i0)') value
    text = trim(buffer)
  end function itoa64

  !> The 64 IEEE bits of x as 16 upper-case hexadecimal digits.
  function bits_text(x) result(text)
    real(real64), intent(in) :: x
    character(len=16) :: text
    character(len=*), parameter :: HEX = '0123456789ABCDEF'
    integer(int64) :: bits
    integer :: d, nibble
    bits = transfer(x, 0_int64)
    do d = 16, 1, -1
      nibble = int(iand(bits, 15_int64))
      text(d:d) = HEX(nibble + 1:nibble + 1)
      bits = shiftr(bits, 4)
    end do
  end function bits_text

end program m3b_resources
