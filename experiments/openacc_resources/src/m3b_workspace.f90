! SPDX-License-Identifier: MIT
!> M3B0 private OpenACC resource workspace (docs/openacc-resource-contract.md).
!>
!> An instance owns exactly three host arrays (binary64 input, binary64
!> output staging, int32 device markers), one explicit device allocation per
!> array and the mapping between them. Caller arrays are never mapped. There
!> is no module state, pool, cache, resize or retry. Every procedure is
!> RECURSIVE so that its locals are automatic: the frozen flags omit
!> -Mrecursive, under which NVHPC may keep address-taken locals in static
!> storage. The module performs no I/O, contains no STOP and installs no
!> OpenACC error callback; a fatal runtime error terminates the process.
!>
!> * Prepare acquires host input, output and marker arrays (checked STAT),
!>   then for input, output and marker in turn: acc_malloc (null-checked),
!>   map the host array onto it and query that it is present.
!> * A failed acquisition and a release use one unwind path that touches only
!>   what was acquired, in reverse order: for marker, output and input, unmap
!>   a live mapping, query its absence while the host array is still
!>   allocated, free the device allocation; then free the host marker, output
!>   and input. Releasing an instance that owns nothing records nothing.
!> * A test-only failure index 1..6, consumed by the next accepted prepare,
!>   skips that acquisition and enters the same branch as a failed
!>   allocation. It models allocation failure; it does not exercise actual
!>   device OOM.
!> * Execution poisons host staging (quiet NaN) and markers (zero) and
!>   uploads both before the kernel, poisons the host copies again before
!>   downloading them, and uses only synchronous constructs. A caller array
!>   receives the staging values only after every downloaded marker is 1 and
!>   no value still carries the poison bits.
!>
!> Status: 0 success; 1 invalid request, nothing changed; 4 device result
!> rejected; 5 allocation failure, unwound to empty; 7 the runtime contradicted
!> a completed map or unmap, or a host deallocation failed. After status 7 the
!> instance is broken: it stopped at once, keeps whatever it still owned (so it
!> frees nothing the runtime may still reference) and refuses later requests.
module m3b_workspace
  use, intrinsic :: iso_fortran_env, only: real64, int32, int64
  use, intrinsic :: iso_c_binding, only: c_size_t
  use openacc, only: acc_malloc, acc_free, acc_map_data, acc_unmap_data, acc_is_present, &
                     acc_on_device, acc_device_nvidia, c_devptr, c_null_devptr, operator(==)
  use m3b_ledger, only: resource_event, event_ledger, ledger_record, ledger_count, &
                        ledger_event, ledger_clear, ledger_dropped, BUFFERS, BUF_IN, BUF_OUT, &
                        BUF_MARK, ACT_H_ALLOC, ACT_H_FAIL, ACT_D_ALLOC, ACT_D_FAIL, ACT_MAP, &
                        ACT_PRESENT, ACT_UNMAP, ACT_D_FREE, ACT_H_FREE
  implicit none
  private
  public :: resource_workspace
  public :: m3b_label, m3b_inject_failure, m3b_prepare, m3b_release
  public :: m3b_set_input, m3b_upload_input, m3b_execute, m3b_copy_result, m3b_value_record
  public :: m3b_live, m3b_generation, m3b_transfers
  public :: m3b_event_count, m3b_event_at, m3b_clear_events, m3b_dropped_events, m3b_ledger_bytes

  integer, parameter, public :: M3B_OK = 0, M3B_INVALID = 1, M3B_RESULT_REJECTED = 4, &
                                M3B_ALLOCATION_FAILURE = 5, M3B_INCONSISTENT = 7
  !> Points per workspace; tracked bytes are 20*points each on host and device.
  integer, parameter, public :: MAX_POINTS = 1024
  !> Acquisitions in order: host input, output, marker; device input, output, marker.
  integer, parameter, public :: ACQUISITIONS = 2*BUFFERS
  !> Quiet NaN written to host and device staging before every use.
  integer(int64), parameter, public :: POISON_BITS = int(z'7FF8000000000BAD', int64)
  integer(int64), parameter :: REAL_BYTES = storage_size(0.0_real64, int64)/8
  integer(int64), parameter :: MARK_BYTES = storage_size(0_int32, int64)/8

  !> Private resource workspace. Instances must not be copied: a copy would
  !> claim the same device allocations.
  type :: resource_workspace
    private
    character(len=1) :: label = ' '
    integer :: generation = 0
    integer :: points = 0
    integer :: fail_at = 0
    logical :: broken = .false.
    real(real64), allocatable :: input(:), staging(:)
    integer(int32), allocatable :: marker(:)
    type(c_devptr) :: device(BUFFERS) = c_null_devptr
    logical :: mapped(BUFFERS) = .false.
    logical :: input_uploaded = .false.
    logical :: result_ready = .false.
    integer :: uploads = 0, downloads = 0, kernels = 0
    integer(int64) :: upload_bytes = 0, download_bytes = 0
    type(event_ledger) :: ledger
  end type resource_workspace

