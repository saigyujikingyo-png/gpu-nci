! SPDX-License-Identifier: MIT
!> OpenACC execution path of ABI v1 for the optional nci_openacc library
!> (docs/openacc-public-contract.md, M3B1). The common C API (nci_capi)
!> validates every descriptor, plans through acc_backend_plan before the
!> density is dereferenced, runs the common density preflight and then calls
!> acc_backend_evaluate. nci_cpu compiles nci_acc_backend_stub.f90 instead.
!>
!> * One private scalar workspace per OpenACC context owns every resource.
!>   It is reached through a C pointer made by C_LOC and C_F_POINTER of the
!>   same non-interoperable type. There is no module variable, registry,
!>   pool, shared scratch or retained capacity, and acc_shutdown is never
!>   called. Procedures are RECURSIVE (locals automatic); the build also
!>   applies -Mrecursive -Mreentrant.
!> * An evaluation acquires nine host arrays (acquisitions 1..9) and then,
!>   for each array in turn, one acc_malloc allocation mapped onto it and
!>   confirmed present (10..18). It uploads the copied density and neighbour
!>   tables, poisons and uploads the outputs and metadata, runs one
!>   synchronous kernel of the production classify_point/point_eval, poisons
!>   the host copies again and downloads and validates every marker, status,
!>   rotation count, flag and field. It then unmaps (absence confirmed) and
!>   frees every device allocation, frees the input and metadata arrays,
!>   moves the field and flag arrays to call-local staging, restores the
!>   caller's device selection and only then writes the caller's arrays. The
!>   staging is released by the automatic deallocation at the return of the
!>   committing routine, which has no returning failure path.
!> * Allocation failure: clean unwind, status 5, context reusable. Rejected
!>   device result: clean unwind, status 6, nothing written. A presence query
!>   contradicting a completed map or unmap, or a failed host deallocation,
!>   stops at once before any output is written, keeps everything still
!>   owned and marks the context broken (status 6 now and from every later
!>   call, destroy included). No status 6 follows a write of caller arrays.
!> * No I/O, no STOP, no OpenACC error callback: a fatal runtime error ends
!>   the process (the worker boundary). There is no CPU fallback.
module nci_acc_backend
  use, intrinsic :: iso_c_binding, only: c_ptr, c_null_ptr, c_loc, c_f_pointer, c_associated, &
                                         c_int, c_int32_t, c_int64_t, c_size_t
  use openacc, only: acc_malloc, acc_free, acc_map_data, acc_unmap_data, acc_is_present, &
                     acc_on_device, acc_get_num_devices, acc_get_device_type, acc_get_device_num, &
                     acc_set_device_type, acc_set_device_num, acc_device_kind, acc_device_none, &
                     acc_device_default, acc_device_not_host, acc_device_nvidia, c_devptr, &
                     c_null_devptr, operator(==)
  use nci_kinds
  use nci_abi, only: NCI_OK, NCI_INVALID_ARGUMENT, NCI_UNSUPPORTED, NCI_INVALID_INPUT, &
                     NCI_NUMERIC_FAILURE, NCI_ALLOCATION_FAILURE, NCI_BACKEND_UNAVAILABLE, &
                     FLAG_POINT_NUMERIC_FAILURE, FLAG_LAMBDA_NUM_UNCERTAIN, &
                     FLAG_LAMBDA_SCI_UNCERTAIN, FLAG_NOT_VALID_MASK
  use nci_numerics, only: point_result, point_eval, stencil61, underflow_floor, &
                          JACOBI_MAX_ROTATIONS, PT_OK, PT_NONFINITE_DERIVATIVE, PT_NONFINITE_RESULT
  use nci_validate, only: message_t, msg_set, msg_add, msg_add_int, tile_layout, mul_overflows
  use nci_kernel, only: axis_table, classify_point
  implicit none
  private

  !> This module is the real backend (the stub sets .false.).
  logical, parameter, public :: ACC_BACKEND_COMPILED = .true.
  !> Frozen private observation shapes and the acquisition count.
  integer, parameter, public :: ACC_OBSERVE_VALUES = 24
  integer, parameter, public :: ACC_EVENT_COLUMNS = 6
  integer, parameter, public :: ACC_EVENT_CAPACITY = 256
  integer, parameter, public :: ACC_ACQUISITIONS = 18
  integer, parameter, public :: ACC_FIXED_STORAGE_ITEMS = 4

  public :: acc_backend_create, acc_backend_destroy, acc_backend_admit, acc_backend_plan
  public :: acc_backend_evaluate, acc_test_configure, acc_test_observe, acc_fixed_storage

  !> The nine tracked objects, in acquisition order.
  integer, parameter :: OBJECTS = 9
  integer, parameter :: OBJ_RHO = 1, OBJ_TX = 2, OBJ_TY = 3, OBJ_TZ = 4, OBJ_FIELDS = 5, &
                        OBJ_FLAGS = 6, OBJ_STATUS = 7, OBJ_NROT = 8, OBJ_MARKER = 9

  !> Event actions (column 2 of acc_test_observe events).
  integer, parameter :: ACT_HOST_ACQUIRE = 1, ACT_DEVICE_ACQUIRE = 2, ACT_MAP = 3, &
                        ACT_UPLOAD = 4, ACT_KERNEL = 5, ACT_DOWNLOAD = 6, ACT_UNMAP = 7, &
                        ACT_DEVICE_FREE = 8, ACT_HOST_FREE = 9, ACT_MOVE_TO_CALL = 10, &
                        ACT_CALL_FREE = 11

  !> Positions of the 24 observation values.
  integer, parameter :: V_SCHEMA = 1, V_CALL = 2, V_PLANNED_HOST = 3, V_PLANNED_DEVICE = 4, &
                        V_PEAK_HOST = 5, V_PEAK_DEVICE = 6, V_FINAL_HOST = 7, &
                        V_FINAL_DEVICE = 8, V_PEAK_MAPS = 9, V_FINAL_MAPS = 10, &
                        V_ATTEMPTS = 11, V_STATUS = 12, V_POINTS = 13, V_KERNELS = 14, &
                        V_UPLOADS = 15, V_UPLOAD_BYTES = 16, V_DOWNLOADS = 17, &
                        V_DOWNLOAD_BYTES = 18, V_FAIL_INDEX = 19, V_FAIL_STATUS = 20, &
                        V_FAIL_NROT = 21, V_MARKERS = 22, V_BROKEN = 23, V_EVENTS = 24
  integer(i64), parameter :: SCHEMA_VERSION = 1

  integer(i64), parameter :: WS_MAGIC = int(z'4E43495F41434331', i64)
  !> M3B0's inspection of the installed runtime found a 32-bit byte count in
  !> acc_is_present: each mapped object is limited to the int32 maximum.
  integer(i64), parameter :: MAX_OBJECT_BYTES = int(huge(0_c_int32_t), i64)

  !> Element sizes of the tracked arrays, from the compiled kinds.
  integer(i64), parameter :: REAL_BYTES = storage_size(0.0_dp, i64)/8
  integer(i64), parameter :: INDEX_BYTES = storage_size(0_i64, i64)/8
  integer(i64), parameter :: FLAG_BYTES = storage_size(0_i8, i64)/8
  integer(i64), parameter :: INT32_BYTES = storage_size(0_i32, i64)/8
  !> Neighbour offsets -2..2 per coordinate; packed FP64 values per point.
  integer(i64), parameter :: TABLE_ENTRIES = 5, FULL_FIELDS = 3, DIAGNOSTIC_FIELDS = 12
  !> Kernel launch scalars: 8 int64, 11 FP64 and 5 logical values.
  integer(i64), parameter :: LAUNCH_SCALAR_BYTES = (8*storage_size(0_i64, i64) &
    + 11*storage_size(0.0_dp, i64) + 5*storage_size(.true., i64))/8

  !> Poison written to host staging and metadata before each upload and each
  !> download: fields the quiet NaN 7FF800000000DEAD, distinct from the
  !> canonical QNAN_BITS that the kernel writes; flags the bit pattern A5
  !> (bit 7 is used by no flag); status and nrot INT32_MIN; marker -1.
  integer(i64), parameter :: FIELD_POISON_BITS = int(z'7FF800000000DEAD', i64)
  integer(i8), parameter :: FLAG_POISON = int(int(z'A5', i32) - 256_i32, i8)
  integer(i32), parameter :: INT_POISON = -huge(0_i32) - 1_i32
  integer(i32), parameter :: MARKER_POISON = -1
  integer(i32), parameter :: STATUS_CLASSIFIED_INVALID = -1
  integer(i32), parameter :: MARKER_ON_DEVICE = 1
  integer(i32), parameter :: MAX_CORRUPTION = 2
  !> Test corruption 2 sets the downloaded status of output point 1 to this.
  integer(i32), parameter :: CORRUPT_STATUS = INT_POISON + 1_i32
  !> Flags of a classified-invalid point use only bits 0-3.
  integer, parameter :: CLASSIFIED_FLAGS_MAX = 15

  character(len=*), parameter :: BROKEN_MESSAGE = 'OpenACC context is broken: the runtime ' // &
    'contradicted a mapping or a release failed; unsafe ownership is retained; destroy it'

  !> The nine host arrays of one evaluation (ids above).
  type :: owned_arrays
    real(dp), allocatable :: rho(:)
    integer(i64), allocatable :: tx(:, :), ty(:, :), tz(:, :)
    real(dp), allocatable :: fields(:, :)
    integer(i8), allocatable :: flags(:)
    integer(i32), allocatable :: pstat(:), nrot(:), marker(:)
  end type owned_arrays

  !> Checked sizes of one evaluation.
  type :: workspace_plan
    logical :: ready = .false.
    integer(i64) :: nin = 0, nb = 0, ny = 0, nz = 0, nout = 0, nf = 0
    integer(i64) :: bytes(OBJECTS) = 0
    integer(i64) :: total = 0
  end type workspace_plan

  !> Device selection of the calling thread saved at a runtime entry.
  type :: device_state
    logical :: concrete = .false.
    integer(acc_device_kind) :: device_type = acc_device_none
    integer :: device_num = 0
  end type device_state

  !> Private per-context workspace. Never copied: a copy would claim the same
  !> device allocations.
  type :: acc_workspace
    integer(i64) :: magic = 0
    integer :: device_num = 0
    logical :: broken = .false.
    integer(i32) :: fail_at = 0
    integer(i32) :: corruption = 0
    type(workspace_plan) :: plan
    type(owned_arrays) :: host
    type(c_devptr) :: device(OBJECTS) = c_null_devptr
    logical :: mapped(OBJECTS) = .false.
    integer(i64) :: live_host = 0, live_device = 0, live_maps = 0
    integer(i64) :: call_ordinal = 0
    integer(i64) :: event_total = 0
    integer(i64) :: values(ACC_OBSERVE_VALUES) = 0
    integer(i64) :: events(ACC_EVENT_COLUMNS, ACC_EVENT_CAPACITY) = 0
  end type acc_workspace

