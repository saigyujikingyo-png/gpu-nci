! SPDX-License-Identifier: MIT
! Test-only wrappers. Link the exact nci_openacc_objects, never the public SO.
! These symbols are NOT sources of nci_openacc and NOT public ABI additions.
module nci_test_bridge
  use, intrinsic :: iso_c_binding
  use nci_capi, only: test_backend_handle
  use nci_acc_backend, only: acc_test_configure, acc_test_observe
  implicit none
contains
  subroutine configure(context, failure_at, corruption, rc) bind(C, name='nci_test_configure_v1')
    type(c_ptr), value :: context
    integer(c_int32_t), value :: failure_at, corruption
    integer(c_int32_t), intent(out) :: rc
    type(c_ptr) :: handle
    handle = test_backend_handle(context)
    call acc_test_configure(handle, failure_at, corruption, rc)
  end subroutine configure

  subroutine observe(context, values, events, n_events, rc) bind(C, name='nci_test_observe_v1')
    type(c_ptr), value :: context
    integer(c_int64_t), intent(out) :: values(24), events(6,256)
    integer(c_int32_t), intent(out) :: n_events, rc
    type(c_ptr) :: handle
    handle = test_backend_handle(context)
    call acc_test_observe(handle, values, events, n_events, rc)
  end subroutine observe
end module nci_test_bridge
