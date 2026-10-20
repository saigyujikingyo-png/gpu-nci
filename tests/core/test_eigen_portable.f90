! SPDX-License-Identifier: MIT
! FP64-only forced-path test. Does not replace the binary128 reference tests.
program test_eigen_portable
  use nci_kinds, only: dp, EPS_MACH, is_finite
  use nci_numerics, only: EIG_OK, EIG_NONCONVERGED, JACOBI_MAX_ROTATIONS
  use nci_test_hooks, only: hook_eig3
  implicit none
  real(dp), parameter :: h6(6)=[2.0_dp,2.0_dp,2.0_dp,1.0_dp,1.0_dp,1.0_dp]
  real(dp), parameter :: exact(3)=[1.0_dp,1.0_dp,4.0_dp]
  real(dp) :: lam(3), bound
  integer :: nrot,info,ncheck=0
  call hook_eig3(h6,1,lam,bound,nrot,info)
  call check(info==EIG_NONCONVERGED,'one rotation must be nonconverged')
  call check(nrot==1,'forced cap consumed exactly one rotation')
  call hook_eig3(h6,JACOBI_MAX_ROTATIONS,lam,bound,nrot,info)
  call check(info==EIG_OK,'30 rotations allow convergence')
  call check(nrot<=JACOBI_MAX_ROTATIONS,'production rotation cap')
  call check(all(is_finite(lam)),'finite eigenvalues')
  call check(lam(1)<=lam(2).and.lam(2)<=lam(3),'algebraic sorting')
  ! Same stopping-rule accuracy scale as the unchanged quad test, known roots.
  call check(maxval(abs(lam-exact))<=80.0_dp*EPS_MACH*4.0_dp,'known roots 1,1,4')
  call check(is_finite(bound).and.bound>=0.0_dp,'finite nonnegative bound')
  call check(maxval(abs(lam-exact))<=bound,'known-root error covered by bound')
  print '(a,i0,a)', 'portable eigen: ',ncheck,' checks passed (FP64 only)'
contains
  subroutine check(ok,label)
    logical, intent(in) :: ok
    character(len=*), intent(in) :: label
    if (.not.ok) then
      print '(a,a)', 'FAIL: ',label
      error stop 1
    end if
    ncheck=ncheck+1
  end subroutine
end program
