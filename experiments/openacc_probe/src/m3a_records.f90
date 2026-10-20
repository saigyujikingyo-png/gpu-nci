! SPDX-License-Identifier: MIT
!> M3A probe: one record of each kind (docs/openacc-probe-contract.md),
!> evaluated only by calls to the actual production procedures. The same
!> source is compiled into the host reference (without OpenACC, where the
!> !$acc lines are comments) and into the device driver, each against its own
!> build of nci_kinds/nci_numerics.
module m3a_records
  use nci_kinds, only: dp, qnan, is_finite, pow2_scale, binary_exponent, binary_fraction
  use nci_numerics, only: point_result, point_eval, rdg_from_gradient, c_cbrt
  implicit none
  private
  public :: scalar_record, rdg_record, point_record

contains

  !> Finite classification; binary exponent and fraction on finite input only
  !> (otherwise exponent 0 and the canonical NaN); power-of-two scaling and
  !> cube root of every input.
  pure subroutine scalar_record(x, scale_exponent, finite, exponent, fraction, scaled, cube_root)
    !$acc routine seq
    real(dp), intent(in) :: x
    integer, intent(in) :: scale_exponent
    logical, intent(out) :: finite
    integer, intent(out) :: exponent
    real(dp), intent(out) :: fraction, scaled, cube_root
    finite = is_finite(x)
    if (finite) then
      exponent = binary_exponent(x)
      fraction = binary_fraction(x)
    else
      exponent = 0
      fraction = qnan()
    end if
    scaled = pow2_scale(x, scale_exponent)
    cube_root = c_cbrt(x)
  end subroutine scalar_record

  !> Standalone RDG helper; the reader guarantees a finite gradient and rho > 0.
  pure subroutine rdg_record(gradient, rho, rdg)
    !$acc routine seq
    real(dp), intent(in) :: gradient(3), rho
    real(dp), intent(out) :: rdg
    rdg = rdg_from_gradient(gradient, rho)
  end subroutine rdg_record

  !> One complete point evaluation with absm = abs(m) and the given floor.
  pure subroutine point_record(blk, m, floor_abs, max_rot, res)
    !$acc routine seq
    real(dp), intent(in) :: blk(-2:2, -2:2, -2:2), m(3, 3), floor_abs
    integer, intent(in) :: max_rot
    type(point_result), intent(out) :: res
    real(dp) :: absm(3, 3)
    absm = abs(m)
    call point_eval(blk, m, absm, floor_abs, max_rot, res)
  end subroutine point_record

end module m3a_records
