! SPDX-License-Identifier: MIT
! Tiny FP64 range tests; no electronic-structure calculations.
program test_rdg_portable
  use nci_kinds, only: dp,i64,C_RDG,EPS_MACH,is_finite
  use nci_numerics, only: rdg_from_gradient
  implicit none
  real(dp) :: gr(3),rho,actual,expected,smallest
  integer :: checks=0
  gr=0.0_dp
  actual=rdg_from_gradient(gr,0.015625_dp)
  call check(actual==0.0_dp,'zero gradient gives zero RDG')
  gr=[-from_bits(int(z'7F90000000000000',i64)),0.0_dp,0.0_dp];rho=0.015625_dp
  actual=rdg_from_gradient(gr,rho)
  ! 2^1024/(C/4) = 2^1023*(8/C), without constructing 2^1024.
  expected=1.1621759632369337941e308_dp
  call near(actual,expected,'intermediate quotient overflow, final finite')
  gr=[huge(1.0_dp),huge(1.0_dp),0.0_dp];rho=64.0_dp
  actual=rdg_from_gradient(gr,rho)
  expected=(huge(1.0_dp)/(C_RDG*256.0_dp))*sqrt(2.0_dp)
  call near(actual,expected,'physical gradient norm overflows, final finite')
  smallest=from_bits(1_i64)
  gr=smallest;rho=from_bits(int(z'1A70000000000000',i64))
  actual=rdg_from_gradient(gr,rho)
  expected=(sqrt(3.0_dp)/C_RDG)*from_bits(int(z'2ED0000000000000',i64))
  call near(actual,expected,'subnormal gradient norm retains full mantissa')
  gr=smallest;rho=from_bits(int(z'6570000000000000',i64))
  actual=rdg_from_gradient(gr,rho)
  call check(actual==0.0_dp,'genuine final underflow rounds to zero')
  gr=[1.0_dp,0.0_dp,0.0_dp];rho=from_bits(int(z'07B0000000000000',i64))
  actual=rdg_from_gradient(gr,rho)
  call check(.not.is_finite(actual),'genuine final overflow remains nonfinite')
  print '(a,i0,a)','portable RDG: ',checks,' checks passed (FP64 only)'
contains
  function from_bits(bits) result(value)
    integer(i64),intent(in) :: bits
    real(dp) :: value
    integer(i64),volatile :: runtime_bits
    runtime_bits=bits
    value=transfer(runtime_bits,value)
  end function
  subroutine check(ok,label)
    logical,intent(in) :: ok
    character(len=*),intent(in) :: label
    if (.not.ok) then
      print '(a,a)','FAIL: ',label
      error stop 1
    end if
    checks=checks+1
  end subroutine
  subroutine near(value,reference,label)
    real(dp),intent(in) :: value,reference
    character(len=*),intent(in) :: label
    call check(is_finite(value),label//' finite')
    call check(abs(value/reference-1.0_dp)<=16.0_dp*EPS_MACH,label//' relative agreement')
  end subroutine
end program
