! SPDX-License-Identifier: MIT
!> TEST-ONLY numerical hooks (built only with -DNCI_BUILD_TEST_HOOKS=ON and
!> linked only into test executables).  They expose the internal Jacobi and
!> point routines with an explicit rotation cap so that the nonconvergence
!> branch can be exercised (numerics.md section 4).  The production library
!> always passes JACOBI_MAX_ROTATIONS = 30 and exports none of this.
module nci_test_hooks
  use nci_kinds
  use nci_numerics
  implicit none
  private
  public :: hook_eig3, hook_point_eval

contains

  pure subroutine hook_eig3(h6, max_rotations, lam, bound, nrot, info)
    real(dp), intent(in) :: h6(6)
    integer, intent(in) :: max_rotations
    real(dp), intent(out) :: lam(3), bound
    integer, intent(out) :: nrot, info
    call eig3_jacobi(h6, max_rotations, lam, bound, nrot, info)
  end subroutine hook_eig3

  pure subroutine hook_point_eval(blk, m, max_rotations, res)
    real(dp), intent(in) :: blk(-2:2, -2:2, -2:2), m(3, 3)
    integer, intent(in) :: max_rotations
    type(point_result), intent(out) :: res
    real(dp) :: absm(3, 3)
    absm = abs(m)
    call point_eval(blk, m, absm, underflow_floor(absm), max_rotations, res)
  end subroutine hook_point_eval

end module nci_test_hooks
