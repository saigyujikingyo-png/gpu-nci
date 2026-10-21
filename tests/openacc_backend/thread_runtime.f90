! Test-only standard runtime observer linked with the actual public shared SO.
! No production objects, hooks, alternate evaluator or hardcoded C enum values.
subroutine runtime_host() bind(C,name='nci_test_runtime_host')
  use openacc
  implicit none
  call acc_set_device_type(acc_device_host)
end subroutine runtime_host

subroutine runtime_state(kind,number) bind(C,name='nci_test_runtime_state')
  use, intrinsic :: iso_c_binding, only: c_int32_t
  use openacc
  implicit none
  integer(c_int32_t), intent(out) :: kind,number
  integer(acc_device_kind) :: current
  current=acc_get_device_type()
  kind=int(current,c_int32_t)
  number=int(acc_get_device_num(current),c_int32_t)
end subroutine runtime_state
