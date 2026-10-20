! SPDX-License-Identifier: MIT
! Exact endpoint fixtures are bit patterns, not values made by SCALE.
program test_pow2_portable
  use nci_kinds, only: dp,i64,pow2_scale,is_finite,binary_exponent,binary_fraction
  use nci_numerics, only: fro_norm,hypot2,EIG_OK,JACOBI_MAX_ROTATIONS
  use nci_test_hooks, only: hook_eig3
  use nci_validate, only: jinv_condition,COND_ACCEPTED
  implicit none
  real(dp) :: hi,sub1,sub2,sub3,sub4,sub5,lam(3),bound,h6(6),jinv(9),kappa,half,quarters,eighths
  integer :: checks=0,nrot,info,verdict
  hi=from_bits(int(z'7FE8000000000000',i64))
  sub1=from_bits(1_i64);sub2=from_bits(2_i64);sub3=from_bits(3_i64)
  sub4=from_bits(4_i64);sub5=from_bits(5_i64)
  half=from_bits(int(z'3FE0000000000000',i64))
  quarters=from_bits(int(z'3FE8000000000000',i64))
  eighths=from_bits(int(z'3FD8000000000000',i64))
  call check(pow2_scale(quarters,1024)==hi,'representable upper exponent')
  call check(pow2_scale(eighths,1025)==hi,'unnormalized upper exponent')
  call check(pow2_scale(half,-1073)==sub1,'least subnormal')
  call check(pow2_scale(quarters,-1073)==sub2,'subnormal nearest-even rounding')
  call check(pow2_scale(quarters,-1074)==sub1,'subnormal rounding above half ulp')
  call check(pow2_scale(sub1,1073)==half,'least-subnormal input normalization')
  call check(pow2_scale(hi,-1024)==quarters,'large input normalization')
  call check(pow2_scale(0.0_dp,1073)==0.0_dp,'zero with large exponent')
  call check(binary_exponent(sub1)==-1073,'least-subnormal exponent')
  call check(binary_exponent(from_bits(16_i64))==-1069,'rho bits16 exponent')
  call check(binary_exponent(-sub1)==-1073,'negative subnormal exponent')
  call check(binary_exponent(hi)==1024,'upper normal exponent')
  call check(binary_exponent(from_bits(0_i64))==0,'zero exponent')
  call check(binary_fraction(sub1)==half,'least-subnormal fraction')
  call check(binary_fraction(-sub1)==-half,'negative subnormal fraction')
  call check(binary_fraction(hi)==quarters,'upper normal fraction')
  call check(fro_norm(3,[hi,0.0_dp,0.0_dp])==hi,'large representable norm')
  call check(fro_norm(3,[sub1,0.0_dp,0.0_dp])==sub1,'least-subnormal norm')
  call check(hypot2(hi,0.0_dp)==hi,'large representable hypot')
  call check(hypot2(sub1,0.0_dp)==sub1,'least-subnormal hypot')
  call check(fro_norm(2,[sub3,sub4])==sub5,'subnormal Pythagorean norm')
  call check(hypot2(sub3,sub4)==sub5,'subnormal Pythagorean hypot')
  h6=[-hi,0.0_dp,hi,0.0_dp,0.0_dp,0.0_dp]
  call hook_eig3(h6,JACOBI_MAX_ROTATIONS,lam,bound,nrot,info)
  call check(info==EIG_OK.and.all(is_finite(lam)).and.all(lam==[-hi,0.0_dp,hi]),'large known eigenvalues')
  call check(nrot==0.and.is_finite(bound),'diagonal large eigenvalues need no rotation, finite contribution')
  h6=[-sub2,sub1,sub3,0.0_dp,0.0_dp,0.0_dp]
  call hook_eig3(h6,JACOBI_MAX_ROTATIONS,lam,bound,nrot,info)
  call check(info==EIG_OK.and.all(lam==[-sub2,sub1,sub3]),'subnormal known eigenvalues')
  call check(nrot==0,'diagonal subnormal eigenvalues need no rotation')
  jinv=0.0_dp;jinv(1)=hi;jinv(5)=hi;jinv(9)=hi
  call jinv_condition(jinv,verdict,kappa)
  call check(verdict==COND_ACCEPTED.and.kappa==1.0_dp,'large Jinv condition one')
  jinv=0.0_dp;jinv(1)=sub1;jinv(5)=sub1;jinv(9)=sub1
  call jinv_condition(jinv,verdict,kappa)
  call check(verdict==COND_ACCEPTED.and.kappa==1.0_dp,'subnormal Jinv condition one')
  print '(a,i0,a)','portable pow2: ',checks,' checks passed (FP64 only)'
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
end program
