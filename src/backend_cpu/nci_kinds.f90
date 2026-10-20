! SPDX-License-Identifier: MIT
!> Kind parameters, IEEE-754 bit helpers and frozen binary64 constants of the
!> CPU core.  Nothing here holds mutable state.
module nci_kinds
  use, intrinsic :: iso_c_binding, only: c_double, c_int, c_int8_t, c_int32_t, c_int64_t
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

  public :: qnan, is_finite, all_finite, pow2_scale, binary_exponent, binary_fraction

  interface
    pure function c_scalbn(x,n) bind(C,name='scalbn') result(y)
      import :: c_double,c_int
      real(c_double),value :: x
      integer(c_int),value :: n
      real(c_double) :: y
    end function c_scalbn
  end interface

contains

  !> Portable binary power scaling under the caller's IEEE rounding/denormal
  !> policy. libc scalbn handles representable large/subnormal endpoints where
  !> NVHPC26.9's intrinsic SCALE returned Inf/zero in actual scalar probes.
  !> All production exponents are bounded well within the C int range.
  pure elemental function pow2_scale(x,n) result(y)
    real(dp),intent(in) :: x
    integer,intent(in) :: n
    real(dp) :: y
    y=c_scalbn(x,int(n,c_int))
  end function pow2_scale

  !> frexp/EXPONENT convention for finite IEEE binary64 input; zero -> 0.
  !> NVHPC26.9 returned -1022 for every tested subnormal EXPONENT input.
  !> Extract the stored exponent or highest subnormal mantissa bit directly.
  !> The sign has no effect on this integer exponent. Nonfinite inputs are
  !> outside this helper's contract and are rejected by production callers.
  pure elemental function binary_exponent(x) result(e)
    real(dp),intent(in) :: x
    integer :: e
    integer(i64) :: bits,stored,mantissa
    bits=transfer(x,0_i64)
    stored=iand(shiftr(bits,52),EXPONENT_MASK)
    if (stored>0_i64.and.stored<EXPONENT_MASK) then
      e=int(stored)-1022
    else if (stored==0_i64) then
      mantissa=iand(bits,int(z'000FFFFFFFFFFFFF',i64))
      e=0
      if (mantissa/=0_i64) e=-1073+(bit_size(mantissa)-1-leadz(mantissa))
    else
      e=0
    end if
  end function binary_exponent

  !> Signed fraction for finite IEEE binary64, with signed zero preserved.
  pure elemental function binary_fraction(x) result(f)
    real(dp),intent(in) :: x
    real(dp) :: f
    f=pow2_scale(x,-binary_exponent(x))
  end function binary_fraction

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
