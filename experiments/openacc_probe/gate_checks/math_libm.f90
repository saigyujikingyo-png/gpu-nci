! SPDX-License-Identifier: MIT
!> Compile/link-only purity gate reproducer, never executed (see
!> docs/openacc-probe-implementation.md). Variant LIBM: pure device routines
!> call real(8) scalbn and cbrt of the NVHPC LIBM module, as the probe shim does.
module gate_math
  use, intrinsic :: iso_c_binding, only: c_double, c_int
  use libm, only: c_scalbn => scalbn, c_cbrt => cbrt
  implicit none
  private
  public :: gate_scale, gate_cbrt

contains

  pure elemental function gate_scale(x, n) result(y)
    !$acc routine seq
    real(c_double), intent(in) :: x
    integer, intent(in) :: n
    real(c_double) :: y
    y = c_scalbn(x, int(n, c_int))
  end function gate_scale

  pure function gate_cbrt(x) result(y)
    !$acc routine seq
    real(c_double), intent(in) :: x
    real(c_double) :: y
    y = c_cbrt(x)
  end function gate_cbrt

end module gate_math
