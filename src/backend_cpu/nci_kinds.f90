! SPDX-License-Identifier: MIT
!> Kind parameters, IEEE-754 bit helpers and frozen binary64 constants of the
!> CPU core.  Nothing here holds mutable state.
module nci_kinds
  use, intrinsic :: iso_c_binding, only: c_double, c_int8_t, c_int32_t, c_int64_t
  implicit none
  private

  integer, parameter, public :: dp = c_double
  integer, parameter, public :: i8 = c_int8_t
  integer, parameter, public :: i32 = c_int32_t
  integer, parameter, public :: i64 = c_int64_t

  !> binary64 machine epsilon 2**-52 and unit roundoff u = 2**-53.
  real(dp), parameter, public :: EPS_MACH = epsilon(1.0_dp)
  real(dp), parameter, public :: U_ROUND = 0.5_dp*EPS_MACH

  !> gamma_n = n*u/(1 - n*u) (Higham), used by the a-priori rounding bounds.
  real(dp), parameter, public :: GAMMA4 = (4*U_ROUND)/(1.0_dp - 4*U_ROUND)
  real(dp), parameter, public :: GAMMA12 = (12*U_ROUND)/(1.0_dp - 12*U_ROUND)

  !> RDG constant C = 2*(3*pi**2)**(1/3).  The literal is the 80-digit decimal
  !> value; the nearest binary64 is fixed by C_RDG_BITS (see docs/cpu-core.md).
  real(dp), parameter, public :: C_RDG = 6.1873354525602718619378904144447739159_dp
  integer(i64), parameter, public :: C_RDG_BITS = int(z'4018BFD4DD6882CB', i64)

  !> Canonical quiet NaN written to every expected-invalid output.
  integer(i64), parameter, public :: QNAN_BITS = int(z'7FF8000000000000', i64)

  integer(i64), parameter :: EXPONENT_MASK = 2047_i64

  public :: qnan, is_finite, all_finite

contains

  pure function qnan() result(x)
    real(dp) :: x
    x = transfer(QNAN_BITS, 1.0_dp)
  end function qnan

  !> Finite test on the bit pattern: never raises an IEEE exception.
  elemental function is_finite(x) result(ok)
    real(dp), intent(in) :: x
    logical :: ok
    ok = iand(shiftr(transfer(x, 0_i64), 52), EXPONENT_MASK) /= EXPONENT_MASK
  end function is_finite

  pure function all_finite(n, x) result(ok)
    integer, intent(in) :: n
    real(dp), intent(in) :: x(n)
    logical :: ok
    integer :: i
    ok = .true.
    do i = 1, n
      if (.not. is_finite(x(i))) then
        ok = .false.
        return
      end if
    end do
  end function all_finite

end module nci_kinds
