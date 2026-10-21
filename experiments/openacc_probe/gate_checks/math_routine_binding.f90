! SPDX-License-Identifier: MIT
!> Compile/link-only purity gate reproducer, never executed (see
!> docs/openacc-probe-implementation.md). Variant ROUTINE_BINDING: the
!> production pure bind(C) interfaces to scalbn and cbrt, unchanged except
!> for an added device routine declaration in each interface body.
module gate_math
  use, intrinsic :: iso_c_binding, only: c_double, c_int
  implicit none
  private
  public :: gate_scale, gate_cbrt

  interface
    pure function c_scalbn(x,n) bind(C,name='scalbn') result(y)
      !$acc routine seq
      import :: c_double,c_int
      real(c_double),value :: x
      integer(c_int),value :: n
      real(c_double) :: y
    end function c_scalbn
    pure function c_cbrt(x) bind(C, name='cbrt') result(y)
      !$acc routine seq
      import :: c_double
      real(c_double), value :: x
      real(c_double) :: y
    end function c_cbrt
  end interface

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