contains

  !> Names the instance once (one upper-case letter); every event carries it.
  recursive subroutine m3b_label(ws, label, status)
    type(resource_workspace), intent(inout) :: ws
    character(len=1), intent(in) :: label
    integer, intent(out) :: status
    status = M3B_INVALID
    if (ws%label /= ' ' .or. index('ABCDEFGHIJKLMNOPQRSTUVWXYZ', label) == 0) return
    ws%label = label
    status = M3B_OK
  end subroutine m3b_label

  !> Test-only seam: the next prepare fails acquisition fail_index (1..6, in
  !> ACQUISITIONS order) through its ordinary failure branch; 0 disables it.
  recursive subroutine m3b_inject_failure(ws, fail_index, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: fail_index
    integer, intent(out) :: status
    status = M3B_INVALID
    if (fail_index < 0 .or. fail_index > ACQUISITIONS) return
    ws%fail_at = fail_index
    status = M3B_OK
  end subroutine m3b_inject_failure

  !> Acquires the three host arrays and their device allocations and
  !> mappings for 1..MAX_POINTS points, as a new generation of the instance.
  recursive subroutine m3b_prepare(ws, points, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: points
    integer, intent(out) :: status
    integer :: fail_at, step, unwind_status
    if (ws%broken) then
      status = M3B_INCONSISTENT
      return
    end if
    status = M3B_INVALID
    if (ws%label == ' ' .or. owns_any(ws) .or. points < 1 .or. points > MAX_POINTS) return
    fail_at = ws%fail_at
    ws%fail_at = 0
    ws%generation = ws%generation + 1
    ws%points = points
    ws%input_uploaded = .false.
    ws%result_ready = .false.
    do step = 1, ACQUISITIONS
      if (step <= BUFFERS) then
        call acquire_host(ws, step, step == fail_at, status)
      else
        call acquire_device(ws, step - BUFFERS, step == fail_at, status)
      end if
      if (status /= M3B_OK) exit
    end do
    if (status == M3B_ALLOCATION_FAILURE) then
      call unwind(ws, unwind_status)
      if (unwind_status /= M3B_OK) status = unwind_status
    end if
  end subroutine m3b_prepare

  !> Releases everything the instance owns through the unwind path. Releasing
  !> an instance that owns nothing is a defined no-op.
  recursive subroutine m3b_release(ws, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(out) :: status
    if (ws%broken) then
      status = M3B_INCONSISTENT
    else if (owns_any(ws)) then
      call unwind(ws, status)
    else
      status = M3B_OK
    end if
  end subroutine m3b_release

  !> Sets host input element `element` of a prepared instance; the input must
  !> be uploaded again before the next execution.
  recursive subroutine m3b_set_input(ws, element, value, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: element
    real(real64), intent(in) :: value
    integer, intent(out) :: status
    status = M3B_INVALID
    if (.not. prepared(ws) .or. element < 1 .or. element > ws%points) return
    ws%input(element) = value
    ws%input_uploaded = .false.
    ws%result_ready = .false.
    status = M3B_OK
  end subroutine m3b_set_input

  !> Synchronously uploads the host input array to its mapped device copy.
  recursive subroutine m3b_upload_input(ws, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(out) :: status
    status = M3B_INVALID
    if (.not. prepared(ws)) return
    call upload_real(ws%points, ws%input)
    call count_transfer(ws, BUF_IN, .true.)
    ws%input_uploaded = .true.
    status = M3B_OK
  end subroutine m3b_upload_input

  !> One fixture execution: staging(i) = input(i) + 1 and marker(i) =
  !> acc_on_device(acc_device_nvidia), written in the same loop iteration on
  !> the device. Poisoned staging and markers are uploaded before the kernel;
  !> the host copies are poisoned again before the synchronous downloads.
  recursive subroutine m3b_execute(ws, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(out) :: status
    status = M3B_INVALID
    if (.not. (prepared(ws) .and. ws%input_uploaded)) return
    ws%result_ready = .false.
    call poison_host(ws)
    call upload_real(ws%points, ws%staging)
    call count_transfer(ws, BUF_OUT, .true.)
    call upload_marker(ws%points, ws%marker)
    call count_transfer(ws, BUF_MARK, .true.)
    call add_one(ws%points, ws%input, ws%staging, ws%marker)
    ws%kernels = ws%kernels + 1
    call poison_host(ws)
    call download_real(ws%points, ws%staging)
    call count_transfer(ws, BUF_OUT, .false.)
    call download_marker(ws%points, ws%marker)
    call count_transfer(ws, BUF_MARK, .false.)
    ws%result_ready = .true.
    status = M3B_OK
  end subroutine m3b_execute

  !> Copies the staging values of the last execution into a distinct caller
  !> array of `points` elements, only after its synchronous downloads, when
  !> every marker is 1 and no value still carries the poison bits. Otherwise
  !> dest is unchanged (status 1 or 4).
  recursive subroutine m3b_copy_result(ws, dest, status)
    type(resource_workspace), intent(in) :: ws
    real(real64), intent(inout) :: dest(:)
    integer, intent(out) :: status
    integer :: i
    status = M3B_INVALID
    if (.not. (prepared(ws) .and. ws%result_ready) .or. size(dest) /= ws%points) return
    status = M3B_RESULT_REJECTED
    do i = 1, ws%points
      if (ws%marker(i) /= 1_int32 .or. transfer(ws%staging(i), 0_int64) == POISON_BITS) return
    end do
    dest = ws%staging
    status = M3B_OK
  end subroutine m3b_copy_result

  !> Host input value and downloaded marker of element `element` after an
  !> execution; the poison value and marker 0 with status 1 otherwise.
  recursive subroutine m3b_value_record(ws, element, input, marker, status)
    type(resource_workspace), intent(in) :: ws
    integer, intent(in) :: element
    real(real64), intent(out) :: input
    integer, intent(out) :: marker, status
    input = transfer(POISON_BITS, 0.0_real64)
    marker = 0
    status = M3B_INVALID
    if (.not. (prepared(ws) .and. ws%result_ready) .or. element < 1 .or. element > ws%points) return
    input = ws%input(element)
    marker = int(ws%marker(element))
    status = M3B_OK
  end subroutine m3b_value_record

  !> Owned host arrays, device allocations and mappings and their tracked
  !> bytes; runtime, descriptor, compiler-temporary and driver storage are
  !> not included.
  recursive subroutine m3b_live(ws, host, device, mappings, host_bytes, device_bytes)
    type(resource_workspace), intent(in) :: ws
    integer, intent(out) :: host, device, mappings
    integer(int64), intent(out) :: host_bytes, device_bytes
    integer :: buffer
    host = 0
    device = 0
    mappings = 0
    host_bytes = 0
    device_bytes = 0
    do buffer = 1, BUFFERS
      if (host_allocated(ws, buffer)) then
        host = host + 1
        host_bytes = host_bytes + tracked_bytes(ws%points, buffer)
      end if
      if (device_owned(ws, buffer)) then
        device = device + 1
        device_bytes = device_bytes + tracked_bytes(ws%points, buffer)
      end if
      if (ws%mapped(buffer)) mappings = mappings + 1
    end do
  end subroutine m3b_live

  recursive pure function m3b_generation(ws) result(generation)
    type(resource_workspace), intent(in) :: ws
    integer :: generation
    generation = ws%generation
  end function m3b_generation

  !> Transfers and kernels performed by this instance since it was created.
  recursive subroutine m3b_transfers(ws, uploads, upload_bytes, downloads, download_bytes, kernels)
    type(resource_workspace), intent(in) :: ws
    integer, intent(out) :: uploads, downloads, kernels
    integer(int64), intent(out) :: upload_bytes, download_bytes
    uploads = ws%uploads
    upload_bytes = ws%upload_bytes
    downloads = ws%downloads
    download_bytes = ws%download_bytes
    kernels = ws%kernels
  end subroutine m3b_transfers

  recursive pure function m3b_event_count(ws) result(count)
    type(resource_workspace), intent(in) :: ws
    integer :: count
    count = ledger_count(ws%ledger)
  end function m3b_event_count

  !> Pending event k (1..m3b_event_count) in recorded order; an event with
  !> action 0 for any other k.
  recursive pure function m3b_event_at(ws, k) result(event)
    type(resource_workspace), intent(in) :: ws
    integer, intent(in) :: k
    type(resource_event) :: event
    event = resource_event()
    if (k >= 1 .and. k <= ledger_count(ws%ledger)) event = ledger_event(ws%ledger, k)
  end function m3b_event_at

  !> Drain step: forgets the pending events once the caller has read them.
  recursive subroutine m3b_clear_events(ws)
    type(resource_workspace), intent(inout) :: ws
    call ledger_clear(ws%ledger)
  end subroutine m3b_clear_events

  recursive pure function m3b_dropped_events(ws) result(dropped)
    type(resource_workspace), intent(in) :: ws
    integer :: dropped
    dropped = ledger_dropped(ws%ledger)
  end function m3b_dropped_events

  !> Host bytes of this instance's bounded event ledger.
  recursive pure function m3b_ledger_bytes(ws) result(bytes)
    type(resource_workspace), intent(in) :: ws
    integer(int64) :: bytes
    bytes = storage_size(ws%ledger, int64)/8
  end function m3b_ledger_bytes

  !> Host acquisition of one buffer. An injected failure leaves stat nonzero
  !> without allocating and takes the same branch as a failed ALLOCATE.
  recursive subroutine acquire_host(ws, buffer, inject, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: buffer
    logical, intent(in) :: inject
    integer, intent(out) :: status
    integer :: stat
    stat = 1
    if (.not. inject) then
      select case (buffer)
      case (BUF_IN)
        allocate(ws%input(ws%points), stat=stat)
      case (BUF_OUT)
        allocate(ws%staging(ws%points), stat=stat)
      case (BUF_MARK)
        allocate(ws%marker(ws%points), stat=stat)
      end select
    end if
    if (stat == 0) then
      call log_event(ws, buffer, ACT_H_ALLOC, M3B_OK)
      status = M3B_OK
    else
      call log_event(ws, buffer, ACT_H_FAIL, M3B_ALLOCATION_FAILURE)
      status = M3B_ALLOCATION_FAILURE
    end if
  end subroutine acquire_host

  !> Device acquisition of one buffer: acc_malloc (an injected failure keeps
  !> the null pointer of a failed allocation), map, then the presence query.
  recursive subroutine acquire_device(ws, buffer, inject, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: buffer
    logical, intent(in) :: inject
    integer, intent(out) :: status
    integer(c_size_t) :: bytes
    bytes = int(tracked_bytes(ws%points, buffer), c_size_t)
    if (inject) then
      ws%device(buffer) = c_null_devptr
    else
      ws%device(buffer) = acc_malloc(bytes)
    end if
    if (ws%device(buffer) == c_null_devptr) then
      call log_event(ws, buffer, ACT_D_FAIL, M3B_ALLOCATION_FAILURE)
      status = M3B_ALLOCATION_FAILURE
      return
    end if
    call log_event(ws, buffer, ACT_D_ALLOC, M3B_OK)
    select case (buffer)
    case (BUF_IN)
      call acc_map_data(ws%input, ws%device(buffer), bytes)
    case (BUF_OUT)
      call acc_map_data(ws%staging, ws%device(buffer), bytes)
    case (BUF_MARK)
      call acc_map_data(ws%marker, ws%device(buffer), bytes)
    end select
    ws%mapped(buffer) = .true.
    call log_event(ws, buffer, ACT_MAP, M3B_OK)
    if (host_present(ws, buffer)) then
      call log_event(ws, buffer, ACT_PRESENT, 1)
      status = M3B_OK
    else
      call log_event(ws, buffer, ACT_PRESENT, 0)
      ws%broken = .true.
      status = M3B_INCONSISTENT
    end if
  end subroutine acquire_device

  !> The single cleanup path of failed prepares and of releases (see the
  !> module header). Stops at a contradicted absence query or a failed host
  !> deallocation, leaving the rest owned and the instance broken.
  recursive subroutine unwind(ws, status)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(out) :: status
    integer :: buffer, stat
    status = M3B_OK
    do buffer = BUFFERS, 1, -1
      if (ws%mapped(buffer)) then
        select case (buffer)
        case (BUF_IN)
          call acc_unmap_data(ws%input)
        case (BUF_OUT)
          call acc_unmap_data(ws%staging)
        case (BUF_MARK)
          call acc_unmap_data(ws%marker)
        end select
        ws%mapped(buffer) = .false.
        call log_event(ws, buffer, ACT_UNMAP, M3B_OK)
        if (host_present(ws, buffer)) then
          call log_event(ws, buffer, ACT_PRESENT, 1)
          ws%broken = .true.
          status = M3B_INCONSISTENT
          return
        end if
        call log_event(ws, buffer, ACT_PRESENT, 0)
      end if
      if (device_owned(ws, buffer)) then
        call acc_free(ws%device(buffer))
        ws%device(buffer) = c_null_devptr
        call log_event(ws, buffer, ACT_D_FREE, M3B_OK)
      end if
    end do
    do buffer = BUFFERS, 1, -1
      if (.not. host_allocated(ws, buffer)) cycle
      stat = 1
      select case (buffer)
      case (BUF_IN)
        deallocate(ws%input, stat=stat)
      case (BUF_OUT)
        deallocate(ws%staging, stat=stat)
      case (BUF_MARK)
        deallocate(ws%marker, stat=stat)
      end select
      if (stat /= 0) then
        call log_event(ws, buffer, ACT_H_FREE, M3B_INCONSISTENT)
        ws%broken = .true.
        status = M3B_INCONSISTENT
        return
      end if
      call log_event(ws, buffer, ACT_H_FREE, M3B_OK)
    end do
    ws%points = 0
    ws%input_uploaded = .false.
    ws%result_ready = .false.
  end subroutine unwind

  !> Actual runtime presence query for the whole host array of a buffer.
  recursive function host_present(ws, buffer) result(found)
    type(resource_workspace), intent(in) :: ws
    integer, intent(in) :: buffer
    logical :: found
    integer(c_size_t) :: bytes
    bytes = int(tracked_bytes(ws%points, buffer), c_size_t)
    select case (buffer)
    case (BUF_IN)
      found = acc_is_present(ws%input, bytes)
    case (BUF_OUT)
      found = acc_is_present(ws%staging, bytes)
    case (BUF_MARK)
      found = acc_is_present(ws%marker, bytes)
    case default
      found = .false.
    end select
  end function host_present

  recursive subroutine log_event(ws, buffer, action, result)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: buffer, action, result
    call ledger_record(ws%ledger, resource_event(ws%label, ws%generation, buffer, action, &
                                                 tracked_bytes(ws%points, buffer), result))
  end subroutine log_event

  recursive subroutine count_transfer(ws, buffer, upload)
    type(resource_workspace), intent(inout) :: ws
    integer, intent(in) :: buffer
    logical, intent(in) :: upload
    if (upload) then
      ws%uploads = ws%uploads + 1
      ws%upload_bytes = ws%upload_bytes + tracked_bytes(ws%points, buffer)
    else
      ws%downloads = ws%downloads + 1
      ws%download_bytes = ws%download_bytes + tracked_bytes(ws%points, buffer)
    end if
  end subroutine count_transfer

  !> Tracked bytes of one buffer: 8*points for input and output, 4*points
  !> for markers.
  recursive pure function tracked_bytes(points, buffer) result(bytes)
    integer, intent(in) :: points, buffer
    integer(int64) :: bytes
    if (buffer == BUF_MARK) then
      bytes = points*MARK_BYTES
    else
      bytes = points*REAL_BYTES
    end if
  end function tracked_bytes

  recursive pure function host_allocated(ws, buffer) result(owned)
    type(resource_workspace), intent(in) :: ws
    integer, intent(in) :: buffer
    logical :: owned
    select case (buffer)
    case (BUF_IN)
      owned = allocated(ws%input)
    case (BUF_OUT)
      owned = allocated(ws%staging)
    case (BUF_MARK)
      owned = allocated(ws%marker)
    case default
      owned = .false.
    end select
  end function host_allocated

  recursive function device_owned(ws, buffer) result(owned)
    type(resource_workspace), intent(in) :: ws
    integer, intent(in) :: buffer
    logical :: owned
    owned = .not. (ws%device(buffer) == c_null_devptr)
  end function device_owned

  recursive function owns_any(ws) result(owns)
    type(resource_workspace), intent(in) :: ws
    logical :: owns
    integer :: buffer
    owns = any(ws%mapped)
    do buffer = 1, BUFFERS
      owns = owns .or. host_allocated(ws, buffer) .or. device_owned(ws, buffer)
    end do
  end function owns_any

  !> All three mappings live (which implies the host arrays and device
  !> allocations) and the instance is not broken.
  recursive pure function prepared(ws) result(ready)
    type(resource_workspace), intent(in) :: ws
    logical :: ready
    ready = .not. ws%broken .and. all(ws%mapped)
  end function prepared

  recursive subroutine poison_host(ws)
    type(resource_workspace), intent(inout) :: ws
    ws%staging = transfer(POISON_BITS, 0.0_real64)
    ws%marker = 0_int32
  end subroutine poison_host

  ! Synchronous transfers of one whole mapped array. Explicit-shape dummies
  ! carry no descriptor, so each directive moves exactly that array.
  recursive subroutine upload_real(points, values)
    integer, intent(in) :: points
    real(real64), intent(in) :: values(points)
    !$acc update device(values)
  end subroutine upload_real

  recursive subroutine upload_marker(points, values)
    integer, intent(in) :: points
    integer(int32), intent(in) :: values(points)
    !$acc update device(values)
  end subroutine upload_marker

  recursive subroutine download_real(points, values)
    integer, intent(in) :: points
    real(real64), intent(inout) :: values(points)
    !$acc update self(values)
  end subroutine download_real

  recursive subroutine download_marker(points, values)
    integer, intent(in) :: points
    integer(int32), intent(inout) :: values(points)
    !$acc update self(values)
  end subroutine download_marker

  !> The fixture kernel on the mapped device arrays (present: no implicit
  !> data movement). Each iteration writes its value and the marker that
  !> certifies it.
  recursive subroutine add_one(points, input, staging, marker)
    integer, intent(in) :: points
    real(real64), intent(in) :: input(points)
    real(real64), intent(inout) :: staging(points)
    integer(int32), intent(inout) :: marker(points)
    integer :: i
    !$acc parallel loop present(input, staging, marker)
    do i = 1, points
      staging(i) = input(i) + 1.0_real64
      marker(i) = merge(1_int32, 0_int32, acc_on_device(acc_device_nvidia))
    end do
  end subroutine add_one

end module m3b_workspace