contains

  ! ------------------------------------------------------------------------
  ! Context lifetime
  ! ------------------------------------------------------------------------

  !> Requires an NVIDIA device, allocates the workspace and checks that this
  !> thread can select NVIDIA device 0, restoring its prior concrete state.
  recursive subroutine acc_backend_create(handle, status, msg)
    type(c_ptr), intent(out) :: handle
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    type(acc_workspace), pointer :: ws
    type(device_state) :: saved
    logical :: selected
    integer :: ierr

    handle = c_null_ptr
    status = NCI_BACKEND_UNAVAILABLE
    if (acc_get_num_devices(acc_device_nvidia) < 1) then
      call msg_set(msg, 'no NVIDIA OpenACC device is available; there is no CPU fallback')
      return
    end if
    allocate (ws, stat=ierr)
    if (ierr /= 0) then
      status = NCI_ALLOCATION_FAILURE
      call msg_set(msg, 'cannot allocate the OpenACC context workspace')
      return
    end if
    ws%magic = WS_MAGIC
    ws%device_num = 0
    call reset_observation(ws)
    call save_device(saved)
    call select_device(ws%device_num, selected)
    call restore_device(saved)
    if (.not. selected) then
      ws%magic = 0
      deallocate (ws, stat=ierr)
      call msg_set(msg, 'cannot select NVIDIA OpenACC device 0')
      return
    end if
    handle = c_loc(ws)
    status = NCI_OK
  end subroutine acc_backend_create

  !> Releases a healthy workspace (it owns nothing between evaluations).
  !> A broken workspace is kept, with everything it still owns: status 6.
  !> So is one whose deallocation fails: its magic is never cleared, so the
  !> handle that the C API keeps stays a valid, now broken, workspace.
  recursive subroutine acc_backend_destroy(handle, status, msg)
    type(c_ptr), intent(in) :: handle
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    type(acc_workspace), pointer :: ws
    type(device_state) :: saved
    logical :: selected
    integer :: ierr

    status = NCI_INVALID_ARGUMENT
    call workspace_of(handle, ws)
    if (.not. associated(ws)) then
      call msg_set(msg, 'invalid OpenACC context workspace')
      return
    end if
    status = NCI_BACKEND_UNAVAILABLE
    if (.not. ws%broken .and. owns_any(ws)) ws%broken = .true.
    if (ws%broken) then
      call msg_set(msg, BROKEN_MESSAGE)
      return
    end if
    ! Runtime entry (the release itself needs no device operation).
    if (acc_get_num_devices(acc_device_nvidia) >= 1) then
      call save_device(saved)
      call select_device(ws%device_num, selected)
      call restore_device(saved)
    end if
    deallocate (ws, stat=ierr)
    if (ierr /= 0) then
      ! Not deallocated: ws keeps its association (F2008 6.7.4).
      ws%broken = .true.
      call msg_set(msg, 'OpenACC context workspace deallocation failed; the context is ' // &
                   'broken and kept until process teardown')
      return
    end if
    status = NCI_OK
  end subroutine acc_backend_destroy

  ! ------------------------------------------------------------------------
  ! Evaluation
  ! ------------------------------------------------------------------------

  !> Admission of an evaluation call before its other checks: a broken
  !> context is refused (6) and any earlier plan is discarded. The
  !> observation, the call ordinal and pending test controls are unchanged;
  !> only acc_backend_evaluate starts a new observation.
  recursive subroutine acc_backend_admit(handle, status, msg)
    type(c_ptr), intent(in) :: handle
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    type(acc_workspace), pointer :: ws

    status = NCI_INVALID_ARGUMENT
    call workspace_of(handle, ws)
    if (.not. associated(ws)) then
      call msg_set(msg, 'invalid OpenACC context workspace')
      return
    end if
    status = NCI_BACKEND_UNAVAILABLE
    if (.not. ws%broken .and. owns_any(ws)) ws%broken = .true.
    if (ws%broken) then
      call msg_set(msg, BROKEN_MESSAGE)
      return
    end if
    ws%plan = workspace_plan()
    status = NCI_OK
  end subroutine acc_backend_admit

  !> Checked plan of the nine host/device objects, before rho is touched.
  !> Bytes on each side: 8*Nin + 40*(B+Ny+Nz) + (37+72*D)*Nout. Overflow of
  !> any product or sum: status 1. An object above MAX_OBJECT_BYTES: 2.
  !> Only a passed plan is kept, for this call; no observation changes.
  recursive subroutine acc_backend_plan(handle, lay, diagnostic, status, msg)
    type(c_ptr), intent(in) :: handle
    type(tile_layout), intent(in) :: lay
    logical, intent(in) :: diagnostic
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    type(acc_workspace), pointer :: ws
    type(workspace_plan) :: plan
    integer(i64) :: total, next
    logical :: overflow
    integer :: obj

    status = NCI_INVALID_ARGUMENT
    call workspace_of(handle, ws)
    if (.not. associated(ws)) then
      call msg_set(msg, 'invalid OpenACC context workspace')
      return
    end if
    if (ws%broken) then
      status = NCI_BACKEND_UNAVAILABLE
      call msg_set(msg, BROKEN_MESSAGE)
      return
    end if
    plan%nin = lay%nin
    plan%nb = lay%nb
    plan%ny = lay%gn(2)
    plan%nz = lay%gn(3)
    plan%nout = lay%nout
    plan%nf = FULL_FIELDS
    if (diagnostic) plan%nf = DIAGNOSTIC_FIELDS

    overflow = .false.
    call checked_product(REAL_BYTES, plan%nin, plan%bytes(OBJ_RHO), overflow)
    call checked_product(TABLE_ENTRIES*INDEX_BYTES, plan%nb, plan%bytes(OBJ_TX), overflow)
    call checked_product(TABLE_ENTRIES*INDEX_BYTES, plan%ny, plan%bytes(OBJ_TY), overflow)
    call checked_product(TABLE_ENTRIES*INDEX_BYTES, plan%nz, plan%bytes(OBJ_TZ), overflow)
    call checked_product(plan%nf*REAL_BYTES, plan%nout, plan%bytes(OBJ_FIELDS), overflow)
    call checked_product(FLAG_BYTES, plan%nout, plan%bytes(OBJ_FLAGS), overflow)
    call checked_product(INT32_BYTES, plan%nout, plan%bytes(OBJ_STATUS), overflow)
    call checked_product(INT32_BYTES, plan%nout, plan%bytes(OBJ_NROT), overflow)
    call checked_product(INT32_BYTES, plan%nout, plan%bytes(OBJ_MARKER), overflow)
    total = 0
    do obj = 1, OBJECTS
      call checked_sum(total, plan%bytes(obj), next, overflow)
      total = next
    end do
    if (overflow) then
      call msg_set(msg, 'OpenACC workspace byte count overflows int64; nothing was allocated')
      return
    end if
    plan%total = total
    do obj = 1, OBJECTS
      if (plan%bytes(obj) > MAX_OBJECT_BYTES) then
        status = NCI_UNSUPPORTED
        call msg_set(msg, 'OpenACC object ')
        call msg_add_int(msg, int(obj, i64))
        call msg_add(msg, ' needs ')
        call msg_add_int(msg, plan%bytes(obj))
        call msg_add(msg, ' bytes; the installed runtime supports at most ')
        call msg_add_int(msg, MAX_OBJECT_BYTES)
        call msg_add(msg, ' bytes per mapped object')
        return
      end if
    end do
    plan%ready = .true.
    ws%plan = plan
    status = NCI_OK
  end subroutine acc_backend_plan

  !> One device evaluation of the planned layout (see the module header).
  !> On completion status is OK, INVALID_INPUT (no valid point) or
  !> NUMERIC_FAILURE, the caller arrays hold the device results, counts are
  !> derived from the downloaded flags and the first numeric failure is
  !> reported by its downloaded status, rotation count and global index
  !> (-1 when absent). On 1, 5 or 6 nothing has been written.
  recursive subroutine acc_backend_evaluate(handle, lay, periodic, m, rho, rho_min, has_negative, &
                                            diagnostic, rdg, srho, lam2, grad, hess, flags, &
                                            counts, first_global, first_status, first_nrot, &
                                            status, msg)
    type(c_ptr), intent(in) :: handle
    type(tile_layout), intent(in) :: lay
    logical, intent(in) :: periodic(3), has_negative, diagnostic
    real(dp), intent(in) :: m(3, 3), rho(:), rho_min
    real(dp), intent(inout) :: rdg(:), srho(:), lam2(:), grad(:, :), hess(:, :)
    integer(i8), intent(inout) :: flags(:)
    integer(i64), intent(out) :: counts(0:7), first_global
    integer, intent(out) :: first_status, first_nrot
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    type(acc_workspace), pointer :: ws
    type(device_state) :: saved
    integer(c_int) :: step_status
    integer(i64) :: verified, first_bad, first_fail
    real(dp) :: floor_abs
    integer :: fail_at, corruption, step
    logical :: ok

    call clear_result(counts, first_global, first_status, first_nrot)
    status = NCI_INVALID_ARGUMENT
    call workspace_of(handle, ws)
    if (.not. associated(ws)) then
      call msg_set(msg, 'invalid OpenACC context workspace')
      return
    end if
    if (ws%broken) then
      status = NCI_BACKEND_UNAVAILABLE
      call msg_set(msg, BROKEN_MESSAGE)
      return
    end if
    if (.not. ws%plan%ready .or. owns_any(ws)) then
      call msg_set(msg, 'OpenACC evaluation without a fresh checked plan')
      return
    end if
    ! Backend evaluation entry, after the common preflight and the checked
    ! plan: a new call ordinal, a reset observation with the planned values,
    ! and the pending test controls are consumed.
    ws%plan%ready = .false.
    ws%call_ordinal = ws%call_ordinal + 1
    call reset_observation(ws)
    ws%values(V_PLANNED_HOST) = ws%plan%total
    ws%values(V_PLANNED_DEVICE) = ws%plan%total
    ws%values(V_POINTS) = ws%plan%nout
    fail_at = ws%fail_at
    corruption = ws%corruption
    ws%fail_at = 0
    ws%corruption = 0

    status = NCI_BACKEND_UNAVAILABLE
    if (acc_get_num_devices(acc_device_nvidia) < 1) then
      call msg_set(msg, 'no NVIDIA OpenACC device is available; there is no CPU fallback')
      call finish(ws, status)
      return
    end if
    call save_device(saved)
    call select_device(ws%device_num, ok)
    if (.not. ok) then
      call restore_device(saved)
      call msg_set(msg, 'cannot select NVIDIA OpenACC device 0')
      call finish(ws, status)
      return
    end if

    ! Acquisitions 1..18: host arrays 1..9, then device allocation + mapping 1..9.
    step_status = NCI_OK
    do step = 1, ACC_ACQUISITIONS
      ws%values(V_ATTEMPTS) = step
      if (step <= OBJECTS) then
        call acquire_host(ws, step, step == fail_at, step_status)
      else
        call acquire_device(ws, step - OBJECTS, step == fail_at, step_status)
      end if
      if (step_status /= NCI_OK) exit
    end do
    if (step_status == NCI_ALLOCATION_FAILURE) then
      call release(ws, .false., ok)
      call restore_device(saved)
      if (ok) then
        status = NCI_ALLOCATION_FAILURE
        call msg_set(msg, 'cannot allocate OpenACC ')
        if (step <= OBJECTS) then
          call msg_add(msg, 'host object ')
          call msg_add_int(msg, int(step, i64))
        else
          call msg_add(msg, 'device object ')
          call msg_add_int(msg, int(step - OBJECTS, i64))
        end if
        call msg_add(msg, '; resources released and no output written')
      else
        call msg_set(msg, BROKEN_MESSAGE)
      end if
      call finish(ws, status)
      return
    else if (step_status /= NCI_OK) then
      ! A mapping the runtime does not report present: keep everything.
      call restore_device(saved)
      call msg_set(msg, BROKEN_MESSAGE)
      call finish(ws, status)
      return
    end if

    ! Inputs, poisoned outputs/metadata, one kernel, poisoned host copies,
    ! downloads. Every construct is synchronous (no async clause).
    call fill_inputs(ws, lay, periodic, rho)
    call upload_real1(ws%plan%nin, ws%host%rho)
    call record(ws, ACT_UPLOAD, OBJ_RHO)
    call upload_table(ws%plan%nb, ws%host%tx)
    call record(ws, ACT_UPLOAD, OBJ_TX)
    call upload_table(ws%plan%ny, ws%host%ty)
    call record(ws, ACT_UPLOAD, OBJ_TY)
    call upload_table(ws%plan%nz, ws%host%tz)
    call record(ws, ACT_UPLOAD, OBJ_TZ)
    call poison_staging(ws)
    call upload_fields(ws%plan%nf, ws%plan%nout, ws%host%fields)
    call record(ws, ACT_UPLOAD, OBJ_FIELDS)
    call upload_flags(ws%plan%nout, ws%host%flags)
    call record(ws, ACT_UPLOAD, OBJ_FLAGS)
    call upload_int32(ws%plan%nout, ws%host%pstat)
    call record(ws, ACT_UPLOAD, OBJ_STATUS)
    call upload_int32(ws%plan%nout, ws%host%nrot)
    call record(ws, ACT_UPLOAD, OBJ_NROT)
    call upload_int32(ws%plan%nout, ws%host%marker)
    call record(ws, ACT_UPLOAD, OBJ_MARKER)
    floor_abs = underflow_floor(abs(m))
    call launch_kernel(ws%plan%nin, ws%plan%nb, ws%plan%ny, ws%plan%nz, ws%plan%nf, &
                       ws%plan%nout, lay%gn(1), lay%x0, periodic(1), periodic(2), periodic(3), &
                       m(1, 1), m(2, 1), m(3, 1), m(1, 2), m(2, 2), m(3, 2), m(1, 3), m(2, 3), &
                       m(3, 3), floor_abs, rho_min, has_negative, diagnostic, ws%host%rho, &
                       ws%host%tx, ws%host%ty, ws%host%tz, ws%host%fields, ws%host%flags, &
                       ws%host%pstat, ws%host%nrot, ws%host%marker)
    call record(ws, ACT_KERNEL, 0)
    call poison_staging(ws)
    call download_fields(ws%plan%nf, ws%plan%nout, ws%host%fields)
    call record(ws, ACT_DOWNLOAD, OBJ_FIELDS)
    call download_flags(ws%plan%nout, ws%host%flags)
    call record(ws, ACT_DOWNLOAD, OBJ_FLAGS)
    call download_int32(ws%plan%nout, ws%host%pstat)
    call record(ws, ACT_DOWNLOAD, OBJ_STATUS)
    call download_int32(ws%plan%nout, ws%host%nrot)
    call record(ws, ACT_DOWNLOAD, OBJ_NROT)
    call download_int32(ws%plan%nout, ws%host%marker)
    call record(ws, ACT_DOWNLOAD, OBJ_MARKER)

    ! Test-only corruption of downloaded output point 1, never of the kernel.
    if (corruption == 1) then
      ws%host%marker(1) = 0
    else if (corruption == 2) then
      ws%host%pstat(1) = CORRUPT_STATUS
    end if

    call validate(ws, counts, verified, first_bad, first_fail)
    ws%values(V_MARKERS) = verified
    if (first_bad /= 0) then
      call describe_rejection(ws, lay, first_bad, msg)
      call release(ws, .false., ok)
      call restore_device(saved)
      if (.not. ok) call msg_set(msg, BROKEN_MESSAGE)
      call finish(ws, status)
      return
    end if
    if (first_fail /= 0) then
      first_global = global_index(lay, first_fail)
      first_status = int(ws%host%pstat(first_fail))
      first_nrot = int(ws%host%nrot(first_fail))
    end if

    ! Release every device allocation and the input/metadata host arrays,
    ! then commit through call-local staging (which restores the device).
    call release(ws, .true., ok)
    if (.not. ok) then
      call restore_device(saved)
      call clear_result(counts, first_global, first_status, first_nrot)
      call msg_set(msg, BROKEN_MESSAGE)
      call finish(ws, status)
      return
    end if
    call commit(ws, saved, diagnostic, rdg, srho, lam2, grad, hess, flags)
    ! commit has returned, so its automatic deallocation has released both
    ! call-local staging arrays: only now are they recorded as freed.
    call record(ws, ACT_CALL_FREE, OBJ_FIELDS)
    call record(ws, ACT_CALL_FREE, OBJ_FLAGS)

    if (counts(4) > 0) then
      status = NCI_NUMERIC_FAILURE
    else if (counts(7) == 0) then
      status = NCI_INVALID_INPUT
    else
      status = NCI_OK
    end if
    ws%values(V_FAIL_INDEX) = first_global
    ws%values(V_FAIL_STATUS) = first_status
    ws%values(V_FAIL_NROT) = first_nrot
    call finish(ws, status)
  end subroutine acc_backend_evaluate

  ! ------------------------------------------------------------------------
  ! Private observation interface (test-only; no device call, not exported)
  ! ------------------------------------------------------------------------

  !> failure_at 0 disables, 1..18 fails that acquisition of the next backend
  !> evaluation through its ordinary failure branch; corruption 0 disables,
  !> 1 sets the downloaded marker of output point 1 to 0 and 2 its downloaded
  !> status to INT32_MIN+1. A valid pair replaces the pending controls, which
  !> the next backend evaluation consumes at its entry (after the common
  !> preflight and the plan). rc: 0 accepted; 1 invalid handle, value out of
  !> range or both nonzero, with nothing changed; 6 broken context.
  recursive subroutine acc_test_configure(handle, failure_at, corruption, rc)
    type(c_ptr), intent(in) :: handle
    integer(c_int32_t), intent(in) :: failure_at, corruption
    integer(c_int32_t), intent(out) :: rc
    type(acc_workspace), pointer :: ws

    rc = NCI_INVALID_ARGUMENT
    call workspace_of(handle, ws)
    if (.not. associated(ws)) return
    if (ws%broken) then
      rc = NCI_BACKEND_UNAVAILABLE
      return
    end if
    if (failure_at < 0 .or. failure_at > ACC_ACQUISITIONS) return
    if (corruption < 0 .or. corruption > MAX_CORRUPTION) return
    if (failure_at /= 0 .and. corruption /= 0) return
    ws%fail_at = failure_at
    ws%corruption = corruption
    rc = NCI_OK
  end subroutine acc_test_configure

  !> Observation of the latest backend evaluation, or the initial one
  !> (values and events: see src/backend_openacc/README.md). rc: 0, or 1 for
  !> an invalid handle with every output zero. Broken contexts can still be
  !> observed.
  recursive subroutine acc_test_observe(handle, values, events, n_events, rc)
    type(c_ptr), intent(in) :: handle
    integer(c_int64_t), intent(out) :: values(ACC_OBSERVE_VALUES)
    integer(c_int64_t), intent(out) :: events(ACC_EVENT_COLUMNS, ACC_EVENT_CAPACITY)
    integer(c_int32_t), intent(out) :: n_events, rc
    type(acc_workspace), pointer :: ws
    integer :: k, n

    values = 0
    events = 0
    n_events = 0
    rc = NCI_INVALID_ARGUMENT
    call workspace_of(handle, ws)
    if (.not. associated(ws)) return
    values = ws%values
    values(V_BROKEN) = merge(1_c_int64_t, 0_c_int64_t, ws%broken)
    n = int(min(ws%event_total, int(ACC_EVENT_CAPACITY, i64)))
    do k = 1, n
      events(:, k) = ws%events(:, k)
    end do
    n_events = int(n, c_int32_t)
    rc = NCI_OK
  end subroutine acc_test_observe

  !> Fixed host storage outside the nine tracked objects, in bytes, from the
  !> compiled sizes: 1 one workspace (including 2 and 3), 2 its observation
  !> values and event ledger, 3 its nine owned-array descriptors, 4 the kernel
  !> launch scalars. The C API context wrapper (magic, options, handle) is
  !> separate. Driver/runtime pools, allocation rounding, compiler-local
  !> scratch and process RSS are not included. No device call.
  recursive subroutine acc_fixed_storage(bytes)
    integer(c_int64_t), intent(out) :: bytes(ACC_FIXED_STORAGE_ITEMS)
    type(acc_workspace), pointer :: ws
    type(owned_arrays), pointer :: arrays
    ws => null()
    arrays => null()
    bytes(1) = storage_size(ws, c_int64_t)/8
    bytes(2) = (ACC_OBSERVE_VALUES + ACC_EVENT_COLUMNS*ACC_EVENT_CAPACITY)*INDEX_BYTES
    bytes(3) = storage_size(arrays, c_int64_t)/8
    bytes(4) = LAUNCH_SCALAR_BYTES
  end subroutine acc_fixed_storage

  ! ------------------------------------------------------------------------
  ! Workspace, ownership and ledger
  ! ------------------------------------------------------------------------

  recursive subroutine workspace_of(handle, ws)
    type(c_ptr), intent(in) :: handle
    type(acc_workspace), pointer, intent(out) :: ws
    ws => null()
    if (.not. c_associated(handle)) return
    call c_f_pointer(handle, ws)
    if (ws%magic /= WS_MAGIC) ws => null()
  end subroutine workspace_of

  !> Observation of a new workspace and at each backend evaluation entry
  !> (never broken there): schema 1, the call ordinal, first failure index -1
  !> and every other value and event zero.
  recursive subroutine reset_observation(ws)
    type(acc_workspace), intent(inout) :: ws
    ws%values = 0
    ws%events = 0
    ws%event_total = 0
    ws%values(V_SCHEMA) = SCHEMA_VERSION
    ws%values(V_CALL) = ws%call_ordinal
    ws%values(V_FAIL_INDEX) = -1
  end subroutine reset_observation

  !> Final values of a backend evaluation.
  recursive subroutine finish(ws, status)
    type(acc_workspace), intent(inout) :: ws
    integer(c_int), intent(in) :: status
    ws%values(V_STATUS) = status
    ws%values(V_FINAL_HOST) = ws%live_host
    ws%values(V_FINAL_DEVICE) = ws%live_device
    ws%values(V_FINAL_MAPS) = ws%live_maps
    ws%values(V_BROKEN) = merge(1_i64, 0_i64, ws%broken)
    ws%values(V_EVENTS) = ws%event_total
  end subroutine finish

  !> Appends one event after applying its effect on the live totals, peaks
  !> and transfer counts. Events beyond the capacity are counted, not stored:
  !> event_count then exceeds the returned n_events.
  recursive subroutine record(ws, action, obj)
    type(acc_workspace), intent(inout) :: ws
    integer, intent(in) :: action, obj
    integer(i64) :: bytes
    bytes = 0
    if (obj >= 1 .and. obj <= OBJECTS) bytes = ws%plan%bytes(obj)
    select case (action)
    case (ACT_HOST_ACQUIRE)
      ws%live_host = ws%live_host + bytes
    case (ACT_DEVICE_ACQUIRE)
      ws%live_device = ws%live_device + bytes
    case (ACT_MAP)
      ws%live_maps = ws%live_maps + 1
    case (ACT_UPLOAD)
      ws%values(V_UPLOADS) = ws%values(V_UPLOADS) + 1
      ws%values(V_UPLOAD_BYTES) = ws%values(V_UPLOAD_BYTES) + bytes
    case (ACT_KERNEL)
      ws%values(V_KERNELS) = ws%values(V_KERNELS) + 1
    case (ACT_DOWNLOAD)
      ws%values(V_DOWNLOADS) = ws%values(V_DOWNLOADS) + 1
      ws%values(V_DOWNLOAD_BYTES) = ws%values(V_DOWNLOAD_BYTES) + bytes
    case (ACT_UNMAP)
      ws%live_maps = ws%live_maps - 1
    case (ACT_DEVICE_FREE)
      ws%live_device = ws%live_device - bytes
    case (ACT_HOST_FREE, ACT_CALL_FREE)
      ws%live_host = ws%live_host - bytes
    end select
    ws%values(V_PEAK_HOST) = max(ws%values(V_PEAK_HOST), ws%live_host)
    ws%values(V_PEAK_DEVICE) = max(ws%values(V_PEAK_DEVICE), ws%live_device)
    ws%values(V_PEAK_MAPS) = max(ws%values(V_PEAK_MAPS), ws%live_maps)
    ws%event_total = ws%event_total + 1
    ws%values(V_EVENTS) = ws%event_total
    if (ws%event_total <= ACC_EVENT_CAPACITY) then
      ws%events(1, ws%event_total) = ws%event_total
      ws%events(2, ws%event_total) = action
      ws%events(3, ws%event_total) = obj
      ws%events(4, ws%event_total) = bytes
      ws%events(5, ws%event_total) = ws%live_host
      ws%events(6, ws%event_total) = ws%live_device
    end if
  end subroutine record

  !> Host array obj; an injected failure takes the failed-ALLOCATE branch.
  recursive subroutine acquire_host(ws, obj, inject, status)
    type(acc_workspace), intent(inout) :: ws
    integer, intent(in) :: obj
    logical, intent(in) :: inject
    integer(c_int), intent(out) :: status
    integer :: ierr
    ierr = 1
    if (.not. inject) then
      select case (obj)
      case (OBJ_RHO)
        allocate (ws%host%rho(ws%plan%nin), stat=ierr)
      case (OBJ_TX)
        allocate (ws%host%tx(-2:2, 0:ws%plan%nb - 1), stat=ierr)
      case (OBJ_TY)
        allocate (ws%host%ty(-2:2, 0:ws%plan%ny - 1), stat=ierr)
      case (OBJ_TZ)
        allocate (ws%host%tz(-2:2, 0:ws%plan%nz - 1), stat=ierr)
      case (OBJ_FIELDS)
        allocate (ws%host%fields(ws%plan%nf, ws%plan%nout), stat=ierr)
      case (OBJ_FLAGS)
        allocate (ws%host%flags(ws%plan%nout), stat=ierr)
      case (OBJ_STATUS)
        allocate (ws%host%pstat(ws%plan%nout), stat=ierr)
      case (OBJ_NROT)
        allocate (ws%host%nrot(ws%plan%nout), stat=ierr)
      case (OBJ_MARKER)
        allocate (ws%host%marker(ws%plan%nout), stat=ierr)
      end select
    end if
    if (ierr /= 0) then
      status = NCI_ALLOCATION_FAILURE
      return
    end if
    call record(ws, ACT_HOST_ACQUIRE, obj)
    status = NCI_OK
  end subroutine acquire_host

  !> Device allocation of obj (an injected failure keeps the null pointer of
  !> a failed acc_malloc), its mapping onto the host array and the presence
  !> query. A mapping not reported present breaks the workspace.
  recursive subroutine acquire_device(ws, obj, inject, status)
    type(acc_workspace), intent(inout) :: ws
    integer, intent(in) :: obj
    logical, intent(in) :: inject
    integer(c_int), intent(out) :: status
    integer(c_size_t) :: bytes
    bytes = int(ws%plan%bytes(obj), c_size_t)
    if (inject) then
      ws%device(obj) = c_null_devptr
    else
      ws%device(obj) = acc_malloc(bytes)
    end if
    if (ws%device(obj) == c_null_devptr) then
      status = NCI_ALLOCATION_FAILURE
      return
    end if
    call record(ws, ACT_DEVICE_ACQUIRE, obj)
    select case (obj)
    case (OBJ_RHO)
      call acc_map_data(ws%host%rho, ws%device(obj), bytes)
    case (OBJ_TX)
      call acc_map_data(ws%host%tx, ws%device(obj), bytes)
    case (OBJ_TY)
      call acc_map_data(ws%host%ty, ws%device(obj), bytes)
    case (OBJ_TZ)
      call acc_map_data(ws%host%tz, ws%device(obj), bytes)
    case (OBJ_FIELDS)
      call acc_map_data(ws%host%fields, ws%device(obj), bytes)
    case (OBJ_FLAGS)
      call acc_map_data(ws%host%flags, ws%device(obj), bytes)
    case (OBJ_STATUS)
      call acc_map_data(ws%host%pstat, ws%device(obj), bytes)
    case (OBJ_NROT)
      call acc_map_data(ws%host%nrot, ws%device(obj), bytes)
    case (OBJ_MARKER)
      call acc_map_data(ws%host%marker, ws%device(obj), bytes)
    end select
    ws%mapped(obj) = .true.
    call record(ws, ACT_MAP, obj)
    if (.not. host_present(ws, obj)) then
      ws%broken = .true.
      status = NCI_BACKEND_UNAVAILABLE
      return
    end if
    status = NCI_OK
  end subroutine acquire_device

  !> The single release path. For ids 9..1: unmap a live mapping and query
  !> its absence while the host array is still allocated, then free the
  !> device allocation. Then free the host arrays 9..1, keeping fields and
  !> flags when keep_outputs. A mapping or host array counts as released
  !> only once its release is confirmed. A contradicted absence query or a
  !> failed host deallocation stops at once and breaks the workspace, which
  !> keeps that object (still mapped/allocated) and everything not yet
  !> released.
  recursive subroutine release(ws, keep_outputs, ok)
    type(acc_workspace), intent(inout) :: ws
    logical, intent(in) :: keep_outputs
    logical, intent(out) :: ok
    integer :: obj, ierr
    ok = .false.
    do obj = OBJECTS, 1, -1
      if (ws%mapped(obj)) then
        select case (obj)
        case (OBJ_RHO)
          call acc_unmap_data(ws%host%rho)
        case (OBJ_TX)
          call acc_unmap_data(ws%host%tx)
        case (OBJ_TY)
          call acc_unmap_data(ws%host%ty)
        case (OBJ_TZ)
          call acc_unmap_data(ws%host%tz)
        case (OBJ_FIELDS)
          call acc_unmap_data(ws%host%fields)
        case (OBJ_FLAGS)
          call acc_unmap_data(ws%host%flags)
        case (OBJ_STATUS)
          call acc_unmap_data(ws%host%pstat)
        case (OBJ_NROT)
          call acc_unmap_data(ws%host%nrot)
        case (OBJ_MARKER)
          call acc_unmap_data(ws%host%marker)
        end select
        if (host_present(ws, obj)) then
          ws%broken = .true.
          return
        end if
        ws%mapped(obj) = .false.
        call record(ws, ACT_UNMAP, obj)
      end if
      if (.not. (ws%device(obj) == c_null_devptr)) then
        call acc_free(ws%device(obj))
        ws%device(obj) = c_null_devptr
        call record(ws, ACT_DEVICE_FREE, obj)
      end if
    end do
    do obj = OBJECTS, 1, -1
      if (keep_outputs .and. (obj == OBJ_FIELDS .or. obj == OBJ_FLAGS)) cycle
      if (.not. host_allocated(ws, obj)) cycle
      ierr = 1
      select case (obj)
      case (OBJ_RHO)
        deallocate (ws%host%rho, stat=ierr)
      case (OBJ_TX)
        deallocate (ws%host%tx, stat=ierr)
      case (OBJ_TY)
        deallocate (ws%host%ty, stat=ierr)
      case (OBJ_TZ)
        deallocate (ws%host%tz, stat=ierr)
      case (OBJ_FIELDS)
        deallocate (ws%host%fields, stat=ierr)
      case (OBJ_FLAGS)
        deallocate (ws%host%flags, stat=ierr)
      case (OBJ_STATUS)
        deallocate (ws%host%pstat, stat=ierr)
      case (OBJ_NROT)
        deallocate (ws%host%nrot, stat=ierr)
      case (OBJ_MARKER)
        deallocate (ws%host%marker, stat=ierr)
      end select
      if (ierr /= 0) then
        ws%broken = .true.
        return
      end if
      call record(ws, ACT_HOST_FREE, obj)
    end do
    ok = .true.
  end subroutine release

  !> Moves the validated fields and flags to call-local staging (ownership
  !> moves; it is not a free), restores the caller's device selection and
  !> writes the caller arrays with explicit loops. The staging arrays are
  !> unsaved local allocatables: Fortran deallocates them when this routine
  !> returns, with no returning failure (a failure there is a fatal runtime
  !> error at the worker boundary). A normal return therefore proves both
  !> were released; the caller records their frees after it.
  recursive subroutine commit(ws, saved, diagnostic, rdg, srho, lam2, grad, hess, flags)
    type(acc_workspace), intent(inout) :: ws
    type(device_state), intent(in) :: saved
    logical, intent(in) :: diagnostic
    real(dp), intent(inout) :: rdg(:), srho(:), lam2(:), grad(:, :), hess(:, :)
    integer(i8), intent(inout) :: flags(:)
    real(dp), allocatable :: staged_fields(:, :)
    integer(i8), allocatable :: staged_flags(:)
    integer(i64) :: p, nout
    integer :: k

    nout = ws%plan%nout
    call move_alloc(ws%host%fields, staged_fields)
    call record(ws, ACT_MOVE_TO_CALL, OBJ_FIELDS)
    call move_alloc(ws%host%flags, staged_flags)
    call record(ws, ACT_MOVE_TO_CALL, OBJ_FLAGS)
    call restore_device(saved)
    do p = 1, nout
      rdg(p) = staged_fields(1, p)
      srho(p) = staged_fields(2, p)
      lam2(p) = staged_fields(3, p)
      flags(p) = staged_flags(p)
    end do
    if (diagnostic) then
      do p = 1, nout
        do k = 1, 3
          grad(k, p) = staged_fields(3 + k, p)
        end do
        do k = 1, 6
          hess(k, p) = staged_fields(6 + k, p)
        end do
      end do
    end if
  end subroutine commit

  recursive function host_present(ws, obj) result(found)
    type(acc_workspace), intent(in) :: ws
    integer, intent(in) :: obj
    logical :: found
    integer(c_size_t) :: bytes
    bytes = int(ws%plan%bytes(obj), c_size_t)
    select case (obj)
    case (OBJ_RHO)
      found = acc_is_present(ws%host%rho, bytes)
    case (OBJ_TX)
      found = acc_is_present(ws%host%tx, bytes)
    case (OBJ_TY)
      found = acc_is_present(ws%host%ty, bytes)
    case (OBJ_TZ)
      found = acc_is_present(ws%host%tz, bytes)
    case (OBJ_FIELDS)
      found = acc_is_present(ws%host%fields, bytes)
    case (OBJ_FLAGS)
      found = acc_is_present(ws%host%flags, bytes)
    case (OBJ_STATUS)
      found = acc_is_present(ws%host%pstat, bytes)
    case (OBJ_NROT)
      found = acc_is_present(ws%host%nrot, bytes)
    case (OBJ_MARKER)
      found = acc_is_present(ws%host%marker, bytes)
    case default
      found = .false.
    end select
  end function host_present

  recursive pure function host_allocated(ws, obj) result(owned)
    type(acc_workspace), intent(in) :: ws
    integer, intent(in) :: obj
    logical :: owned
    select case (obj)
    case (OBJ_RHO)
      owned = allocated(ws%host%rho)
    case (OBJ_TX)
      owned = allocated(ws%host%tx)
    case (OBJ_TY)
      owned = allocated(ws%host%ty)
    case (OBJ_TZ)
      owned = allocated(ws%host%tz)
    case (OBJ_FIELDS)
      owned = allocated(ws%host%fields)
    case (OBJ_FLAGS)
      owned = allocated(ws%host%flags)
    case (OBJ_STATUS)
      owned = allocated(ws%host%pstat)
    case (OBJ_NROT)
      owned = allocated(ws%host%nrot)
    case (OBJ_MARKER)
      owned = allocated(ws%host%marker)
    case default
      owned = .false.
    end select
  end function host_allocated

  recursive function owns_any(ws) result(owns)
    type(acc_workspace), intent(in) :: ws
    logical :: owns
    integer :: obj
    owns = any(ws%mapped) .or. ws%live_host /= 0 .or. ws%live_device /= 0 .or. ws%live_maps /= 0
    do obj = 1, OBJECTS
      owns = owns .or. host_allocated(ws, obj) .or. .not. (ws%device(obj) == c_null_devptr)
    end do
  end function owns_any

  ! ------------------------------------------------------------------------
  ! Device selection of the calling thread
  ! ------------------------------------------------------------------------

  !> A NONE, DEFAULT or NOT_HOST type is not a concrete selection and has no
  !> valid restoration operation.
  recursive subroutine save_device(saved)
    type(device_state), intent(out) :: saved
    saved%device_type = acc_get_device_type()
    saved%concrete = saved%device_type /= acc_device_none .and. &
                     saved%device_type /= acc_device_default .and. &
                     saved%device_type /= acc_device_not_host
    saved%device_num = 0
    if (saved%concrete) saved%device_num = acc_get_device_num(saved%device_type)
  end subroutine save_device

  recursive subroutine select_device(device_num, ok)
    integer, intent(in) :: device_num
    logical, intent(out) :: ok
    call acc_set_device_type(acc_device_nvidia)
    call acc_set_device_num(device_num, acc_device_nvidia)
    ok = acc_get_device_type() == acc_device_nvidia
    if (ok) ok = acc_get_device_num(acc_device_nvidia) == device_num
  end subroutine select_device

  recursive subroutine restore_device(saved)
    type(device_state), intent(in) :: saved
    if (.not. saved%concrete) return
    call acc_set_device_type(saved%device_type)
    call acc_set_device_num(saved%device_num, saved%device_type)
  end subroutine restore_device

  ! ------------------------------------------------------------------------
  ! Host preparation and checks
  ! ------------------------------------------------------------------------

  !> Private copy of the supplied density and the production neighbour
  !> tables (the same axis_table calls as the CPU evaluate_grid).
  recursive subroutine fill_inputs(ws, lay, periodic, rho)
    type(acc_workspace), intent(inout) :: ws
    type(tile_layout), intent(in) :: lay
    logical, intent(in) :: periodic(3)
    real(dp), intent(in) :: rho(:)
    integer(i64) :: i
    do i = 1, ws%plan%nin
      ws%host%rho(i) = rho(i)
    end do
    call axis_table(lay%gn(1), lay%x0, lay%nb, lay%xlo, periodic(1), lay%wrap, &
                    lay%gn(2)*lay%gn(3), ws%host%tx)
    call axis_table(lay%gn(2), 0_i64, lay%gn(2), 0_i64, periodic(2), .true., lay%gn(3), ws%host%ty)
    call axis_table(lay%gn(3), 0_i64, lay%gn(3), 0_i64, periodic(3), .true., 1_i64, ws%host%tz)
  end subroutine fill_inputs

  recursive subroutine poison_staging(ws)
    type(acc_workspace), intent(inout) :: ws
    ws%host%fields = transfer(FIELD_POISON_BITS, 0.0_dp)
    ws%host%flags = FLAG_POISON
    ws%host%pstat = INT_POISON
    ws%host%nrot = INT_POISON
    ws%host%marker = MARKER_POISON
  end subroutine poison_staging

  recursive pure subroutine clear_result(counts, first_global, first_status, first_nrot)
    integer(i64), intent(out) :: counts(0:7), first_global
    integer, intent(out) :: first_status, first_nrot
    counts = 0
    first_global = -1
    first_status = 0
    first_nrot = 0
  end subroutine clear_result

  !> Validates every downloaded value. A point is consistent when its marker
  !> is 1 and either status -1 (classified invalid): flags in 1..15, nrot 0,
  !> every requested field the canonical NaN; or status 0: flags 64 or 96,
  !> nrot 0..30, every field finite; or status 1..6: flags 16, nrot 0..30,
  !> every field the canonical NaN. counts are taken from the flags of a
  !> fully consistent result; first_bad (0 if none) is the first
  !> inconsistent point and first_fail the first numeric failure.
  recursive subroutine validate(ws, counts, verified, first_bad, first_fail)
    type(acc_workspace), intent(in) :: ws
    integer(i64), intent(out) :: counts(0:7), verified, first_bad, first_fail
    integer(i64) :: p, k
    integer :: fl, s, r
    logical :: good, nan_fields, finite_fields
    counts = 0
    verified = 0
    first_bad = 0
    first_fail = 0
    do p = 1, ws%plan%nout
      good = ws%host%marker(p) == MARKER_ON_DEVICE
      if (good) verified = verified + 1
      fl = int(ws%host%flags(p))
      s = int(ws%host%pstat(p))
      r = int(ws%host%nrot(p))
      nan_fields = .true.
      finite_fields = .true.
      do k = 1, ws%plan%nf
        nan_fields = nan_fields .and. transfer(ws%host%fields(k, p), 0_i64) == QNAN_BITS
        finite_fields = finite_fields .and. is_finite(ws%host%fields(k, p))
      end do
      if (s == STATUS_CLASSIFIED_INVALID) then
        good = good .and. fl >= 1 .and. fl <= CLASSIFIED_FLAGS_MAX .and. r == 0 .and. nan_fields
      else if (s == PT_OK) then
        good = good .and. (fl == FLAG_LAMBDA_SCI_UNCERTAIN .or. &
                           fl == ior(FLAG_LAMBDA_SCI_UNCERTAIN, FLAG_LAMBDA_NUM_UNCERTAIN)) &
               .and. r >= 0 .and. r <= JACOBI_MAX_ROTATIONS .and. finite_fields
      else if (s >= PT_NONFINITE_DERIVATIVE .and. s <= PT_NONFINITE_RESULT) then
        good = good .and. fl == FLAG_POINT_NUMERIC_FAILURE .and. r >= 0 &
               .and. r <= JACOBI_MAX_ROTATIONS .and. nan_fields
      else
        good = .false.
      end if
      if (.not. good) then
        if (first_bad == 0) first_bad = p
        cycle
      end if
      do k = 0, 6
        if (btest(fl, k)) counts(k) = counts(k) + 1
      end do
      if (iand(fl, FLAG_NOT_VALID_MASK) == 0) counts(7) = counts(7) + 1
      if (first_fail == 0 .and. btest(fl, 4)) first_fail = p
    end do
    if (first_bad /= 0) counts = 0
  end subroutine validate

  recursive subroutine describe_rejection(ws, lay, p, msg)
    type(acc_workspace), intent(in) :: ws
    type(tile_layout), intent(in) :: lay
    integer(i64), intent(in) :: p
    type(message_t), intent(inout) :: msg
    call msg_set(msg, 'OpenACC device result rejected at point ')
    call msg_add_int(msg, global_index(lay, p))
    call msg_add(msg, ': marker ')
    call msg_add_int(msg, int(ws%host%marker(p), i64))
    call msg_add(msg, ', status ')
    call msg_add_int(msg, int(ws%host%pstat(p), i64))
    call msg_add(msg, ', nrot ')
    call msg_add_int(msg, int(ws%host%nrot(p), i64))
    call msg_add(msg, ', flags ')
    call msg_add_int(msg, int(ws%host%flags(p), i64))
    call msg_add(msg, '; no output written')
  end subroutine describe_rejection

  !> Zero-based global Z-fastest index of local output point p (1-based).
  recursive pure function global_index(lay, p) result(g)
    type(tile_layout), intent(in) :: lay
    integer(i64), intent(in) :: p
    integer(i64) :: g, q, ny, nz
    ny = lay%gn(2)
    nz = lay%gn(3)
    q = p - 1
    g = ((lay%x0 + q/(ny*nz))*ny + mod(q/nz, ny))*nz + mod(q, nz)
  end function global_index

  recursive pure subroutine checked_product(a, b, r, overflow)
    integer(i64), intent(in) :: a, b
    integer(i64), intent(out) :: r
    logical, intent(inout) :: overflow
    r = 0
    if (a < 0 .or. b < 0 .or. mul_overflows(a, b)) then
      overflow = .true.
    else
      r = a*b
    end if
  end subroutine checked_product

  recursive pure subroutine checked_sum(a, b, r, overflow)
    integer(i64), intent(in) :: a, b
    integer(i64), intent(out) :: r
    logical, intent(inout) :: overflow
    r = 0
    if (a < 0 .or. b < 0 .or. a > huge(a) - b) then
      overflow = .true.
    else
      r = a + b
    end if
  end subroutine checked_sum

  ! ------------------------------------------------------------------------
  ! Transfers of whole mapped arrays. Explicit-shape dummies carry no
  ! descriptor, so each directive moves exactly that array; no async clause.
  ! ------------------------------------------------------------------------

  recursive subroutine upload_real1(n, x)
    integer(i64), intent(in) :: n
    real(dp), intent(in) :: x(n)
    !$acc update device(x)
  end subroutine upload_real1

  recursive subroutine upload_table(n, x)
    integer(i64), intent(in) :: n
    integer(i64), intent(in) :: x(-2:2, 0:n - 1)
    !$acc update device(x)
  end subroutine upload_table

  recursive subroutine upload_fields(nf, n, x)
    integer(i64), intent(in) :: nf, n
    real(dp), intent(in) :: x(nf, n)
    !$acc update device(x)
  end subroutine upload_fields

  recursive subroutine upload_flags(n, x)
    integer(i64), intent(in) :: n
    integer(i8), intent(in) :: x(n)
    !$acc update device(x)
  end subroutine upload_flags

  recursive subroutine upload_int32(n, x)
    integer(i64), intent(in) :: n
    integer(i32), intent(in) :: x(n)
    !$acc update device(x)
  end subroutine upload_int32

  recursive subroutine download_fields(nf, n, x)
    integer(i64), intent(in) :: nf, n
    real(dp), intent(inout) :: x(nf, n)
    !$acc update self(x)
  end subroutine download_fields

  recursive subroutine download_flags(n, x)
    integer(i64), intent(in) :: n
    integer(i8), intent(inout) :: x(n)
    !$acc update self(x)
  end subroutine download_flags

  recursive subroutine download_int32(n, x)
    integer(i64), intent(in) :: n
    integer(i32), intent(inout) :: x(n)
    !$acc update self(x)
  end subroutine download_int32

  ! ------------------------------------------------------------------------
  ! Kernel
  ! ------------------------------------------------------------------------

  !> One synchronous compute region over every output point on the mapped
  !> arrays (present: no implicit data movement; scalars are launch values).
  !> Each iteration writes its marker from acc_on_device in this region and
  !> evaluates the point with the production classifier and point_eval.
  recursive subroutine launch_kernel(nin, nb, ny, nz, nf, nout, nx, x0, px, py, pz, m1, m2, m3, &
                                     m4, m5, m6, m7, m8, m9, floor_abs, rho_min, has_negative, &
                                     diagnostic, rho, tx, ty, tz, fields, flags, pstat, nrot, marker)
    integer(i64), intent(in) :: nin, nb, ny, nz, nf, nout, nx, x0
    logical, intent(in) :: px, py, pz, has_negative, diagnostic
    real(dp), intent(in) :: m1, m2, m3, m4, m5, m6, m7, m8, m9, floor_abs, rho_min
    real(dp), intent(in) :: rho(nin)
    integer(i64), intent(in) :: tx(-2:2, 0:nb - 1), ty(-2:2, 0:ny - 1), tz(-2:2, 0:nz - 1)
    real(dp), intent(inout) :: fields(nf, nout)
    integer(i8), intent(inout) :: flags(nout)
    integer(i32), intent(inout) :: pstat(nout), nrot(nout), marker(nout)
    integer(i64) :: ix, iy, iz, p

    !$acc parallel loop collapse(3) default(none) private(p) &
    !$acc   present(rho, tx, ty, tz, fields, flags, pstat, nrot, marker) &
    !$acc   firstprivate(nin, nb, ny, nz, nf, nout, nx, x0, px, py, pz, m1, m2, m3, m4, m5, m6, &
    !$acc                m7, m8, m9, floor_abs, rho_min, has_negative, diagnostic)
    do ix = 0, nb - 1
      do iy = 0, ny - 1
        do iz = 0, nz - 1
          p = (ix*ny + iy)*nz + iz + 1
          marker(p) = merge(MARKER_ON_DEVICE, 0_i32, acc_on_device(acc_device_nvidia))
          call evaluate_point(p, ix, iy, iz, nin, nb, ny, nz, nf, nout, nx, x0, px, py, pz, &
                              m1, m2, m3, m4, m5, m6, m7, m8, m9, floor_abs, rho_min, &
                              has_negative, diagnostic, rho, tx, ty, tz, fields, flags, pstat, nrot)
        end do
      end do
    end do
  end subroutine launch_kernel

  !> Device evaluation of output point p = (ix*Ny + iy)*Nz + iz + 1 at global
  !> (x0+ix, iy, iz), with the per-point logic of the CPU evaluate_grid:
  !> classified-invalid points get status -1, nrot 0 and NaN fields;
  !> evaluated points get the point_eval status, rotation count and either
  !> the result fields or NaN.
  subroutine evaluate_point(p, ix, iy, iz, nin, nb, ny, nz, nf, nout, nx, x0, px, py, pz, &
                            m1, m2, m3, m4, m5, m6, m7, m8, m9, floor_abs, rho_min, has_negative, &
                            diagnostic, rho, tx, ty, tz, fields, flags, pstat, nrot)
    !$acc routine seq
    integer(i64), intent(in) :: p, ix, iy, iz, nin, nb, ny, nz, nf, nout, nx, x0
    logical, intent(in) :: px, py, pz, has_negative, diagnostic
    real(dp), intent(in) :: m1, m2, m3, m4, m5, m6, m7, m8, m9, floor_abs, rho_min
    real(dp), intent(in) :: rho(nin)
    integer(i64), intent(in) :: tx(-2:2, 0:nb - 1), ty(-2:2, 0:ny - 1), tz(-2:2, 0:nz - 1)
    real(dp), intent(inout) :: fields(nf, nout)
    integer(i8), intent(inout) :: flags(nout)
    integer(i32), intent(inout) :: pstat(nout), nrot(nout)
    real(dp) :: m(3, 3), absm(3, 3), blk(-2:2, -2:2, -2:2), nan
    logical :: periodic(3)
    integer :: off(3, 61), fl
    integer(i64) :: k
    type(point_result) :: res

    m(1, 1) = m1
    m(2, 1) = m2
    m(3, 1) = m3
    m(1, 2) = m4
    m(2, 2) = m5
    m(3, 2) = m6
    m(1, 3) = m7
    m(2, 3) = m8
    m(3, 3) = m9
    absm = abs(m)
    periodic(1) = px
    periodic(2) = py
    periodic(3) = pz
    off = stencil61()
    blk = 0.0_dp
    nan = qnan()
    call classify_point(x0 + ix, iy, iz, nx, ny, nz, periodic, tx(:, ix), ty(:, iy), tz(:, iz), &
                        off, rho, rho_min, has_negative, fl, blk)
    if (fl == 0) then
      call point_eval(blk, m, absm, floor_abs, JACOBI_MAX_ROTATIONS, res)
      pstat(p) = int(res%status, i32)
      nrot(p) = int(res%nrot, i32)
      if (res%status == PT_OK) then
        fl = FLAG_LAMBDA_SCI_UNCERTAIN
        if (res%uncertain) fl = ior(fl, FLAG_LAMBDA_NUM_UNCERTAIN)
        fields(1, p) = res%rdg
        fields(2, p) = res%signed_rho
        fields(3, p) = res%lambda(2)
        if (diagnostic) then
          do k = 1, 3
            fields(3 + k, p) = res%grad(k)
          end do
          do k = 1, 6
            fields(6 + k, p) = res%hess(k)
          end do
        end if
      else
        fl = FLAG_POINT_NUMERIC_FAILURE
        do k = 1, nf
          fields(k, p) = nan
        end do
      end if
    else
      pstat(p) = STATUS_CLASSIFIED_INVALID
      nrot(p) = 0
      do k = 1, nf
        fields(k, p) = nan
      end do
    end if
    ! Kind conversion by assignment (fl is 0..127): NVHPC implements INT with
    ! an 8-bit kind by a host runtime routine that device code cannot call.
    flags(p) = fl
  end subroutine evaluate_point

end module nci_acc_backend
