! SPDX-License-Identifier: MIT
!> Compile/link-only purity gate reproducer, never executed: one compute
!> region calling the pure device routines of a gate_math variant compiled
!> from a separate file (relocatable device code).
program gate_main
  use gate_math, only: gate_scale, gate_cbrt
  implicit none
  real(8) :: a(2), b(2)
  integer :: i
  a = [8.0d0, 27.0d0]
  !$acc parallel loop copyin(a) copyout(b)
  do i = 1, 2
    b(i) = gate_scale(gate_cbrt(a(i)), i)
  end do
  write(*, '(2(1x,z16.16))') b
end program gate_main
