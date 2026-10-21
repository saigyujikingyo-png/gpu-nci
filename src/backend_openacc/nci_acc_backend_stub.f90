! SPDX-License-Identifier: MIT
!> Build-selected stub of nci_acc_backend (docs/openacc-public-contract.md),
!> compiled into nci_cpu instead of nci_acc_backend.f90. The common C API is
!> the same source in both libraries; here ACC_BACKEND_COMPILED is false, so
!> option validation rejects NCI_OPENACC exactly as before and no entry below
!> is reached through the C ABI. Every entry reports BACKEND_UNAVAILABLE (6)
!> with null or zero outputs and ignores its inputs. Nothing here references
!> the OpenACC runtime.
module nci_acc_backend
  use, intrinsic :: iso_c_binding, only: c_ptr, c_null_ptr, c_int, c_int32_t, c_int64_t
  use nci_kinds, only: dp, i8, i64
  use nci_abi, only: NCI_BACKEND_UNAVAILABLE
  use nci_validate, only: message_t, msg_set, tile_layout
  implicit none
  private

  logical, parameter, public :: ACC_BACKEND_COMPILED = .false.
  integer, parameter, public :: ACC_OBSERVE_VALUES = 24
  integer, parameter, public :: ACC_EVENT_COLUMNS = 6
  integer, parameter, public :: ACC_EVENT_CAPACITY = 256
  integer, parameter, public :: ACC_ACQUISITIONS = 18
  integer, parameter, public :: ACC_FIXED_STORAGE_ITEMS = 4

  public :: acc_backend_create, acc_backend_destroy, acc_backend_begin, acc_backend_plan
  public :: acc_backend_evaluate, acc_test_configure, acc_test_observe, acc_fixed_storage

  character(len=*), parameter :: UNAVAILABLE = 'the OpenACC backend is not available in this library'

contains

  recursive subroutine acc_backend_create(handle, status, msg)
    type(c_ptr), intent(out) :: handle
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    handle = c_null_ptr
    status = NCI_BACKEND_UNAVAILABLE
    call msg_set(msg, UNAVAILABLE)
  end subroutine acc_backend_create

  recursive subroutine acc_backend_destroy(handle, status, msg)
    type(c_ptr), intent(in) :: handle
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    status = NCI_BACKEND_UNAVAILABLE
    call msg_set(msg, UNAVAILABLE)
  end subroutine acc_backend_destroy

  recursive subroutine acc_backend_begin(handle, status, msg)
    type(c_ptr), intent(in) :: handle
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    status = NCI_BACKEND_UNAVAILABLE
    call msg_set(msg, UNAVAILABLE)
  end subroutine acc_backend_begin

  recursive subroutine acc_backend_plan(handle, lay, diagnostic, status, msg)
    type(c_ptr), intent(in) :: handle
    type(tile_layout), intent(in) :: lay
    logical, intent(in) :: diagnostic
    integer(c_int), intent(out) :: status
    type(message_t), intent(inout) :: msg
    status = NCI_BACKEND_UNAVAILABLE
    call msg_set(msg, UNAVAILABLE)
  end subroutine acc_backend_plan

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
    counts = 0
    first_global = -1
    first_status = 0
    first_nrot = 0
    status = NCI_BACKEND_UNAVAILABLE
    call msg_set(msg, UNAVAILABLE)
  end subroutine acc_backend_evaluate

  recursive subroutine acc_test_configure(handle, failure_at, corruption, rc)
    type(c_ptr), intent(in) :: handle
    integer(c_int32_t), intent(in) :: failure_at, corruption
    integer(c_int32_t), intent(out) :: rc
    rc = NCI_BACKEND_UNAVAILABLE
  end subroutine acc_test_configure

  recursive subroutine acc_test_observe(handle, values, events, n_events, rc)
    type(c_ptr), intent(in) :: handle
    integer(c_int64_t), intent(out) :: values(ACC_OBSERVE_VALUES)
    integer(c_int64_t), intent(out) :: events(ACC_EVENT_COLUMNS, ACC_EVENT_CAPACITY)
    integer(c_int32_t), intent(out) :: n_events, rc
    values = 0
    events = 0
    n_events = 0
    rc = NCI_BACKEND_UNAVAILABLE
  end subroutine acc_test_observe

  !> No OpenACC context storage exists in this library.
  recursive subroutine acc_fixed_storage(bytes)
    integer(c_int64_t), intent(out) :: bytes(ACC_FIXED_STORAGE_ITEMS)
    bytes = 0
  end subroutine acc_fixed_storage

end module nci_acc_backend
